import uvicorn
from fastapi import FastAPI, UploadFile, File, Depends, Query, HTTPException, Form, status
from typing import List, Tuple
from fastapi.middleware.cors import CORSMiddleware
from app.database import get_db
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.routes.auth import router as auth_router
from app.models import Business, User, Document, QueryLog, Organization, OrgMember
from app.rag import (
    ingest_document,
    retrieve_chunks,
    retrieve_chunks_multi,
    check_search_limit,
    increment_search_count,
    check_rate_limit,
    clear_active_query,
    get_active_query,
    set_active_query,
    normalize_query,
    PLAN_CONFIG,
)
from app.llm import generate_answer
from pydantic import BaseModel, Field
from app.auth import get_current_user
import os
import uuid
from datetime import datetime, timezone
from math import ceil
from app.routes.billing import router as billing_router


# ── Request / Response models ──────────────────────────────────────────────────
class DocumentsRequest(BaseModel):
    business_ids: List[int]
    page: int = 1
    page_size: int = 10

class BusinessSettingsUpdate(BaseModel):
    business_id: int = Field(..., description="The unique ID of the business being updated")
    query_allocation: int = Field(..., ge=0, description="The maximum number of allowed searches")

class AskRequest(BaseModel):
    question:    str
    get_k:       int = 3
    offset:      int = 0
    business_id: int

class CreateBusinessRequest(BaseModel):
    name: str
    org_id: int

class BusinessResponse(BaseModel):
    id:   int
    name: str
    model_config = {"from_attributes": True}

class DocumentRequest(BaseModel):
    business_ids: List[int]
    page:         int = 1
    page_size:    int = 50

class DocumentResponseItem(BaseModel):
    id:     int
    name:   str
    type:   str
    status: str

class DocumentListResponse(BaseModel):
    documents: List[DocumentResponseItem]

class OrgCreateSchema(BaseModel):
    name: str

class OrgResponseSchema(BaseModel):
    id: int
    name: str
    owner_id: int
    is_active: bool

    class Config:
        from_attributes = True


# ── App setup ──────────────────────────────────────────────────────────────────
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)

def enforce_business_quota(db: Session, business_id: int, user_id: int):
    # 1. Fetch the business and organization ownership framework
    business = db.query(Business).filter(Business.id == business_id).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business profile not found")
        
    org = db.query(Organization).filter(Organization.id == business.org_id).first()
    billing_owner = db.query(User).filter(User.id == org.owner_id).first()
    
    # 2. Derive the 30-day window anchor
    start_of_period = billing_owner.stripe_current_period_start or billing_owner.created_at
    if not start_of_period:
        start_of_period = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0)

    # 3. Check business-specific usage
    business_usage = db.query(func.count(QueryLog.id)).filter(
        QueryLog.business_id == business_id,
        QueryLog.created_at >= start_of_period
    ).scalar() or 0
    
    if business_usage >= business.query_allocation:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This location workspace has exhausted its allocated search quota for the billing period."
        )

# ── Helpers ────────────────────────────────────────────────────────────────────
def get_business_doc_state(db: Session, business_id: int) -> dict:
    latest_doc = (
        db.query(Document)
        .filter(Document.business_id == business_id)
        .order_by(Document.id.desc())
        .first()
    )
    count = db.query(Document).filter(Document.business_id == business_id).count()
    return {
        "document_count":    count,
        "latest_document_id": latest_doc.id if latest_doc else None,
    }


# ── Routes ─────────────────────────────────────────────────────────────────────
@app.get("/")
def read_root():
    return {"Hello": "World"}


app.include_router(billing_router)


