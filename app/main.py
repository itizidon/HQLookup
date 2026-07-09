import uvicorn
from fastapi import FastAPI, UploadFile, File, Depends, Query, HTTPException, Form, status
from typing import List, Tuple
from fastapi.middleware.cors import CORSMiddleware
from app.database import get_db
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.routes.auth import router as auth_router
from app.models import Business, User, Document, QueryLog, Organization, OrgMember, user_business
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
from pydantic import BaseModel, Field, EmailStr
from app.auth import get_current_user
import os
import uuid
from datetime import datetime, timezone
from math import ceil
from app.routes.billing import router as billing_router

import jwt  # pyjwt
import resend
from datetime import datetime, timedelta, timezone

# Configure your keys (In production, load these from os.environ)
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your_super_secret_signing_key_change_this_in_production")
JWT_ALGORITHM = "HS256"

resend.api_key = os.getenv("RESEND_API_KEY")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000") # Your frontend app domain


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


class AcceptInviteRequest(BaseModel):
    token: str
    password: str = Field(..., min_length=6, description="Password required only for new accounts")
    name: str = "User"

# Place this in your "Request / Response models" section at the top of the file:
class OrgInviteRequest(BaseModel):
    email: EmailStr
    role: str = "member"
    business_ids: List[int] = []

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


