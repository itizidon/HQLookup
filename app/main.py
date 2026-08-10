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
from app.models import Business, User, Document, QueryLog, Organization, OrgMember, Invitation, user_business
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
from datetime import datetime, timedelta, timezone
from math import ceil
from app.routes.billing import router as billing_router

import jwt
import resend

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
@app.post("/upload-multiple")
async def upload_documents(
    business_id:     int              = Form(...),
    file_contexts:   Optional[str]    = Form(None),
    current_context: User             = Depends(get_current_user),
    files:           List[UploadFile] = File(...),
    db:              Session          = Depends(get_db),
):
    import pandas as pd

    user, _      = current_context
    user_org_ids = get_user_org_ids(db, user.id)

    business = (
        db.query(Business)
        .filter(Business.id == business_id, Business.org_id.in_(user_org_ids))
        .first()
    )
    if not business:
        raise HTTPException(status_code=403, detail="Business not found or access denied.")

    # ── Plan limits ────────────────────────────────────────────────────────────
    user_plan = user.plan if hasattr(user, "plan") else "free"
    config    = PLAN_CONFIG.get(user_plan, PLAN_CONFIG["free"])
    max_rows  = config["max_rows"]
    max_mb    = config["max_file_mb"]

    # Parse optional JSON map: {"filename.xlsx": "context note"}
    contexts_map = {}
    if file_contexts:
        try:
            contexts_map = json.loads(file_contexts)
        except Exception as e:
            print(f"Failed to parse file_contexts payload: {e}")

    uploaded = []
    for file in files:
        safe_filename    = Path(file.filename).name
        specific_context = contexts_map.get(safe_filename, "").strip() or None
        ext              = Path(safe_filename).suffix.lower()
        temp_path        = f"/tmp/{uuid.uuid4()}_{safe_filename}"

        # Save to disk
        contents = await file.read()
        with open(temp_path, "wb") as f:
            f.write(contents)

        try:
            # ── File size check ────────────────────────────────────────────────
            file_size_mb = os.path.getsize(temp_path) / (1024 * 1024)
            if file_size_mb > max_mb:
                raise HTTPException(status_code=400, detail={
                    "message":     f"{safe_filename} exceeds the {max_mb}MB limit for your {config['display_name']} plan.",
                    "size_mb":     round(file_size_mb, 1),
                    "limit_mb":    max_mb,
                    "upgrade_url": "/pricing",
                })

            # ── Row count check (spreadsheets only) ───────────────────────────
            if ext in [".csv", ".xlsx", ".xls"]:
                try:
                    if ext == ".csv":
                        with open(temp_path) as f:
                            row_count = sum(1 for _ in f) - 1
                    else:
                        xl        = pd.ExcelFile(temp_path)
                        row_count = sum(
                            len(pd.read_excel(temp_path, sheet_name=s, header=None))
                            for s in xl.sheet_names
                        )

                    if row_count > max_rows:
                        raise HTTPException(status_code=400, detail={
                            "message":     f"{safe_filename} has {row_count} rows which exceeds your {config['display_name']} plan limit of {max_rows}.",
                            "rows":        row_count,
                            "limit":       max_rows,
                            "upgrade_url": "/pricing",
                        })
                except HTTPException:
                    raise
                except Exception as e:
                    print(f"[Upload] Row count check failed for {safe_filename}: {e}")

            # ── Create document record ─────────────────────────────────────────
            doc = Document(
                business_id=business.id,
                filename=safe_filename,
                content="",
                description=specific_context,
                status="ready",
            )
            db.add(doc)
            db.commit()
            db.refresh(doc)

            # ── Ingest ─────────────────────────────────────────────────────────
            chunks_count = ingest_document(
                db=db,
                business_id=business.id,
                document_id=doc.id,
                file_path=temp_path,
                mime_type=file.content_type,
                filename=safe_filename,
                file_context=specific_context,
            )
            uploaded.append({
                "filename":    safe_filename,
                "document_id": doc.id,
                "chunks":      chunks_count,
            })

        except HTTPException:
            raise
        except Exception as e:
            print(f"[Upload] Failed for {safe_filename}: {e}")
            uploaded.append({
                "filename": safe_filename,
                "error":    str(e),
            })
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    clear_active_query(user.id)
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

ANSWER_PAGE_SIZE = 10
CHUNK_BATCH_SIZE = 5