@app.post("/upload-multiple")
async def upload_documents(
    business_id:     int              = Form(...),
    current_context: User             = Depends(get_current_user),
    files:           List[UploadFile] = File(...),
    db:              Session          = Depends(get_db),
):
    user, _ = current_context

    user_org_ids = [
        membership.org_id for membership in db.query(OrgMember)
        .filter(OrgMember.user_id == user.id)
        .all()
    ]

    business = (
        db.query(Business)
        .filter(Business.id == business_id, Business.org_id.in_(user_org_ids))
        .first()
    )
    
    if not business:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Business not found or you are not authorized to access it."
        )

    uploaded = []
    for file in files:
        temp_path = f"/tmp/{uuid.uuid4()}_{file.filename}"
        with open(temp_path, "wb") as f:
            f.write(await file.read())

        doc = Document(
            business_id=business.id,
            filename=file.filename,
            content="",
            status="ready",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        chunks_count = ingest_document(
            db=db,
            business_id=business.id,
            document_id=doc.id,
            file_path=temp_path,
            mime_type=file.content_type,
            filename=file.filename,
        )

        uploaded.append({
            "filename":    file.filename,
            "document_id": doc.id,
            "chunks":      chunks_count,
        })
        os.remove(temp_path)

    clear_active_query(user.id)
    return {"uploaded": uploaded}


@app.post("/documents", response_model=DocumentListResponse, status_code=status.HTTP_200_OK)
async def get_documents(
    payload:      DocumentRequest,
    db:           Session = Depends(get_db),
    current_auth          = Depends(get_current_user),
):
    user, _ = current_auth
    
    user_org_ids = [
        membership.org_id for membership in db.query(OrgMember)
        .filter(OrgMember.user_id == user.id)
        .all()
    ]
    
    allowed_businesses = (
        db.query(Business.id)
        .filter(Business.org_id.in_(user_org_ids))
        .all()
    )
    allowed_business_ids = {b.id for b in allowed_businesses}

    for requested_id in payload.business_ids:
        if requested_id not in allowed_business_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Not authorized to view business ID: {requested_id}",
            )

    offset = (payload.page - 1) * payload.page_size
    query_results = (
        db.query(Document)
        .filter(Document.business_id.in_(payload.business_ids))
        .order_by(Document.created_at.desc())
        .offset(offset)
        .limit(payload.page_size)
        .all()
    )

    formatted_docs = []
    for doc in query_results:
        ext = doc.filename.split(".")[-1].upper() if "." in doc.filename else "FILE"
        formatted_docs.append(DocumentResponseItem(
            id=doc.id, name=doc.filename, type=ext, status=doc.status
        ))

    return DocumentListResponse(documents=formatted_docs)


@app.get("/me/businesses")
def get_my_businesses(
    db:           Session = Depends(get_db),
    current_user          = Depends(get_current_user),
):
    user, _ = current_user
    
    user_org_ids = [
        membership.org_id for membership in db.query(OrgMember)
        .filter(OrgMember.user_id == user.id)
        .all()
    ]
    
    if not user_org_ids:
        return {"businesses": []}
        
    db_businesses = (
        db.query(Business)
        .filter(Business.org_id.in_(user_org_ids))
        .all()
    )
    
    return {
        "businesses": [
            {
                "id": b.id, 
                "name": b.name,
                "org_id": b.org_id
            } 
            for b in db_businesses
        ]
    }

# Updated route to a static path, pulling everything from the body payload
@app.patch("/businesses/settings")
async def update_business_settings(
    settings_data: BusinessSettingsUpdate,
    current_auth = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user, _ = current_auth

    # 1. Look up the business target using the body data
    business = db.query(Business).filter(Business.id == settings_data.business_id).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business profile location not found.")

    # 2. Authorization guard: Verify user belongs to the parent organization workspace
    org = db.query(Organization).filter(Organization.id == business.org_id).first()
    if not org or org.owner_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Unauthorized: Only the workspace workspace owner can change resource allocations."
        )

    # 3. Apply changes and commit transaction record pipeline
    plan_limit = PLAN_CONFIG.get(user.plan.lower(), PLAN_CONFIG["free"]).get("monthly_searches", 50)
    
    # Calculate the current allocated pool across ALL businesses owned by this user
    # We join Organization to ensure we match the owner_id across potentially multiple workspaces
    total_currently_allocated = (
        db.query(func.sum(Business.query_allocation))
        .join(Organization, Business.org_id == Organization.id)
        .filter(Organization.owner_id == user.id)
        .scalar() or 0
    )
    
    # Calculate what the new grand total would be if we accept this patch request
    projected_total_allocation = (total_currently_allocated - business.query_allocation) + settings_data.query_allocation
    
    if projected_total_allocation > plan_limit:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Allocation limit exceeded. Your plan allow maximum {plan_limit} queries across all locations. "
                   f"Requested changes would bring your total allocated workspace pool to {projected_total_allocation}."
        )

    business.query_allocation = settings_data.query_allocation
    
    db.add(business)
    db.commit()
    db.refresh(business)

    return {
        "message": "Business resource settings updated successfully.", 
        "business_id": business.id,
        "query_allocation": business.query_allocation
    }