@app.get("/auth/verify-invite")
def verify_invite_token(token: str, db: Session = Depends(get_db)):
    """Frontend calls this on page load to see if the token is valid and checks if user exists."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        email = payload["email"]
        
        # Check if they already have an account in your ecosystem
        user_exists = db.query(User).filter(User.email == email).first() is not None
        
        return {
            "valid": True,
            "email": email,
            "org_id": payload["org_id"],
            "user_exists": user_exists
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="This invitation link has expired.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=400, detail="Invalid invitation token.")


@app.post("/auth/accept-invite")
def accept_workspace_invitation(body: AcceptInviteRequest, db: Session = Depends(get_db)):
    """Frontend submits the password/name here to seal the registration and map permissions."""
    try:
        payload = jwt.decode(body.token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        raise HTTPException(status_code=400, detail="Invalid or expired invitation token.")

    email = payload["email"]
    org_id = payload["org_id"]
    role = payload["role"]
    business_ids = payload["business_ids"]

    # 1. Fetch or create the user profile record securely
    target_user = db.query(User).filter(User.email == email).first()
    
    if not target_user:
        # For a production application, make sure to hash this password using your auth pass-context!
        # Assuming you use passlib/bcrypt elsewhere in your auth router:
        # from app.routes.auth import pwd_context (or similar hashing helper)
        hashed_pwd = body.password # Replace with your real password hashing helper function
        
        target_user = User(
            email=email,
            name=body.name,
            hashed_password=hashed_pwd,
            plan="free"
        )
        db.add(target_user)
        db.flush()

    # 2. Map organization-wide container membership
    existing_member = db.query(OrgMember).filter(
        OrgMember.org_id == org_id,
        OrgMember.user_id == target_user.id
    ).first()
    
    if not existing_member:
        new_membership = OrgMember(
            org_id=org_id,
            user_id=target_user.id,
            role=role
        )
        db.add(new_membership)

    # 3. Map local multi-property location access bridges
    for biz_id in business_ids:
        already_has_access = db.execute(
            user_business.select().where(
                user_business.c.user_id == target_user.id,
                user_business.c.business_id == biz_id
            )
        ).first()
        
        if not already_has_access:
            db.execute(
                user_business.insert().values(user_id=target_user.id, business_id=biz_id)
            )

    db.commit()
    return {"status": "success", "message": "Workspace onboarding mapped safely. You can now sign in."}

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
    org_id: int,  
    db:           Session = Depends(get_db),
    current_user          = Depends(get_current_user),
):
    user, _ = current_user
    
    # Boundary check: Ensure user belongs to the requested workspace
    membership = db.query(OrgMember).filter(
        OrgMember.org_id == org_id,
        OrgMember.user_id == user.id
    ).first()
    
    if not membership:
        raise HTTPException(
            status_code=403, 
            detail="Access Denied: You are not a member of this workspace container."
        )
        
    org = db.query(Organization).filter(Organization.id == org_id).first()
    is_owner = org and org.owner_id == user.id
    is_admin = membership.role == "admin"

    if is_owner or is_admin:
        # Admins automatically get visibility over ALL properties in the org
        db_businesses = db.query(Business).filter(Business.org_id == org_id).all()
    else:
        # Standard members use the user_business junction table safely
        db_businesses = (
            db.query(Business)
            .join(user_business, Business.id == user_business.c.business_id)
            .filter(
                Business.org_id == org_id,
                user_business.c.user_id == user.id
            )
            .all()
        )
    
    return {
        "businesses": [
            {"id": b.id, "name": b.name, "org_id": b.org_id} 
            for b in db_businesses
        ]
    }

@app.post("/organizations/{org_id}/invite", status_code=status.HTTP_201_CREATED)
async def invite_user_to_workspace(
    org_id: int,
    body: OrgInviteRequest,
    db: Session = Depends(get_db),
    current_auth = Depends(get_current_user),
):
    admin_user, _ = current_auth

    # 1. Fetch organization and verify admin permissions
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization workspace not found.")
        
    admin_membership = db.query(OrgMember).filter(
        OrgMember.org_id == org_id, 
        OrgMember.user_id == admin_user.id
    ).first()
    
    if org.owner_id != admin_user.id and (not admin_membership or admin_membership.role != "admin"):
        raise HTTPException(
            status_code=403, 
            detail="You lack administrative permissions to invite users to this workspace."
        )

    # 2. Enforce your PLAN_CONFIG 'max_users' seat limit caps
    billing_owner = db.query(User).filter(User.id == org.owner_id).first()
    owner_plan = billing_owner.plan.lower() if billing_owner and billing_owner.plan else "free"
    
    config = PLAN_CONFIG.get(owner_plan, PLAN_CONFIG["free"])
    max_seats_allowed = config.get("max_users", 2)

    # Count all members in this specific workspace container
    current_seat_count = db.query(OrgMember).filter(OrgMember.org_id == org_id).count()

    if current_seat_count >= max_seats_allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Workspace seat limit reached: Your current '{owner_plan}' plan allows a maximum of "
                   f"{max_seats_allowed} users. Please upgrade your tier profile to invite more members."
        )

    # 3. Verify business IDs map to this organization layer safely
    valid_biz_count = db.query(Business).filter(
        Business.id.in_(body.business_ids),
        Business.org_id == org_id
    ).count()
    
    if valid_biz_count != len(body.business_ids):
        raise HTTPException(status_code=400, detail="One or more selected Business IDs are invalid for this workspace.")

    # 4. Generate a secure, short-lived Invitation Token (Expires in 7 days)
    token_expiry = datetime.now(timezone.utc) + timedelta(days=7)
    token_payload = {
        "email": body.email,
        "org_id": org_id,
        "role": body.role,
        "business_ids": body.business_ids,
        "exp": token_expiry
    }
    invite_token = jwt.encode(token_payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

    # 5. Build the invite magic URL for your frontend
    invite_link = f"{FRONTEND_URL}/accept-invite?token={invite_token}"

    # 6. Send the transactional email using Resend
    try:
        params = {
            "from": "Acme Team <onboarding@resend.dev>", # Use your verified domain once you set it up in Resend
            "to": [body.email],
            "subject": f"You've been invited to join {org.name}",
            "html": f"""
                <div style="font-family: sans-serif; padding: 20px; color: #333;">
                    <h2>You're invited!</h2>
                    <p><strong>{admin_user.email}</strong> has invited you to collaborate on their team workspace: <strong>{org.name}</strong>.</p>
                    <p>Click the button below to accept your invitation and set up your account. This link will expire in 7 days.</p>
                    <div style="margin: 24px 0;">
                        <a href="{invite_link}" style="background-color: #000; color: #fff; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">
                            Accept Invitation
                        </a>
                    </div>
                    <p style="font-size: 12px; color: #666;">If the button doesn't work, copy and paste this link into your browser:<br>{invite_link}</p>
                </div>
            """
        }
        resend.Emails.send(params)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send invitation email cleanly: {str(e)}"
        )

    return {"message": f"Invitation link generated and emailed to {body.email} successfully."}


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
    user, _ = current_auth
    user_plan = user.plan if hasattr(user, "plan") else "free"
    config = PLAN_CONFIG.get(user_plan, PLAN_CONFIG["free"])
    max_orgs = config.get("max_organizations", 1)
    
    owned_org_count = db.query(Organization).filter(Organization.owner_id == user.id).count()
    if owned_org_count >= max_orgs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Subscription account tier cap reached: Your current '{user_plan}' plan allows a maximum of {max_orgs} active organization workspaces."
        )
        
    try:
        new_org = Organization(name=payload.name, owner_id=user.id, is_active=True)
        db.add(new_org)
        db.flush() 

        org_membership = OrgMember(org_id=new_org.id, user_id=user.id, role="admin")
        db.add(org_membership)
        db.commit()
        db.refresh(new_org)
        
        # Inject the role value directly into the returned object to satisfy OrgResponseSchema
        new_org.role = "admin"
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
        # Querying membership links directly so we can grab both Org data AND your custom member roles
        memberships = db.query(OrgMember).filter(OrgMember.user_id == user.id).all()
        
        formatted_orgs = []
        for m in memberships:
            if m.organization:
                formatted_orgs.append({
                    "id": m.organization.id,
                    "name": m.organization.name,
                    "owner_id": m.organization.owner_id,
                    "is_active": m.organization.is_active,
                    "role": m.role # Populates the newly updated response model parameter
                })
        return formatted_orgs
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