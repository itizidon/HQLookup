import uvicorn
import json
from fastapi import FastAPI, UploadFile, File, Depends, Query, HTTPException, Form, status
from typing import List, Optional
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from app.database import get_db
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.routes.auth import router as auth_router
from app.models import Business, User, Document, QueryLog,Chunk , Organization, OrgMember, Invitation, user_business
from app.rag import (
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
from app.ingestion.pipeline import ingest_document
from app.llm import generate_answer
from pydantic import BaseModel, Field, EmailStr
from app.auth import get_current_user
import os
import uuid
from datetime import datetime, timedelta, timezone
from math import ceil
from app.routes.billing import router as billing_router
from app.services.deduplicate import deduplicate_answers
import jwt
import resend
import io
import os
import pandas as pd
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your_super_secret_signing_key_change_this_in_production")
JWT_ALGORITHM  = "HS256"

resend.api_key = os.getenv("RESEND_API_KEY")
FRONTEND_URL   = os.getenv("FRONTEND_URL", "http://localhost:3000")


# ── Request / Response models ──────────────────────────────────────────────────
class DocumentsRequest(BaseModel):
    business_ids: List[int]
    page:         int = 1
    page_size:    int = 10

class BusinessSettingsUpdate(BaseModel):
    business_id:      int = Field(..., description="The unique ID of the business being updated")
    query_allocation: int = Field(..., ge=0, description="The maximum number of allowed searches")

class AskRequest(BaseModel):
    question:    str
    get_k:       int = 3
    offset:      int = 0
    business_id: int

class CreateBusinessRequest(BaseModel):
    name:   str
    org_id: int

class BusinessResponse(BaseModel):
    id:   int
    name: str
    model_config = {"from_attributes": True}

class DocumentRequest(BaseModel):
    business_ids: List[int]
    page:         int = 1
    page_size:    int = 50

# If your Pydantic schema looks like this:
class DocumentResponseItem(BaseModel):
    id: int
    name: str
    type: str
    status: str
    description: Optional[str] = None  # 👈 Make sure this is Optional!

class DocumentListResponse(BaseModel):
    documents: List[DocumentResponseItem]

class OrgCreateSchema(BaseModel):
    name: str

class OrgResponseSchema(BaseModel):
    id:       int
    name:     str
    owner_id: int
    is_active: bool

    class Config:
        from_attributes = True

class WorkspaceQueryRequest(BaseModel):
    org_id:      int
    business_id: int
    status:      str = "pending"

class AcceptInviteRequest(BaseModel):
    token:    str
    password: str = Field(..., min_length=6)
    name:     str = "User"

class OrgInviteRequest(BaseModel):
    email:        EmailStr
    role:         str       = "member"
    business_ids: List[int] = []

class MultiOrgBusinessesRequest(BaseModel):
    org_ids: List[int] = Field(..., description="List of target organization IDs to filter businesses by")


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
app.include_router(billing_router)


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
        "document_count":     count,
        "latest_document_id": latest_doc.id if latest_doc else None,
    }

def get_user_org_ids(db: Session, user_id: int) -> List[int]:
    """Reusable helper — returns all org IDs a user belongs to."""
    return [
        m.org_id for m in
        db.query(OrgMember).filter(OrgMember.user_id == user_id).all()
    ]


# ── Routes ─────────────────────────────────────────────────────────────────────
@app.get("/")
def read_root():
    return {"Hello": "World"}