@app.get("/auth/me")
async def get_current_user_profile(
    current_auth = Depends(get_current_user)
):
    """
    Returns the authenticated user profile information 
    along with plan tier limit constraints dynamically.
    """
    user, _ = current_auth
    
    # Safely derive the user's plan key
    user_plan = user.plan.lower() if hasattr(user, "plan") and user.plan else "free"
    
    # Grab the specific configuration from PLAN_CONFIG with a safe fallback to free
    tier_config = PLAN_CONFIG.get(user_plan, PLAN_CONFIG["free"])
    
    return {
        "id": user.id,
        "email": user.email,
        "name": getattr(user, "name", "User"),
        "plan": user_plan,
        # Dynamically map the allocation configuration boundaries
        "max_businesses": tier_config.get("max_businesses", 1),
        "max_organizations": tier_config.get("max_organizations", 1),
        "max_queries": tier_config.get("monthly_searches", 50) # 👈 Added for analytics/dashboard guards
    }

ANSWER_PAGE_SIZE    = 10
CHUNK_BATCH_SIZE    = 3
RETRIEVAL_POOL_SIZE = 50
MAX_LLM_CALLS       = 10


@app.post("/ask")
def ask_question(
    body:            AskRequest,
    db:              Session = Depends(get_db),
    current_context          = Depends(get_current_user),
):
    user, _ = current_context

    # ── 1. Secure Multi-Tenant Membership Check ──
    user_org_ids = [
        membership.org_id for membership in db.query(OrgMember)
        .filter(OrgMember.user_id == user.id)
        .all()
    ]
    
    business = (
        db.query(Business)
        .filter(Business.id == body.business_id, Business.org_id.in_(user_org_ids))
        .first()
    )
    if not business or not business.organization:
        raise HTTPException(status_code=403, detail="You do not have access to this business")

    org = business.organization
    
    # ── 2. Derive Plan Limits dynamically from User Profile ──
    user_plan = user.plan if hasattr(user, "plan") else "free"
    config = PLAN_CONFIG.get(user_plan, PLAN_CONFIG["free"])

    # Rate limit check evaluation using user's plan tier context
    if not check_rate_limit(user.id, user_plan):
        raise HTTPException(status_code=429, detail="Too many requests. Please slow down.")

    # Monthly quota validation checks
    answer_offset = body.offset or 0
    if answer_offset == 0:
        allowed, current, limit = check_search_limit(org.id, user_plan)
        if not allowed:
            raise HTTPException(
                status_code=402,
                detail={
                    "message":     f"Monthly search limit of {limit} reached.",
                    "current":     current,
                    "limit":       limit,
                    "upgrade_url": "/pricing",
                },
            )

    # ── Cache validation checks ──────────────────────────────────────────────────
    current_doc_state = get_business_doc_state(db, body.business_id)
    cached            = get_active_query(user.id)

    cache_is_valid = (
        cached
        and cached.get("question")    == normalize_query(body.question)
        and cached.get("business_id") == body.business_id
        and cached.get("doc_state")   == current_doc_state
    )

    if cache_is_valid:
        print("[Cache] HIT")
        all_answers       = cached.get("answers", [])
        retrieval_results = cached.get("retrieval_results", [])
        next_chunk_offset = cached.get("next_chunk_offset", 0)
    else:
        print("[Cache] MISS — running retrieval")

        if config["use_multiquery"]:
            retrieval         = retrieve_chunks_multi(
                db=db, business_id=body.business_id,
                query=body.question, get_k=RETRIEVAL_POOL_SIZE, offset=0,
            )
            retrieval_results = retrieval["allResults"]
        elif config["use_hyde"]:
            retrieval         = retrieve_chunks(
                db=db, business_id=body.business_id,
                query=body.question, get_k=RETRIEVAL_POOL_SIZE,
                offset=0, use_hyde=True,
            )
            retrieval_results = retrieval["results"]
        else:
            retrieval         = retrieve_chunks(
                db=db, business_id=body.business_id,
                query=body.question, get_k=RETRIEVAL_POOL_SIZE,
                offset=0, use_hyde=False,
            )
            retrieval_results = retrieval["results"]

        all_answers       = []
        next_chunk_offset = 0

        increment_search_count(org.id)

    # ── Engine Tokenization Core Pipeline Loop ──────────────────────────────────
    target    = answer_offset + ANSWER_PAGE_SIZE
    llm_calls = 0

    while (
        len(all_answers) < target
        and next_chunk_offset is not None
        and llm_calls < MAX_LLM_CALLS
    ):
        chunks = retrieval_results[next_chunk_offset: next_chunk_offset + CHUNK_BATCH_SIZE]
        if not chunks:
            next_chunk_offset = None
            break

        generated    = generate_answer(body.question, chunks)
        new_answers  = generated.get("answers", [])
        all_answers.extend(new_answers)

        next_chunk_offset += CHUNK_BATCH_SIZE
        llm_calls         += 1

        if next_chunk_offset >= len(retrieval_results):
            next_chunk_offset = None

    set_active_query(
        user_id=user.id,
        question=body.question,
        business_id=body.business_id,
        doc_state=current_doc_state,
        answers=all_answers,
        retrieval_results=retrieval_results,
        next_chunk_offset=next_chunk_offset,
    )

    page_answers = all_answers[answer_offset: answer_offset + ANSWER_PAGE_SIZE]
    has_more     = (
        answer_offset + ANSWER_PAGE_SIZE < len(all_answers)
        or next_chunk_offset is not None
    )
    next_offset  = answer_offset + ANSWER_PAGE_SIZE if has_more else None

    if answer_offset == 0:
        db.add(QueryLog(
            org_id         = org.id,
            business_id    = body.business_id,
            user_id        = user.id,
            query_text     = body.question,
            answer         = {"answers": page_answers},
            retrieval_plan = (
                "multiquery" if config["use_multiquery"]
                else "hyde"  if config["use_hyde"]
                else "basic"
            ),
        ))
        db.commit()

    if not page_answers:
        return {
            "answer":      {"answers": []},
            "sources":     [],
            "chunks_used": 0,
            "hasMore":     False,
            "nextOffset":  None,
        }

    return {
        "answer":      {"answers": page_answers},
        "sources":     list({
            source["filename"]
            for item in page_answers
            for source in item.get("sources", [])
        }),
        "chunks_used": len(page_answers),
        "hasMore":     has_more,
        "nextOffset":  next_offset,
        "usage": {
            "searches_used":  None, # Overridden dynamically if verified via check_search_limit helpers
            "searches_limit": config["monthly_searches"],
        },
    }