INITIAL_RETRIEVAL_SIZE = 50
RETRIEVAL_EXPAND_SIZE = 50
MAX_RETRIEVAL_SIZE = 500

# Retry only tabular chunks for which the LLM returned NO decision.
# Explicit matches=False chunks are considered complete and are not retried.
MISSING_DECISION_RETRIES = 2


@app.post("/ask")
def ask_question(
    body: AskRequest,
    db: Session = Depends(get_db),
    current_context=Depends(get_current_user),
):
    user, _ = current_context

    user_org_ids = get_user_org_ids(
        db,
        user.id,
    )

    # ------------------------------------------------------------------
    # 1. Validate business / organization access
    # ------------------------------------------------------------------

    business = (
        db.query(Business)
        .filter(
            Business.id == body.business_id,
            Business.org_id.in_(user_org_ids),
        )
        .first()
    )

    if not business or not business.organization:
        raise HTTPException(
            status_code=403,
            detail="Access denied.",
        )

    org = business.organization

    user_plan = (
        user.plan
        if hasattr(user, "plan")
        else "free"
    )

    config = PLAN_CONFIG.get(
        user_plan,
        PLAN_CONFIG["free"],
    )

    # ------------------------------------------------------------------
    # 2. Check search limits
    # ------------------------------------------------------------------

    allowed, current, limit = check_search_limit(
        org.id,
        user_plan,
    )

    if not allowed:
        raise HTTPException(
            status_code=402,
            detail={
                "message": f"Monthly limit of {limit} searches reached.",
                "current": current,
                "limit": limit,
                "upgrade_url": "/pricing",
            },
        )

    remaining_plan_calls = max(
        0,
        limit - current,
    )

    # ------------------------------------------------------------------
    # 3. Requested answer page
    # ------------------------------------------------------------------

    answer_offset = body.offset or 0

    normalized_question = normalize_query(
        body.question
    )

    current_doc_state = get_business_doc_state(
        db,
        body.business_id,
    )

    # ------------------------------------------------------------------
    # 4. Load cached retrieval session
    # ------------------------------------------------------------------

    cached = get_active_query(
        user.id
    )

    cache_is_valid = (
        cached
        and cached.get("question") == normalized_question
        and cached.get("business_id") == body.business_id
        and cached.get("doc_state") == current_doc_state
    )

    if cache_is_valid:
        print("[Cache] HIT")

        retrieval_results = cached.get(
            "retrieval_results",
            [],
        )

        all_answers = cached.get(
            "answers",
            [],
        )

        retrieval_cursor = cached.get(
            "retrieval_cursor",
            0,
        )

        retrieval_limit = cached.get(
            "retrieval_limit",
            INITIAL_RETRIEVAL_SIZE,
        )

        retrieval_vectors = cached.get(
            "retrieval_vectors",
            None,
        )

        retrieval_fully_exhausted = cached.get(
            "retrieval_fully_exhausted",
            False,
        )

    else:
        print("[Cache] MISS")

        retrieval_limit = INITIAL_RETRIEVAL_SIZE
        retrieval_vectors = None
        retrieval_fully_exhausted = False

        # --------------------------------------------------------------
        # Initial retrieval
        # --------------------------------------------------------------

        if config["use_multiquery"]:
            retrieval = retrieve_chunks_multi(
                db=db,
                business_id=body.business_id,
                query=body.question,
                get_k=retrieval_limit,
                offset=0,
            )

            # Use only the requested retrieval window here.
            # `allResults` contains the entire post-RRF candidate pool and
            # would bypass the 50 -> 100 -> ... expansion flow.
            retrieval_results = retrieval.get(
                "results",
                [],
            )

            retrieval_vectors = retrieval.get(
                "vectors",
                None,
            )

        elif config["use_hyde"]:
            retrieval = retrieve_chunks(
                db=db,
                business_id=body.business_id,
                query=body.question,
                get_k=retrieval_limit,
                offset=0,
                use_hyde=True,
            )

            retrieval_results = retrieval.get(
                "results",
                [],
            )

        else:
            retrieval = retrieve_chunks(
                db=db,
                business_id=body.business_id,
                query=body.question,
                get_k=retrieval_limit,
                offset=0,
                use_hyde=False,
            )

            retrieval_results = retrieval.get(
                "results",
                [],
            )

        all_answers = []
        retrieval_cursor = 0

        retrieval_fully_exhausted = (
            len(retrieval_results) == 0
        )

        print(
            f"[Retrieval] Initial candidate pool: "
            f"{len(retrieval_results)} chunks"
        )

        increment_search_count(
            org.id
        )

        remaining_plan_calls -= 1

    # ------------------------------------------------------------------
    # Helper:
    # Always make user-facing answers frontend-safe strings.
    # ------------------------------------------------------------------

    def normalize_answer_text(raw_answer):
        if raw_answer is None:
            return None

        if isinstance(raw_answer, str):
            normalized = raw_answer.strip()
            return normalized or None

        if isinstance(raw_answer, dict):
            normalized = ", ".join(
                f"{key}: {value}"
                for key, value in raw_answer.items()
                if value is not None
            )

            return normalized or None

        if isinstance(raw_answer, list):
            normalized = ", ".join(
                str(value)
                for value in raw_answer
                if value is not None
            )

            return normalized or None

        normalized = str(
            raw_answer
        ).strip()

        return normalized or None

    # ------------------------------------------------------------------
    # 5. Generate enough answers for requested page
    #
    # retrieval_cursor:
    #     how many retrieval candidates have been fully processed
    #
    # answer_offset:
    #     which generated answer page the frontend requested
    # ------------------------------------------------------------------

    llm_calls = 0

    target_answer_count = (
        answer_offset
        + ANSWER_PAGE_SIZE
    )

    while (
        len(all_answers) < target_answer_count
        and llm_calls < remaining_plan_calls
    ):

        # ==============================================================
        # CURRENT RETRIEVAL POOL HAS BEEN PROCESSED
        # ==============================================================

        if retrieval_cursor >= len(retrieval_results):

            if retrieval_fully_exhausted:
                print(
                    "[Retrieval Expansion] "
                    "No more candidates available."
                )
                break

            if retrieval_limit >= MAX_RETRIEVAL_SIZE:
                print(
                    "[Retrieval Expansion] "
                    f"Reached maximum retrieval size "
                    f"of {MAX_RETRIEVAL_SIZE}."
                )

                retrieval_fully_exhausted = True
                break

            new_retrieval_limit = min(
                retrieval_limit + RETRIEVAL_EXPAND_SIZE,
                MAX_RETRIEVAL_SIZE,
            )

            print(
                "[Retrieval Expansion] "
                f"Expanding search "
                f"{retrieval_limit} -> {new_retrieval_limit}"
            )

            # ----------------------------------------------------------
            # Retrieve again using a larger candidate window
            # ----------------------------------------------------------

            if config["use_multiquery"]:
                expanded = retrieve_chunks_multi(
                    db=db,
                    business_id=body.business_id,
                    query=body.question,
                    get_k=new_retrieval_limit,
                    offset=0,
                    # Reuse the exact Multi-Query/HyDE search vectors
                    # created for the original request. This prevents
                    # Load More from regenerating query variants/HyDE.
                    vectors=retrieval_vectors,
                )

                # `results` is the top `new_retrieval_limit` window.
                # Existing chunk IDs are removed below, leaving only the
                # newly exposed candidates from this expansion.
                expanded_results = expanded.get(
                    "results",
                    [],
                )

            elif config["use_hyde"]:
                expanded = retrieve_chunks(
                    db=db,
                    business_id=body.business_id,
                    query=body.question,
                    get_k=new_retrieval_limit,
                    offset=0,
                    use_hyde=True,
                )

                expanded_results = expanded.get(
                    "results",
                    [],
                )

            else:
                expanded = retrieve_chunks(
                    db=db,
                    business_id=body.business_id,
                    query=body.question,
                    get_k=new_retrieval_limit,
                    offset=0,
                    use_hyde=False,
                )

                expanded_results = expanded.get(
                    "results",
                    [],
                )

            existing_ids = {
                result["id"]
                for result in retrieval_results
                if result.get("id") is not None
            }

            new_results = [
                result
                for result in expanded_results
                if (
                    result.get("id") is not None
                    and result["id"] not in existing_ids
                )
            ]

            print(
                "[Retrieval Expansion] "
                f"Expanded retrieval returned "
                f"{len(expanded_results)} candidates; "
                f"{len(new_results)} are new."
            )

            retrieval_limit = new_retrieval_limit

            if not new_results:
                retrieval_fully_exhausted = True

                print(
                    "[Retrieval Expansion] "
                    "No new chunks found."
                )

                break

            retrieval_results.extend(
                new_results
            )

            print(
                "[Retrieval Expansion] "
                f"Candidate pool now contains "
                f"{len(retrieval_results)} chunks."
            )

            continue

        # ==============================================================
        # PROCESS NEXT BATCH
        # ==============================================================

        batch_end = min(
            retrieval_cursor + CHUNK_BATCH_SIZE,
            len(retrieval_results),
        )

        chunks = retrieval_results[
            retrieval_cursor:batch_end
        ]

        if not chunks:
            break

        print(
            f"[LLM] Processing candidates "
            f"{retrieval_cursor}:{batch_end} "
            f"of {len(retrieval_results)}"
        )

        print(
            "\n[LLM BATCH INPUT]"
        )

        for chunk in chunks:
            print(
                f"chunk_id={chunk.get('id')} | "
                f"chunk_index={chunk.get('chunk_index')} | "
                f"content_type={chunk.get('content_type')} | "
                f"chunk_type={chunk.get('chunk_type')} | "
                f"{chunk.get('text', '')}"
            )

        # --------------------------------------------------------------
        # Main LLM call
        # --------------------------------------------------------------

        result = generate_answer(
            body.question,
            chunks,
        )

        llm_calls += 1

        records = result.get(
            "records",
            [],
        )

        text_answers = result.get(
            "answers",
            [],
        )

        if not isinstance(records, list):
            records = []

        if not isinstance(text_answers, list):
            text_answers = []

        # --------------------------------------------------------------
        # ONLY spreadsheet/tabular rows require a decision per chunk.
        #
        # Metadata / PDF / TXT / DOCX do NOT.
        # --------------------------------------------------------------

        tabular_chunks = [
            chunk
            for chunk in chunks
            if (
                chunk.get("content_type") == "tabular"
                or chunk.get("chunk_type") == "tabular_record"
            )
        ]

        tabular_chunks_by_id = {
            int(chunk["id"]): chunk
            for chunk in tabular_chunks
            if chunk.get("id") is not None
        }

        input_tabular_ids = set(
            tabular_chunks_by_id.keys()
        )

        returned_tabular_ids = set()

        # --------------------------------------------------------------
        # IMPORTANT:
        #
        # Keep answers for this batch isolated.
        #
        # We do NOT commit them to all_answers until every tabular row
        # in this batch has an explicit decision.
        # --------------------------------------------------------------

        batch_answers = []

        # --------------------------------------------------------------
        # Helper:
        # Process one spreadsheet decision.
        # --------------------------------------------------------------

        def process_tabular_record(
            record,
            expected_ids,
            returned_ids,
            destination_answers,
        ):
            if not isinstance(record, dict):
                print(
                    "[INVALID DECISION] "
                    f"Expected object, received: {record}"
                )
                return

            chunk_id = record.get(
                "chunk_id"
            )

            if chunk_id is None:
                print(
                    "[INVALID DECISION] "
                    "LLM returned a tabular decision "
                    "without chunk_id"
                )
                return

            try:
                chunk_id = int(
                    chunk_id
                )

            except (TypeError, ValueError):
                print(
                    "[INVALID DECISION] "
                    f"Invalid chunk_id={chunk_id}"
                )
                return

            # ----------------------------------------------------------
            # Reject chunk IDs that were not actually sent.
            # ----------------------------------------------------------

            if chunk_id not in expected_ids:
                print(
                    "[INVALID DECISION] "
                    f"Unexpected chunk_id={chunk_id}"
                )
                return

            # ----------------------------------------------------------
            # Only one decision per spreadsheet row.
            # ----------------------------------------------------------

            if chunk_id in returned_ids:
                print(
                    "[DUPLICATE DECISION] "
                    f"chunk_id={chunk_id}"
                )
                return

            original_chunk = tabular_chunks_by_id.get(
                chunk_id
            )

            # ----------------------------------------------------------
            # EXPLICIT NO MATCH
            #
            # This is a VALID completed decision.
            #
            # It is marked accounted-for and NEVER retried.
            # ----------------------------------------------------------

            if not record.get(
                "matches",
                False,
            ):
                returned_ids.add(
                    chunk_id
                )

                print(
                    f"[NO MATCH] "
                    f"chunk_id={chunk_id} | "
                    f"{original_chunk.get('text', '')[:300] if original_chunk else ''}"
                )

                return

            # ----------------------------------------------------------
            # MATCH
            # ----------------------------------------------------------

            answer_text = normalize_answer_text(
                record.get("answer")
            )

            if not answer_text:
                print(
                    "[INVALID MATCH] "
                    f"chunk_id={chunk_id} "
                    "has matches=true but no usable answer"
                )

                # Do NOT add it to returned_ids.
                #
                # That makes this row eligible for retry.
                return

            returned_ids.add(
                chunk_id
            )

            print(
                f"[MATCH] "
                f"chunk_id={chunk_id} | "
                f"{answer_text}"
            )

            destination_answers.append({
                "answer": answer_text,
                "confidence": record.get(
                    "confidence",
                    0.0,
                ),
                "sources": record.get(
                    "sources",
                    [],
                ),
            })

        # ==============================================================
        # PROCESS INITIAL TABULAR DECISIONS
        # ==============================================================

        for record in records:
            process_tabular_record(
                record=record,
                expected_ids=input_tabular_ids,
                returned_ids=returned_tabular_ids,
                destination_answers=batch_answers,
            )

        # ==============================================================
        # PROCESS NORMAL TEXT / PDF / DOCX / METADATA ANSWERS
        # ==============================================================

        for text_answer in text_answers:

            if not isinstance(text_answer, dict):
                print(
                    "[INVALID TEXT ANSWER] "
                    f"Expected object, received: {text_answer}"
                )
                continue

            answer_text = normalize_answer_text(
                text_answer.get("answer")
            )

            if not answer_text:
                continue

            print(
                f"[TEXT MATCH] "
                f"{answer_text}"
            )

            batch_answers.append({
                "answer": answer_text,
                "confidence": text_answer.get(
                    "confidence",
                    0.0,
                ),
                "sources": text_answer.get(
                    "sources",
                    [],
                ),
            })

        # ==============================================================
        # DETECT MISSING SPREADSHEET DECISIONS
        # ==============================================================

        missing_tabular_ids = (
            input_tabular_ids
            - returned_tabular_ids
        )

        if missing_tabular_ids:
            print(
                "[MISSING DECISION] "
                f"Initial batch failed to account for "
                f"chunk IDs: {sorted(missing_tabular_ids)}"
            )

        # ==============================================================
        # RETRY ONLY MISSING SPREADSHEET DECISIONS
        #
        # IMPORTANT:
        #
        # matches=False rows were already added to returned_tabular_ids.
        #
        # Therefore NO MATCH rows DO NOT enter this retry loop.
        # ==============================================================

        retry_round = 0

        while (
            missing_tabular_ids
            and retry_round < MISSING_DECISION_RETRIES
            and llm_calls < remaining_plan_calls
        ):
            retry_round += 1

            print(
                "[MISSING DECISION RETRY] "
                f"Round {retry_round} | "
                f"remaining={sorted(missing_tabular_ids)}"
            )

            ids_to_retry = sorted(
                missing_tabular_ids
            )

            for missing_id in ids_to_retry:

                if llm_calls >= remaining_plan_calls:
                    break

                missing_chunk = tabular_chunks_by_id.get(
                    missing_id
                )

                if not missing_chunk:
                    print(
                        "[RETRY ERROR] "
                        f"Could not locate "
                        f"chunk_id={missing_id}"
                    )
                    continue

                print(
                    "[RETRY CHUNK] "
                    f"chunk_id={missing_id} | "
                    f"{missing_chunk.get('text', '')[:500]}"
                )

                # ------------------------------------------------------
                # Retry ONE missing spreadsheet row.
                # ------------------------------------------------------

                retry_result = generate_answer(
                    body.question,
                    [missing_chunk],
                )

                llm_calls += 1

                retry_records = retry_result.get(
                    "records",
                    [],
                )

                if not isinstance(
                    retry_records,
                    list,
                ):
                    retry_records = []

                for retry_record in retry_records:
                    process_tabular_record(
                        record=retry_record,
                        expected_ids={missing_id},
                        returned_ids=returned_tabular_ids,
                        destination_answers=batch_answers,
                    )

            # ----------------------------------------------------------
            # Recalculate after retry round.
            # ----------------------------------------------------------

            missing_tabular_ids = (
                input_tabular_ids
                - returned_tabular_ids
            )

        # ==============================================================
        # STILL MISSING AFTER RETRIES
        #
        # DO NOT ADVANCE THE CURSOR.
        # ==============================================================

        if missing_tabular_ids:
            print(
                "[UNRESOLVED MISSING DECISION] "
                f"Could not safely account for "
                f"chunk IDs: {sorted(missing_tabular_ids)}"
            )

            print(
                "[BATCH NOT COMMITTED] "
                "retrieval_cursor remains unchanged."
            )

            # ----------------------------------------------------------
            # Do NOT:
            #
            # all_answers.extend(batch_answers)
            #
            # Do NOT:
            #
            # retrieval_cursor = batch_end
            #
            # Otherwise we would silently lose the unresolved row.
            # ----------------------------------------------------------

            break

        # ==============================================================
        # EVERY TABULAR ROW IS ACCOUNTED FOR
        #
        # Safe to commit the batch.
        # ==============================================================

        all_answers.extend(
            batch_answers
        )

        retrieval_cursor = batch_end

    # ------------------------------------------------------------------
    # 6. Save stable retrieval session
    # ------------------------------------------------------------------

    set_active_query(
        user_id=user.id,
        question=body.question,
        business_id=body.business_id,
        doc_state=current_doc_state,
        answers=all_answers,
        retrieval_results=retrieval_results,
        retrieval_cursor=retrieval_cursor,
        retrieval_limit=retrieval_limit,
        retrieval_vectors=retrieval_vectors,
        retrieval_fully_exhausted=retrieval_fully_exhausted,
    )

    # ------------------------------------------------------------------
    # 7. Paginate generated answers
    # ------------------------------------------------------------------

    page_answers = all_answers[
        answer_offset:
        answer_offset + ANSWER_PAGE_SIZE
    ]

    print(
        "\n[PAGINATION DEBUG] "
        f"answer_offset={answer_offset} "
        f"total_all_answers={len(all_answers)} "
        f"retrieval_cursor={retrieval_cursor} "
        f"retrieval_results={len(retrieval_results)}"
    )

    for i, answer in enumerate(
        all_answers
    ):
        print(
            f"[ALL ANSWER {i}] "
            f"{answer.get('answer')}"
        )

    # ------------------------------------------------------------------
    # 8. Determine whether additional work/results remain
    # ------------------------------------------------------------------

    has_more_answers = (
        answer_offset
        + ANSWER_PAGE_SIZE
        < len(all_answers)
    )

    # Retrieved candidates that have not yet been successfully committed.
    has_more_candidates = (
        retrieval_cursor
        < len(retrieval_results)
    )

    # Current retrieval pool may still be expandable.
    can_expand_retrieval = (
        not retrieval_fully_exhausted
        and retrieval_limit < MAX_RETRIEVAL_SIZE
    )

    has_more = (
        has_more_answers
        or has_more_candidates
        or can_expand_retrieval
    )

    next_offset = (
        answer_offset + ANSWER_PAGE_SIZE
        if has_more
        else None
    )

    # ------------------------------------------------------------------
    # 9. Log initial query
    # ------------------------------------------------------------------

    if (
        answer_offset == 0
        and not cache_is_valid
    ):
        db.add(
            QueryLog(
                org_id=org.id,
                business_id=body.business_id,
                user_id=user.id,
                query_text=body.question,
                answer={
                    "answers": page_answers,
                },
                retrieval_plan=(
                    "multiquery"
                    if config["use_multiquery"]
                    else (
                        "hyde"
                        if config["use_hyde"]
                        else "basic"
                    )
                ),
            )
        )

        db.commit()

    # ------------------------------------------------------------------
    # 10. Empty answer page
    # ------------------------------------------------------------------

    if not page_answers:
        return {
            "answer": {
                "answers": [],
            },
            "sources": [],
            "chunks_used": 0,
            "hasMore": has_more,
            "nextOffset": next_offset,
            "usage": {
                "searches_limit": config["monthly_searches"],
            },
        }

    # ------------------------------------------------------------------
    # 11. Collect source filenames
    # ------------------------------------------------------------------

    sources = list({
        source["filename"]
        for item in page_answers
        for source in item.get(
            "sources",
            [],
        )
        if (
            isinstance(source, dict)
            and source.get("filename")
        )
    })

    # ------------------------------------------------------------------
    # 12. Return requested answer page
    # ------------------------------------------------------------------

    return {
        "answer": {
            "answers": page_answers,
        },
        "sources": sources,
        "chunks_used": len(page_answers),
        "hasMore": has_more,
        "nextOffset": next_offset,
        "usage": {
            "searches_limit": config["monthly_searches"],
        },
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