# ── Auth: verify invite token ──────────────────────────────────────────────────
@app.get("/auth/verify-invite")
def verify_invite_token(token: str, db: Session = Depends(get_db)):
    try:
        payload    = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        email      = payload["email"]
        user_exists = db.query(User).filter(User.email == email).first() is not None
        return {
            "valid":       True,
            "email":       email,
            "org_id":      payload["org_id"],
            "user_exists": user_exists,
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="This invitation link has expired.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=400, detail="Invalid invitation token.")


# ── Auth: accept invite ────────────────────────────────────────────────────────
@app.post("/auth/accept-invite")
def accept_workspace_invitation(body: AcceptInviteRequest, db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(body.token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        raise HTTPException(status_code=400, detail="Invalid or expired invitation token.")

    email        = payload["email"]
    org_id       = payload["org_id"]
    role         = payload["role"]
    business_ids = payload["business_ids"]

    # Create or fetch user
    target_user = db.query(User).filter(User.email == email).first()
    if not target_user:
        from app.auth import hash_password
        target_user = User(
            email=email,
            name=body.name,
            hashed_password=hash_password(body.password),
            plan="free",
        )
        db.add(target_user)
        db.flush()

    # Add org membership
    existing_member = db.query(OrgMember).filter(
        OrgMember.org_id  == org_id,
        OrgMember.user_id == target_user.id,
    ).first()
    if not existing_member:
        db.add(OrgMember(org_id=org_id, user_id=target_user.id, role=role))

    # Grant business access
    for biz_id in business_ids:
        already = db.execute(
            user_business.select().where(
                user_business.c.user_id    == target_user.id,
                user_business.c.business_id == biz_id,
            )
        ).first()
        if not already:
            db.execute(user_business.insert().values(user_id=target_user.id, business_id=biz_id))

    # Mark invitation as accepted
    invitation = db.query(Invitation).filter(Invitation.token == body.token).first()
    if invitation:
        invitation.status = "accepted"

    db.commit()
    return {"status": "success", "message": "Invitation accepted. You can now sign in."}


# ── Auth: current user profile ─────────────────────────────────────────────────
@app.get("/auth/me")
async def get_current_user_profile(current_auth = Depends(get_current_user)):
    user, _     = current_auth
    user_plan   = user.plan.lower() if hasattr(user, "plan") and user.plan else "free"
    tier_config = PLAN_CONFIG.get(user_plan, PLAN_CONFIG["free"])
    return {
        "id":                user.id,
        "email":             user.email,
        "name":              getattr(user, "name", "User"),
        "plan":              user_plan,
        "max_businesses":    tier_config.get("max_businesses", 1),
        "max_organizations": tier_config.get("max_organizations", 1),
        "max_queries":       tier_config.get("monthly_searches", 50),
    }


# ── Auth: usage metrics ────────────────────────────────────────────────────────
@app.get("/auth/usage-metrics")
async def get_comprehensive_usage_metrics(
    org_id:       int,
    current_auth          = Depends(get_current_user),
    db:           Session = Depends(get_db),
):
    user, _ = current_auth
    org     = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")

    is_owner      = org.owner_id == user.id
    billing_owner = user if is_owner else db.query(User).filter(User.id == org.owner_id).first()

    start_of_period = (
        billing_owner.stripe_current_period_start
        if (billing_owner and hasattr(billing_owner, "stripe_current_period_start") and billing_owner.stripe_current_period_start)
        else datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    )

    total_combined_usage = db.query(func.count(QueryLog.id)).filter(
        QueryLog.org_id    == org_id,
        QueryLog.created_at >= start_of_period,
    ).scalar() or 0

    personal_user_usage = db.query(func.count(QueryLog.id)).filter(
        QueryLog.org_id    == org_id,
        QueryLog.user_id   == user.id,
        QueryLog.created_at >= start_of_period,
    ).scalar() or 0

    businesses         = db.query(Business).filter(Business.org_id == org_id).all()
    business_breakdown = []
    for biz in businesses:
        biz_count = db.query(func.count(QueryLog.id)).filter(
            QueryLog.business_id == biz.id,
            QueryLog.created_at  >= start_of_period,
        ).scalar() or 0
        business_breakdown.append({
            "id":         biz.id,
            "name":       biz.name,
            "allocation": biz.query_allocation,
            "usage":      biz_count,
        })

    owner_plan = billing_owner.plan.lower() if billing_owner and billing_owner.plan else "free"
    return {
        "is_owner":             is_owner,
        "max_queries_allowed":  PLAN_CONFIG.get(owner_plan, PLAN_CONFIG["free"]).get("monthly_searches", 50),
        "total_combined_usage": total_combined_usage,
        "personal_user_usage":  personal_user_usage,
        "businesses":           business_breakdown,
    }


# ── Upload documents ───────────────────────────────────────────────────────────
# app/routers/documents.py (or your route file)

@app.post("/upload-multiple")
async def upload_documents(
    business_id:     int              = Form(...),
    file_contexts:   Optional[str]    = Form(None),  # JSON string from frontend
    current_context: User             = Depends(get_current_user),
    files:           List[UploadFile] = File(...),
    db:              Session          = Depends(get_db),
):
    user, _      = current_context
    user_org_ids = get_user_org_ids(db, user.id)

    business = (
        db.query(Business)
        .filter(Business.id == business_id, Business.org_id.in_(user_org_ids))
        .first()
    )
    if not business:
        raise HTTPException(status_code=403, detail="Business not found or access denied.")

    # Parse optional JSON map: {"filename.xlsx": "context note"}
    contexts_map = {}
    if file_contexts:
        try:
            contexts_map = json.loads(file_contexts)
        except Exception as e:
            print(f"Failed to parse file_contexts payload: {e}")

    uploaded = []
    
    for file in files:
        safe_filename = Path(file.filename).name
        specific_context = contexts_map.get(safe_filename, "").strip() or None

        # 1. Read file bytes ONCE and store in memory
        contents = await file.read()

        temp_path = f"/tmp/{uuid.uuid4()}_{safe_filename}"
        with open(temp_path, "wb") as f:
            f.write(contents)

        # 2. Create parent Document record in DB
        doc = Document(
            business_id=business.id, 
            filename=safe_filename, 
            content="", 
            description=specific_context,
            status="ready"
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        try:
            # 3. Run through your updated modular pipeline dispatcher
            pipeline_result = ingest_document(
                file_bytes=contents,
                filename=safe_filename,
                # analyze_region_func=... # Pass your region analyzer function here if needed for xlsx
            )

            # Handle return structure depending on file type
            if isinstance(pipeline_result, tuple):
                final_chunks, workbook_graph = pipeline_result
            else:
                final_chunks = pipeline_result

            # 4. Map pipeline RAGChunks to your database Chunk model
            db_chunks = []
            for i, chunk in enumerate(final_chunks):
                meta = chunk.metadata or {}
                
                if specific_context and "file_context" not in meta:
                    meta["file_context"] = specific_context

                db_chunks.append(
                    Chunk(
                        business_id=business.id,
                        document_id=doc.id,
                        chunk_index=meta.get("chunk_index", i),
                        text=chunk.content,
                        parent_text=meta.get("parent_text") or meta.get("parent_id"),
                        chunk_type=meta.get("chunk_type", "child"),
                        embedding=chunk.embedding,
                    )
                )

            if db_chunks:
                db.add_all(db_chunks)
                db.commit()

            uploaded.append({
                "filename": safe_filename, 
                "document_id": doc.id, 
                "chunks": len(db_chunks)
            })

        except Exception as e:
            db.rollback()
            print(f"Error ingesting file {safe_filename}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to ingest {safe_filename}: {str(e)}")
            
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    return {"uploaded": uploaded}

# ── Get documents ──────────────────────────────────────────────────────────────
@app.post("/documents", response_model=DocumentListResponse, status_code=status.HTTP_200_OK)
async def get_documents(
    payload:      DocumentRequest,
    db:           Session = Depends(get_db),
    current_auth          = Depends(get_current_user),
):
    user, _      = current_auth
    user_org_ids = get_user_org_ids(db, user.id)

    # 1. Authorize requested business IDs
    allowed_business_ids = {
        b.id for b in db.query(Business.id).filter(Business.org_id.in_(user_org_ids)).all()
    }
    
    if not payload.business_ids:
        return DocumentListResponse(documents=[], total=0)

    for requested_id in payload.business_ids:
        if requested_id not in allowed_business_ids:
            raise HTTPException(status_code=403, detail=f"Not authorized for business ID: {requested_id}")

    # 2. Compute safe pagination bounds
    page = max(payload.page, 1)
    page_size = max(payload.page_size, 1)
    offset = (page - 1) * page_size

    # 3. Query documents
    query = db.query(Document).filter(Document.business_id.in_(payload.business_ids))
    total_count = query.count()  # Optional: include if response schema requires total

    query_results = (
        query
        .order_by(Document.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    # 4. Construct response items with description attached
    documents = [
        DocumentResponseItem(
            id=doc.id,
            name=doc.filename,
            type=doc.filename.rsplit(".", 1)[-1].upper() if "." in doc.filename else "FILE",
            status=doc.status,
            description=doc.description,  # Pass new field to Pydantic
        )
        for doc in query_results
    ]

    return DocumentListResponse(documents=documents, total=total_count)


# ── Get businesses (multi-org) ─────────────────────────────────────────────────
@app.post("/me/businesses")
def get_my_businesses(
    payload:      MultiOrgBusinessesRequest,
    db:           Session = Depends(get_db),
    current_user          = Depends(get_current_user),
):
    user, _           = current_user
    requested_org_ids = payload.org_ids

    if not requested_org_ids:
        return {"businesses": []}

    memberships       = db.query(OrgMember).filter(
        OrgMember.org_id.in_(requested_org_ids),
        OrgMember.user_id == user.id,
    ).all()
    authorized_org_ids = {m.org_id for m in memberships}
    org_role_map       = {m.org_id: m.role for m in memberships}

    admin_org_ids  = []
    member_org_ids = []

    for org_id in requested_org_ids:
        if org_id not in authorized_org_ids:
            raise HTTPException(status_code=403, detail=f"Not a member of org ID {org_id}")
        org      = db.query(Organization).filter(Organization.id == org_id).first()
        is_owner = org and org.owner_id == user.id
        is_admin = org_role_map.get(org_id) == "admin"
        if is_owner or is_admin:
            admin_org_ids.append(org_id)
        else:
            member_org_ids.append(org_id)

    combined = []
    if admin_org_ids:
        combined.extend(db.query(Business).filter(Business.org_id.in_(admin_org_ids)).all())
    if member_org_ids:
        combined.extend(
            db.query(Business)
            .join(user_business, Business.id == user_business.c.business_id)
            .filter(Business.org_id.in_(member_org_ids), user_business.c.user_id == user.id)
            .all()
        )

    return {"businesses": [{"id": b.id, "name": b.name, "org_id": b.org_id} for b in combined]}


# ── Organizations: create ──────────────────────────────────────────────────────
@app.post("/organizations", response_model=OrgResponseSchema, status_code=status.HTTP_201_CREATED)
async def create_organization(
    payload:      OrgCreateSchema,
    db:           Session = Depends(get_db),
    current_auth          = Depends(get_current_user),
):
    user, _   = current_auth
    user_plan = user.plan if hasattr(user, "plan") else "free"
    config    = PLAN_CONFIG.get(user_plan, PLAN_CONFIG["free"])
    max_orgs  = config.get("max_organizations", 1)

    owned_count = db.query(Organization).filter(Organization.owner_id == user.id).count()
    if owned_count >= max_orgs:
        raise HTTPException(
            status_code=400,
            detail=f"Your '{user_plan}' plan allows a maximum of {max_orgs} organizations.",
        )

    try:
        new_org = Organization(name=payload.name, owner_id=user.id, is_active=True)
        db.add(new_org)
        db.flush()
        db.add(OrgMember(org_id=new_org.id, user_id=user.id, role="admin"))
        db.commit()
        db.refresh(new_org)
        return new_org
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ── Organizations: list ────────────────────────────────────────────────────────
@app.get("/organizations", response_model=List[OrgResponseSchema], status_code=status.HTTP_200_OK)
async def get_user_organizations(
    db:           Session = Depends(get_db),
    current_auth          = Depends(get_current_user),
):
    user, _ = current_auth
    try:
        memberships = db.query(OrgMember).filter(OrgMember.user_id == user.id).all()
        return [
            {
                "id":       m.organization.id,
                "name":     m.organization.name,
                "owner_id": m.organization.owner_id,
                "is_active": m.organization.is_active,
            }
            for m in memberships if m.organization
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Organizations: invite user ─────────────────────────────────────────────────
@app.post("/organizations/{org_id}/invite", status_code=status.HTTP_201_CREATED)
async def invite_user_to_workspace(
    org_id:       int,
    body:         OrgInviteRequest,
    db:           Session = Depends(get_db),
    current_auth          = Depends(get_current_user),
):
    admin_user, _ = current_auth

    # 1. Fetch organization and verify admin permissions
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")

    admin_membership = db.query(OrgMember).filter(
        OrgMember.org_id == org_id, OrgMember.user_id == admin_user.id
    ).first()
    if org.owner_id != admin_user.id and (not admin_membership or admin_membership.role != "admin"):
        raise HTTPException(status_code=403, detail="Admin permissions required.")

    # 2. Schema check: Ensure at least one valid business ID is provided
    if not body.business_ids or len(body.business_ids) == 0:
        raise HTTPException(
            status_code=400, 
            detail="At least one valid location target (business_id) must be selected for this invitation."
        )

    # 3. Seat limit check
    billing_owner  = db.query(User).filter(User.id == org.owner_id).first()
    owner_plan     = billing_owner.plan.lower() if billing_owner and billing_owner.plan else "free"
    config         = PLAN_CONFIG.get(owner_plan, PLAN_CONFIG["free"])
    max_seats      = config.get("max_users", 2)
    active_seats   = db.query(OrgMember).filter(OrgMember.org_id == org_id).count()
    pending_seats  = db.query(Invitation).filter(
        Invitation.org_id == org_id, Invitation.status == "pending"
    ).count()
    if (active_seats + pending_seats) >= max_seats:
        raise HTTPException(
            status_code=400,
            detail=f"Seat limit reached ({max_seats} max). Upgrade to invite more members.",
        )

    # 4. Validate business IDs belong to this org layer safely
    valid_count = db.query(Business).filter(
        Business.id.in_(body.business_ids), Business.org_id == org_id
    ).count()
    if valid_count != len(body.business_ids):
        raise HTTPException(status_code=400, detail="One or more selected business IDs are invalid.")

    # 5. Generate a secure, short-lived JWT token (Expires in 7 days)
    token_expiry  = datetime.now(timezone.utc) + timedelta(days=7)
    invite_token  = jwt.encode(
        {"email": body.email, "org_id": org_id, "role": body.role,
         "business_ids": body.business_ids, "exp": token_expiry},
        JWT_SECRET_KEY, algorithm=JWT_ALGORITHM,
    )

    # 6. Save invitations to DB - Every entry now maps cleanly to its required business_id
    # We track the primary invite ID to cleanly hand it right back to the frontend engine
    primary_invite_id = None
    created_invites = []

    try:
        for biz_id in body.business_ids:
            # Check for an existing duplicate pending invite to same email + business to avoid spam
            existing = db.query(Invitation).filter(
                Invitation.org_id      == org_id,
                Invitation.business_id == biz_id,
                Invitation.email       == body.email,
                Invitation.status      == "pending",
            ).first()
            
            if not existing:
                inv = Invitation(
                    org_id      = org_id,
                    business_id = biz_id,  # 👈 Maps the non-nullable relation correctly
                    email       = body.email,
                    role        = body.role,
                    status      = "pending",
                    token       = invite_token,
                    created_at  = datetime.now(timezone.utc)
                )
                db.add(inv)
                created_invites.append(inv)
        
        db.commit()
        
        # Capture the database ID of the primary location invited to
        if created_invites:
            db.refresh(created_invites[0])
            primary_invite_id = created_invites[0].id
        else:
            # Fallback handling: If it was already pending, find it
            fallback = db.query(Invitation).filter(
                Invitation.org_id == org_id,
                Invitation.business_id == body.business_ids[0],
                Invitation.email == body.email
            ).first()
            primary_invite_id = fallback.id if fallback else 999
            
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database transaction error: {str(e)}")

    # 7. Send the transactional invite email via Resend
    invite_link = f"{FRONTEND_URL}/accept-invite?token={invite_token}"
    try:
        resend.Emails.send({
            "from":    "Team <onboarding@resend.dev>",
            "to":      [body.email],
            "subject": f"You've been invited to join {org.name}",
            "html":    f"""
                <div style="font-family:sans-serif;padding:20px;color:#333">
                    <h2>You're invited!</h2>
                    <p><strong>{admin_user.email}</strong> invited you to join their workspace: <strong>{org.name}</strong>.</p>
                    <div style="margin:24px 0">
                        <a href="{invite_link}" style="background:#000;color:#fff;padding:12px 24px;text-decoration:none;border-radius:6px;font-weight:bold;display:inline-block">
                            Accept Invitation
                        </a>
                    </div>
                    <p style="font-size:12px;color:#666">Or copy: {invite_link}</p>
                </div>
            """,
        })
    except Exception as e:
        # Rollback database changes if the transactional email delivery fails completely
        for inv in created_invites:
            db.delete(inv)
        db.commit()
        raise HTTPException(status_code=500, detail=f"Email delivery failed: {str(e)}")

    # 8. Returns the explicit object format expected by your React useState array updater
    return {
        "id": f"pending_{primary_invite_id}",
        "email": body.email,
        "role": body.role,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat()
    }


# ── Organizations: get members + pending invites for a business ────────────────
@app.get("/organizations/{org_id}/businesses/{business_id}/members")
def get_business_members(
    org_id:      int,
    business_id: int,
    db:          Session = Depends(get_db),
    current_auth          = Depends(get_current_user),
):
    user, _ = current_auth

    # 1. Auth Guard: Verify the requesting user belongs to this organization
    membership = db.query(OrgMember).filter(
        OrgMember.org_id == org_id, OrgMember.user_id == user.id
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this organization.")

    # 2. Verify the location profile belongs to this parent workspace container
    business = db.query(Business).filter(
        Business.id == business_id, Business.org_id == org_id
    ).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found.")

    org = db.query(Organization).filter(Organization.id == org_id).first()

    # ── Active members ─────────────────────────────────────────────────────────
    # Pull all workspace memberships for this organization
    org_memberships = db.query(OrgMember).filter(OrgMember.org_id == org_id).all()
    org_user_ids = [m.user_id for m in org_memberships]

    # Map user profiles securely by their unique IDs
    all_org_users = db.query(User).filter(User.id.in_(org_user_ids)).all()
    user_map = {u.id: u for u in all_org_users}

    # Gather explicit location bridge relations from the join table context
    assigned_relations = db.execute(
        user_business.select().where(user_business.c.business_id == business_id)
    ).fetchall()
    assigned_user_ids = {r.user_id for r in assigned_relations}

    active_members = []
    
    for m in org_memberships:
        u = user_map.get(m.user_id)
        if not u:
            continue
            
        is_owner = (int(org.owner_id) == int(u.id))
        is_assigned = u.id in assigned_user_ids

        # Include if they are the root creator, or explicitly mapped via bridge table rows
        if is_owner or is_assigned:
            active_members.append({
                "id":      str(m.id),  # Matches the OrgMember row ID format expected by page.tsx
                "email":   u.email,
                "role":    m.role,
                "status":  "active",
                "is_root": is_owner,
            })

    # ── Pending invitations for this business ──────────────────────────────────
    pending_invites = (
        db.query(Invitation)
        .filter(
            Invitation.org_id      == org_id,
            Invitation.business_id == business_id,
            Invitation.status      == "pending",
        )
        .order_by(Invitation.created_at.desc())
        .all()
    )
    
    pending_members = [
        {
            "id":         f"pending_{inv.id}",
            "email":      inv.email,
            "role":       inv.role,
            "status":     "pending",
            "created_at": inv.created_at.isoformat(),
            "is_root":    False,
        }
        for inv in pending_invites
    ]

    return {"members": active_members + pending_members}


# ── Organizations: revoke invitation ──────────────────────────────────────────
@app.delete("/organizations/{org_id}/invitations/{invitation_id}")
def revoke_invitation(
    org_id:        int,
    invitation_id: int,
    db:            Session = Depends(get_db),
    current_auth            = Depends(get_current_user),
):
    user, _ = current_auth

    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")

    membership = db.query(OrgMember).filter(
        OrgMember.org_id == org_id, OrgMember.user_id == user.id
    ).first()
    is_owner = org.owner_id == user.id
    is_admin = membership and membership.role == "admin"
    if not is_owner and not is_admin:
        raise HTTPException(status_code=403, detail="Admin permissions required to revoke invitations.")

    invitation = db.query(Invitation).filter(
        Invitation.id     == invitation_id,
        Invitation.org_id == org_id,
        Invitation.status == "pending",
    ).first()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found or already accepted.")

    email = invitation.email
    db.delete(invitation)
    db.commit()
    return {"message": f"Invitation to {email} revoked."}


# ── Organizations: list org-level members ─────────────────────────────────────
@app.get("/organizations/{org_id}/members")
def get_organization_members(
    org_id:      int,
    db:          Session = Depends(get_db),
    current_auth          = Depends(get_current_user),
):
    current_user, _ = current_auth

    membership = db.query(OrgMember).filter(
        OrgMember.org_id == org_id, OrgMember.user_id == current_user.id
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="Not authorized.")

    org     = db.query(Organization).filter(Organization.id == org_id).first()
    members = db.query(OrgMember).filter(OrgMember.org_id == org_id).all()

    formatted = []
    for m in members:
        u = db.query(User).filter(User.id == m.user_id).first()
        if u:
            formatted.append({
                "id":      str(m.id),
                "email":   u.email,
                "role":    m.role,
                "is_root": org.owner_id == m.user_id if org else False,
            })
    return {"members": formatted}


# ── Organizations: pending invitations (org-level) ────────────────────────────
@app.post("/organizations/invitations")
def get_pending_invitations(
    body:        WorkspaceQueryRequest,
    db:          Session = Depends(get_db),
    current_auth          = Depends(get_current_user),
):
    current_user, _ = current_auth

    membership = db.query(OrgMember).filter(
        OrgMember.org_id == body.org_id, OrgMember.user_id == current_user.id
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="Not authorized.")

    invites = db.query(Invitation).filter(
        Invitation.org_id == body.org_id, Invitation.status == body.status
    ).all()

    return {"invitations": [
        {"id": str(i.id), "email": i.email, "role": i.role, "created_at": i.created_at.isoformat()}
        for i in invites
    ]}


# ── Businesses: create ─────────────────────────────────────────────────────────
@app.post("/businesses", response_model=BusinessResponse)
def create_business_route(
    body:         CreateBusinessRequest,
    db:           Session = Depends(get_db),
    current_user          = Depends(get_current_user),
):
    user, _       = current_user
    business_name = body.name.strip()
    if not business_name:
        raise HTTPException(status_code=400, detail="Business name is required.")

    membership = db.query(OrgMember).filter(
        OrgMember.org_id == body.org_id, OrgMember.user_id == user.id
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="No permission to modify this organization.")

    org = db.query(Organization).filter(Organization.id == body.org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")
    if not org.is_active:
        raise HTTPException(status_code=402, detail="Organization is inactive.")

    business = Business(name=business_name, org_id=org.id)
    db.add(business)
    db.commit()
    db.refresh(business)
    return business


# ── Businesses: update settings ────────────────────────────────────────────────
@app.patch("/businesses/settings")
async def update_business_settings(
    settings_data: BusinessSettingsUpdate,
    current_auth           = Depends(get_current_user),
    db:            Session = Depends(get_db),
):
    user, _ = current_auth

    business = db.query(Business).filter(Business.id == settings_data.business_id).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found.")

    org = db.query(Organization).filter(Organization.id == business.org_id).first()
    if not org or org.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the org owner can change allocations.")

    plan_limit = PLAN_CONFIG.get(user.plan.lower(), PLAN_CONFIG["free"]).get("monthly_searches", 50)
    total_allocated = (
        db.query(func.sum(Business.query_allocation))
        .join(Organization, Business.org_id == Organization.id)
        .filter(Organization.owner_id == user.id)
        .scalar() or 0
    )
    projected = (total_allocated - business.query_allocation) + settings_data.query_allocation
    if projected > plan_limit:
        raise HTTPException(
            status_code=400,
            detail=f"Allocation would exceed plan limit of {plan_limit} (projected: {projected}).",
        )

    business.query_allocation = settings_data.query_allocation
    db.add(business)
    db.commit()
    db.refresh(business)
    return {"message": "Settings updated.", "business_id": business.id, "query_allocation": business.query_allocation}


# ── Ask ────────────────────────────────────────────────────────────────────────
ANSWER_PAGE_SIZE    = 10
PARENT_BATCH_SIZE    = 3
RETRIEVAL_POOL_SIZE = 50


@app.post("/ask")
def ask_question(
    body:            AskRequest,
    db:              Session = Depends(get_db),
    current_context          = Depends(get_current_user),
):
    user, _      = current_context
    user_org_ids = get_user_org_ids(db, user.id)

    business = (
        db.query(Business)
        .filter(Business.id == body.business_id, Business.org_id.in_(user_org_ids))
        .first()
    )
    if not business or not business.organization:
        raise HTTPException(status_code=403, detail="Access denied.")

    org       = business.organization
    user_plan = user.plan if hasattr(user, "plan") else "free"
    config    = PLAN_CONFIG.get(user_plan, PLAN_CONFIG["free"])

    # 1. Check search limit and calculate remaining calls for the plan
    allowed, current, limit = check_search_limit(org.id, user_plan)
    if not allowed:
        raise HTTPException(status_code=402, detail={
            "message": f"Monthly limit of {limit} searches reached.",
            "current": current, "limit": limit, "upgrade_url": "/pricing",
        })

    remaining_plan_calls = max(0, limit - current)

    answer_offset = body.offset or 0

    current_doc_state = get_business_doc_state(db, body.business_id)
    cached            = get_active_query(user.id)
    cache_is_valid    = (
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
        print("[Cache] MISS")
        if config["use_multiquery"]:
            retrieval         = retrieve_chunks_multi(db=db, business_id=body.business_id, query=body.question, get_k=RETRIEVAL_POOL_SIZE, offset=0)
            retrieval_results = retrieval["allResults"]
        elif config["use_hyde"]:
            retrieval         = retrieve_chunks(db=db, business_id=body.business_id, query=body.question, get_k=RETRIEVAL_POOL_SIZE, offset=0, use_hyde=True)
            retrieval_results = retrieval["results"]
        else:
            retrieval         = retrieve_chunks(db=db, business_id=body.business_id, query=body.question, get_k=RETRIEVAL_POOL_SIZE, offset=0, use_hyde=False)
            retrieval_results = retrieval["results"]

        all_answers       = []
        next_chunk_offset = 0
        
        # Count initial search execution
        increment_search_count(org.id)
        remaining_plan_calls -= 1

    target    = answer_offset + ANSWER_PAGE_SIZE
    llm_calls = 0

    # 2. Process chunks without a hardcoded MAX_LLM_CALLS limit
    while len(all_answers) < target and next_chunk_offset is not None and llm_calls < remaining_plan_calls:
        chunks = retrieval_results[next_chunk_offset: next_chunk_offset + PARENT_BATCH_SIZE]
        if not chunks:
            next_chunk_offset = None
            break

        new_answers = generate_answer(
            body.question,
            chunks
        ).get("answers", [])

        all_answers.extend(new_answers)

        all_answers = deduplicate_answers(all_answers)

        next_chunk_offset += PARENT_BATCH_SIZE
        llm_calls         += 1

        if next_chunk_offset >= len(retrieval_results):
            next_chunk_offset = None

    set_active_query(
        user_id=user.id, question=body.question, business_id=body.business_id,
        doc_state=current_doc_state, answers=all_answers,
        retrieval_results=retrieval_results, next_chunk_offset=next_chunk_offset,
    )

    page_answers = all_answers[answer_offset: answer_offset + ANSWER_PAGE_SIZE]
    has_more     = answer_offset + ANSWER_PAGE_SIZE < len(all_answers) or next_chunk_offset is not None
    next_offset  = answer_offset + ANSWER_PAGE_SIZE if has_more else None

    if answer_offset == 0:
        db.add(QueryLog(
            org_id=org.id, business_id=body.business_id, user_id=user.id,
            query_text=body.question, answer={"answers": page_answers},
            retrieval_plan="multiquery" if config["use_multiquery"] else "hyde" if config["use_hyde"] else "basic",
        ))
        db.commit()

    if not page_answers:
        return {"answer": {"answers": []}, "sources": [], "chunks_used": 0, "hasMore": False, "nextOffset": None}

    return {
        "answer":      {"answers": page_answers},
        "sources":     list({s["filename"] for item in page_answers for s in item.get("sources", [])}),
        "chunks_used": len(page_answers),
        "hasMore":     has_more,
        "nextOffset":  next_offset,
        "usage":       {"searches_limit": config["monthly_searches"]},
    }


# ── Recent queries ─────────────────────────────────────────────────────────────
@app.get("/queries/recent")
def get_recent_queries(
    business_id: int     = Query(...),
    page:        int     = Query(1, ge=1),
    page_size:   int     = Query(10, ge=1, le=50),
    db:          Session = Depends(get_db),
    current_user          = Depends(get_current_user),
):
    user, _      = current_user
    user_org_ids = get_user_org_ids(db, user.id)

    business = (
        db.query(Business)
        .filter(Business.id == business_id, Business.org_id.in_(user_org_ids))
        .first()
    )
    if not business:
        raise HTTPException(status_code=403, detail="Access denied.")

    query   = db.query(QueryLog).filter(QueryLog.business_id == business_id).order_by(QueryLog.id.desc())
    total   = query.count()
    queries = query.offset((page - 1) * page_size).limit(page_size).all()

    return {
        "page": page, "page_size": page_size, "total": total,
        "has_more": page * page_size < total,
        "queries": [{"id": q.id, "question": q.query_text, "answer": q.answer} for q in queries],
    }


# ── Delete document ────────────────────────────────────────────────────────────
@app.delete("/documents/{document_id}")
def delete_document(
    document_id:  int,
    business_id:  int     = Query(...),
    db:           Session = Depends(get_db),
    current_user          = Depends(get_current_user),
):
    user, _      = current_user
    user_org_ids = get_user_org_ids(db, user.id)

    business = (
        db.query(Business)
        .filter(Business.id == business_id, Business.org_id.in_(user_org_ids))
        .first()
    )
    if not business:
        raise HTTPException(status_code=403, detail="Access denied.")

    doc = db.query(Document).filter(Document.id == document_id, Document.business_id == business_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    from app.models import Chunk
    db.query(Chunk).filter(Chunk.document_id == document_id).delete()
    db.delete(doc)
    db.commit()
    clear_active_query(user.id)
    return {"message": "Document deleted successfully"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)