@app.get("/auth/usage-metrics")
async def get_comprehensive_usage_metrics(
    org_id: int,
    current_auth = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user, _ = current_auth
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Organization context workspace not found.")
    is_owner = (org.owner_id == user.id)


    # Resolve billing dates based on owner anchor
    billing_owner = user if is_owner else db.query(User).filter(User.id == org.owner_id).first()
    
    # Gold standard: use Stripe period anchor. Fallback: dynamic start of current month.
    start_of_period = billing_owner.stripe_current_period_start if (billing_owner and billing_owner.stripe_current_period_start) else datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # 1. Fetch global stats
    total_combined_usage = db.query(func.count(QueryLog.id)).filter(
        QueryLog.org_id == org_id, QueryLog.created_at >= start_of_period
    ).scalar() or 0

    personal_user_usage = db.query(func.count(QueryLog.id)).filter(
        QueryLog.org_id == org_id, QueryLog.user_id == user.id, QueryLog.created_at >= start_of_period
    ).scalar() or 0

    # 2. Fetch specific business-level allocations and current counts
    businesses = db.query(Business).filter(Business.org_id == org_id).all()
    business_breakdown = []
    
    for biz in businesses:
        biz_count = db.query(func.count(QueryLog.id)).filter(
            QueryLog.business_id == biz.id, QueryLog.created_at >= start_of_period
        ).scalar() or 0
        
        business_breakdown.append({
            "id": biz.id,
            "name": biz.name,
            "allocation": biz.query_allocation,
            "usage": biz_count
        })

    return {
        "is_owner": is_owner,
        "max_queries_allowed": PLAN_CONFIG.get(billing_owner.plan.lower(), PLAN_CONFIG["free"]).get("monthly_searches", 50),
        "total_combined_usage": total_combined_usage,
        "personal_user_usage": personal_user_usage,
        "businesses": business_breakdown
    }

@app.post(
    "/organizations", 
    response_model=OrgResponseSchema, 
    status_code=status.HTTP_201_CREATED
)
async def create_organization(
    payload: OrgCreateSchema, 
    db: Session = Depends(get_db), 
    current_auth = Depends(get_current_user)
):
    """
    Creates an organization workspace. Inspects the user's personal billing tier
    limits dynamically to control how many workspaces they can cleanly own.
    """
    user, _ = current_auth
    
    # 1. Fetch user's global plan configurations dynamically
    user_plan = user.plan if hasattr(user, "plan") else "free"
    config = PLAN_CONFIG.get(user_plan, PLAN_CONFIG["free"])
    max_orgs = config.get("max_organizations", 1) # Defaulting cleanly to 1 if not declared
    
    # 2. Count how many organizations this user owns
    owned_org_count = db.query(Organization).filter(Organization.owner_id == user.id).count()
    if owned_org_count >= max_orgs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Subscription account tier cap reached: Your current '{user_plan}' plan allows a maximum of {max_orgs} active organization workspaces."
        )
        
    try:
        # 3. Instantiate organization (Plan fields removed here—now derived from owner relation)
        new_org = Organization(
            name=payload.name,
            owner_id=user.id,
            is_active=True
        )
        db.add(new_org)
        db.flush() 

        # 4. Automatically insert creator as administrator
        org_membership = OrgMember(
            org_id=new_org.id,
            user_id=user.id,
            role="admin"
        )
        db.add(org_membership)
        
        db.commit()
        db.refresh(new_org)
        
        return new_org

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to provision system workspace metadata safely: {str(e)}"
        )


@app.get(
    "/organizations", 
    response_model=List[OrgResponseSchema], 
    status_code=status.HTTP_200_OK
)
async def get_user_organizations(
    db: Session = Depends(get_db), 
    current_auth = Depends(get_current_user)
):
    user, _ = current_auth
    try:
        user_orgs = (
            db.query(Organization)
            .join(OrgMember, OrgMember.org_id == Organization.id)
            .filter(OrgMember.user_id == user.id)
            .all()
        )
        return user_orgs
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to query user workspace membership profiles safely: {str(e)}"
        )


@app.post("/businesses", response_model=BusinessResponse)
def create_business_route(
    body: CreateBusinessRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    user, _ = current_user
    
    business_name = body.name.strip()
    if not business_name:
        raise HTTPException(status_code=400, detail="Business name is required")

    membership = (
        db.query(OrgMember)
        .filter(OrgMember.org_id == body.org_id, OrgMember.user_id == user.id)
        .first()
    )
    if not membership:
        raise HTTPException(
            status_code=403, 
            detail="You do not have permission to modify this organization workspace"
        )

    org = db.query(Organization).filter(Organization.id == body.org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    if not org.is_active:
        raise HTTPException(status_code=402, detail="Your organization workspace is inactive")

    business = Business(name=business_name, org_id=org.id)
    db.add(business)
    db.commit()
    db.refresh(business)

    return business


@app.get("/queries/recent")
def get_recent_queries(
    business_id: int     = Query(...),
    page:        int     = Query(1, ge=1),
    page_size:   int     = Query(10, ge=1, le=50),
    db:          Session = Depends(get_db),
    current_user         = Depends(get_current_user),
):
    user, _ = current_user

    user_org_ids = [
        membership.org_id for membership in db.query(OrgMember)
        .filter(OrgMember.user_id == user.id)
        .all()
    ]
    
    business = (
        db.query(Business)
        .filter(Business.id == business_id, Business.org_id.in_(user_org_ids))
        .first()
    )
    if not business:
        raise HTTPException(status_code=403, detail="Access denied.")

    query = (
        db.query(QueryLog)
        .filter(QueryLog.business_id == business_id)
        .order_by(QueryLog.id.desc())
    )

    total   = query.count()
    queries = query.offset((page - 1) * page_size).limit(page_size).all()

    return {
        "page":      page,
        "page_size": page_size,
        "total":     total,
        "has_more":  page * page_size < total,
        "queries": [
            {"id": q.id, "question": q.query_text, "answer": q.answer}
            for q in queries
        ],
    }


@app.delete("/documents/{document_id}")
def delete_document(
    document_id:  int,
    business_id:  int     = Query(...),
    db:           Session = Depends(get_db),
    current_user          = Depends(get_current_user),
):
    user, _ = current_user

    user_org_ids = [
        membership.org_id for membership in db.query(OrgMember)
        .filter(OrgMember.user_id == user.id)
        .all()
    ]

    business = (
        db.query(Business)
        .filter(Business.id == business_id, Business.org_id.in_(user_org_ids))
        .first()
    )
    if not business:
        raise HTTPException(status_code=403, detail="Not authorized to edit this workspace entity.")

    doc = (
        db.query(Document)
        .filter(Document.id == document_id, Document.business_id == business_id)
        .first()
    )
    if not doc:
        raise HTTPException(404, "Document not found")

    from app.models import Chunk
    db.query(Chunk).filter(Chunk.document_id == document_id).delete()
    db.delete(doc)
    db.commit()

    clear_active_query(user.id)
    return {"message": "Document deleted successfully"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)