import uvicorn
import json
import hashlib
import html
import logging
import secrets
import tempfile
from fastapi import FastAPI, UploadFile, File, Depends, Query, HTTPException, Form, status
from typing import List, Optional, Literal
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pathlib import Path
from app.database import get_db
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from app.routes.auth import router as auth_router
from app.models import Business, User, Document, QueryLog, Organization, OrgMember, Invitation, user_business
from app.rag import (
    ingest_document,
    retrieve_chunks,
    retrieve_chunks_multi,
    check_search_limit,
    consume_search_quota,
    clear_active_query,
    get_active_query,
    set_active_query,
    normalize_query,
    PLAN_CONFIG,
    QuotaBackendUnavailable,
    redis_is_ready,
)
from app.llm import generate_answer
from pydantic import BaseModel, Field, EmailStr
from app.auth import get_current_user, hash_password, validate_password
from datetime import datetime, timedelta, timezone
from app.routes.billing import router as billing_router
import resend
from app.access import (
    INVITABLE_ROLES,
    get_billing_owner,
    require_business_access,
    require_org_access,
)
from app.database import engine
from app.logging_config import configure_logging
from app.settings import settings

configure_logging()
logger = logging.getLogger(__name__)

resend.api_key = (
    settings.resend_api_key.get_secret_value()
    if settings.resend_api_key
    else None
)


# ── Request / Response models ──────────────────────────────────────────────────
class BusinessSettingsUpdate(BaseModel):
    business_id:      int = Field(..., description="The unique ID of the business being updated")
    query_allocation: int = Field(..., ge=0, description="The maximum number of allowed searches")

class AskRequest(BaseModel):
    question:    str = Field(min_length=1, max_length=4000)
    get_k:       int = Field(default=3, ge=1, le=100)
    offset:      int = Field(default=0, ge=0)
    business_id: int

class CreateBusinessRequest(BaseModel):
    name:   str
    org_id: int

class BusinessResponse(BaseModel):
    id:   int
    name: str
    model_config = {"from_attributes": True}

class DocumentRequest(BaseModel):
    business_ids: List[int] = Field(max_length=100)
    page:         int = Field(default=1, ge=1)
    page_size:    int = Field(default=50, ge=1, le=100)

# If your Pydantic schema looks like this:
class DocumentResponseItem(BaseModel):
    id: int
    name: str
    type: str
    status: str
    description: Optional[str] = None  # 👈 Make sure this is Optional!

class DocumentListResponse(BaseModel):
    documents: List[DocumentResponseItem]
    total: int = 0

class OrgCreateSchema(BaseModel):
    name: str = Field(min_length=1, max_length=120)

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
    token:    str = Field(min_length=32, max_length=512)
    password: str | None = Field(default=None, max_length=72)
    name:     str | None = Field(default=None, max_length=120)

class OrgInviteRequest(BaseModel):
    email:        EmailStr
    role:         Literal["admin", "member"] = "member"
    business_ids: List[int] = Field(default_factory=list, min_length=1, max_length=100)

class MultiOrgBusinessesRequest(BaseModel):
    org_ids: List[int] = Field(..., max_length=100, description="List of target organization IDs to filter businesses by")


# ── App setup ──────────────────────────────────────────────────────────────────
app = FastAPI(
    title="HQLookup API",
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def csrf_origin_guard(request, call_next):
    """Reject cross-origin mutations that authenticate with the session cookie."""
    if (
        request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and request.url.path != "/billing/webhook"
        and request.cookies.get("token")
    ):
        origin = (request.headers.get("origin") or "").rstrip("/")
        if not origin or origin not in settings.cors_origins:
            return JSONResponse(status_code=403, content={"detail": "Untrusted request origin."})
    return await call_next(request)


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

INVITATION_TTL = timedelta(days=7)
ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".csv", ".xlsx", ".xls"}
MAX_UPLOAD_FILES = 10
UPLOAD_READ_SIZE = 1024 * 1024


def _invite_token_digest(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _pending_invite_query(db: Session, raw_token: str):
    cutoff = datetime.now(timezone.utc) - INVITATION_TTL
    digest = _invite_token_digest(raw_token)
    return db.query(Invitation).filter(
        Invitation.token.in_([digest, raw_token]),
        Invitation.status == "pending",
        Invitation.created_at >= cutoff,
    )


# ── Routes ─────────────────────────────────────────────────────────────────────
@app.get("/")
def read_root():
    return {"name": "HQLookup API", "status": "ok"}


@app.get("/health/live", include_in_schema=False)
def health_live():
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
def health_ready():
    failures = []
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        failures.append("database")
    if not redis_is_ready():
        failures.append("redis")
    if failures:
        raise HTTPException(status_code=503, detail={"status": "not_ready", "services": failures})
    return {"status": "ready"}


# ── Auth: verify invite token ──────────────────────────────────────────────────
@app.get("/auth/verify-invite")
def verify_invite_token(token: str, db: Session = Depends(get_db)):
    invitation = _pending_invite_query(db, token).order_by(Invitation.id).first()
    if not invitation or invitation.role not in INVITABLE_ROLES:
        raise HTTPException(status_code=400, detail="Invalid, expired, or revoked invitation token.")
    org = db.query(Organization).filter(
        Organization.id == invitation.org_id,
        Organization.is_active.is_(True),
    ).first()
    if not org:
        raise HTTPException(status_code=400, detail="This invitation is no longer valid.")
    email = invitation.email.strip().lower()
    user_exists = db.query(User).filter(func.lower(User.email) == email).first() is not None
    return {
        "valid": True,
        "email": email,
        "org_id": invitation.org_id,
        "user_exists": user_exists,
    }


# ── Auth: accept invite ────────────────────────────────────────────────────────
@app.post("/auth/accept-invite")
def accept_workspace_invitation(body: AcceptInviteRequest, db: Session = Depends(get_db)):
    invitations = _pending_invite_query(db, body.token).with_for_update().all()
    if not invitations:
        raise HTTPException(status_code=400, detail="Invalid, expired, or already-used invitation token.")

    first = invitations[0]
    email = first.email.strip().lower()
    org_id = first.org_id
    role = first.role
    if role not in INVITABLE_ROLES or any(
        inv.org_id != org_id or inv.email.strip().lower() != email or inv.role != role
        for inv in invitations
    ):
        raise HTTPException(status_code=400, detail="Invalid invitation data.")

    business_ids = {inv.business_id for inv in invitations}
    valid_businesses = db.query(Business.id).filter(
        Business.id.in_(business_ids),
        Business.org_id == org_id,
    ).count()
    if valid_businesses != len(business_ids):
        raise HTTPException(status_code=400, detail="Invitation references an unavailable business.")

    target_user = db.query(User).filter(func.lower(User.email) == email).first()
    if not target_user:
        name = (body.name or "").strip()
        if not name or not body.password:
            raise HTTPException(status_code=400, detail="Name and password are required for a new account.")
        try:
            validate_password(body.password)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        target_user = User(
            email=email,
            name=name,
            hashed_password=hash_password(body.password),
            plan="free",
        )
        db.add(target_user)
        db.flush()

    existing_member = db.query(OrgMember).filter(
        OrgMember.org_id == org_id,
        OrgMember.user_id == target_user.id,
    ).first()
    if not existing_member:
        db.add(OrgMember(org_id=org_id, user_id=target_user.id, role=role))
    elif role == "admin":
        existing_member.role = "admin"

    for business_id in business_ids:
        already = db.execute(user_business.select().where(
            user_business.c.user_id == target_user.id,
            user_business.c.business_id == business_id,
        )).first()
        if not already:
            db.execute(user_business.insert().values(
                user_id=target_user.id,
                business_id=business_id,
            ))

    for invitation in invitations:
        invitation.status = "accepted"
        invitation.token = None

    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Invitation acceptance transaction failed")
        raise HTTPException(status_code=500, detail="Unable to accept invitation.")
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
    org, _ = require_org_access(db, user, org_id)

    is_owner      = org.owner_id == user.id
    billing_owner = get_billing_owner(db, org)

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
    current_context                  = Depends(get_current_user),
    files:           List[UploadFile] = File(...),
    db:              Session          = Depends(get_db),
):
    import pandas as pd

    user, _ = current_context
    business, org, _ = require_business_access(db, user, business_id, admin=True)
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required.")
    if len(files) > MAX_UPLOAD_FILES:
        raise HTTPException(status_code=400, detail=f"A maximum of {MAX_UPLOAD_FILES} files may be uploaded at once.")

    # ── Plan limits ────────────────────────────────────────────────────────────
    billing_owner = get_billing_owner(db, org)
    owner_plan = (billing_owner.plan or "free").lower()
    config    = PLAN_CONFIG.get(owner_plan, PLAN_CONFIG["free"])
    max_rows  = config["max_rows"]
    max_mb    = config["max_file_mb"]

    # Parse optional JSON map: {"filename.xlsx": "context note"}
    contexts_map = {}
    if file_contexts:
        try:
            contexts_map = json.loads(file_contexts)
            if not isinstance(contexts_map, dict):
                raise ValueError
        except (TypeError, ValueError, json.JSONDecodeError):
            raise HTTPException(status_code=400, detail="file_contexts must be a JSON object.")

    uploaded = []
    for file in files:
        doc = None
        safe_filename = Path(file.filename or "").name
        if not safe_filename or safe_filename in {".", ".."}:
            raise HTTPException(status_code=400, detail="Every upload must have a valid filename.")
        context_value = contexts_map.get(safe_filename, "")
        if context_value is not None and not isinstance(context_value, str):
            raise HTTPException(status_code=400, detail=f"Context for {safe_filename} must be text.")
        specific_context = (context_value or "").strip()[:4000] or None
        ext              = Path(safe_filename).suffix.lower()
        if ext not in ALLOWED_UPLOAD_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type '{ext or 'unknown'}'.",
            )

        max_bytes = int(max_mb * 1024 * 1024)
        temp_file = tempfile.NamedTemporaryFile(
            mode="wb",
            prefix="hqlookup-upload-",
            suffix=ext,
            delete=False,
        )
        temp_path = temp_file.name
        bytes_written = 0
        try:
            while chunk := await file.read(UPLOAD_READ_SIZE):
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    temp_file.close()
                    Path(temp_path).unlink(missing_ok=True)
                    await file.close()
                    raise HTTPException(status_code=413, detail={
                        "message": f"{safe_filename} exceeds the {max_mb}MB plan limit.",
                        "limit_mb": max_mb,
                        "upgrade_url": "/billing",
                    })
                temp_file.write(chunk)
        finally:
            temp_file.close()

        try:
            if bytes_written == 0:
                raise HTTPException(status_code=400, detail=f"{safe_filename} is empty.")

            # ── Row count check (spreadsheets only) ───────────────────────────
            if ext in [".csv", ".xlsx", ".xls"]:
                try:
                    if ext == ".csv":
                        with open(temp_path, encoding="utf-8-sig", errors="replace") as f:
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
                            "upgrade_url": "/billing",
                        })
                except HTTPException:
                    raise
                except Exception:
                    logger.warning("Unable to validate spreadsheet row count", extra={"extension": ext})
                    raise HTTPException(status_code=400, detail=f"{safe_filename} could not be parsed as a spreadsheet.")

            # ── Create document record ─────────────────────────────────────────
            doc = Document(
                business_id=business.id,
                filename=safe_filename,
                content="",
                description=specific_context,
                status="processing",
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
            if chunks_count <= 0:
                raise ValueError("No indexable content was found")
            doc.status = "ready"
            db.commit()
            uploaded.append({
                "filename":    safe_filename,
                "document_id": doc.id,
                "chunks":      chunks_count,
            })

        except HTTPException:
            raise
        except Exception:
            db.rollback()
            if doc is not None and doc.id:
                failed_doc = db.query(Document).filter(Document.id == doc.id).first()
                if failed_doc:
                    failed_doc.status = "failed"
                    db.commit()
            logger.exception("Document ingestion failed", extra={"extension": ext})
            uploaded.append({
                "filename": safe_filename,
                "error":    "The file could not be ingested.",
            })
        finally:
            Path(temp_path).unlink(missing_ok=True)
            await file.close()

    clear_active_query(user.id)
    return {"uploaded": uploaded}


# ── Get documents ──────────────────────────────────────────────────────────────
@app.post("/documents", response_model=DocumentListResponse, status_code=status.HTTP_200_OK)
async def get_documents(
    payload:      DocumentRequest,
    db:           Session = Depends(get_db),
    current_auth          = Depends(get_current_user),
):
    user, _ = current_auth
    if not payload.business_ids:
        return DocumentListResponse(documents=[], total=0)

    business_ids = list(dict.fromkeys(payload.business_ids))
    for requested_id in business_ids:
        require_business_access(db, user, requested_id)

    # 2. Compute safe pagination bounds
    page = max(payload.page, 1)
    page_size = max(payload.page_size, 1)
    offset = (page - 1) * page_size

    # 3. Query documents
    query = db.query(Document).filter(Document.business_id.in_(business_ids))
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

    return {"businesses": [
        {
            "id": b.id,
            "name": b.name,
            "org_id": b.org_id,
            "query_allocation": b.query_allocation,
        }
        for b in combined
    ]}


# ── Organizations: create ──────────────────────────────────────────────────────
@app.post("/organizations", response_model=OrgResponseSchema, status_code=status.HTTP_201_CREATED)
async def create_organization(
    payload:      OrgCreateSchema,
    db:           Session = Depends(get_db),
    current_auth          = Depends(get_current_user),
):
    user, _   = current_auth
    user_plan = (user.plan or "free").lower()
    config    = PLAN_CONFIG.get(user_plan, PLAN_CONFIG["free"])
    max_orgs  = config.get("max_organizations", 1)

    owned_count = db.query(Organization).filter(Organization.owner_id == user.id).count()
    if owned_count >= max_orgs:
        raise HTTPException(
            status_code=400,
            detail=f"Your '{user_plan}' plan allows a maximum of {max_orgs} organizations.",
        )

    try:
        new_org = Organization(name=payload.name.strip(), owner_id=user.id, is_active=True)
        db.add(new_org)
        db.flush()
        db.add(OrgMember(org_id=new_org.id, user_id=user.id, role="admin"))
        db.commit()
        db.refresh(new_org)
        return new_org
    except Exception:
        db.rollback()
        logger.exception("Organization creation failed")
        raise HTTPException(status_code=500, detail="Unable to create organization.")


# ── Organizations: list ────────────────────────────────────────────────────────
@app.get("/organizations", response_model=List[OrgResponseSchema], status_code=status.HTTP_200_OK)
async def get_user_organizations(
    db:           Session = Depends(get_db),
    current_auth          = Depends(get_current_user),
):
    user, _ = current_auth
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


# ── Organizations: invite user ─────────────────────────────────────────────────
@app.post("/organizations/{org_id}/invite", status_code=status.HTTP_201_CREATED)
async def invite_user_to_workspace(
    org_id:       int,
    body:         OrgInviteRequest,
    db:           Session = Depends(get_db),
    current_auth          = Depends(get_current_user),
):
    admin_user, _ = current_auth

    org, _ = require_org_access(db, admin_user, org_id, admin=True)
    business_ids = list(dict.fromkeys(body.business_ids))
    email = str(body.email).strip().lower()

    billing_owner = get_billing_owner(db, org)
    owner_plan     = (billing_owner.plan or "free").lower()
    config         = PLAN_CONFIG.get(owner_plan, PLAN_CONFIG["free"])
    max_seats      = config.get("max_users", 2)
    active_seats   = db.query(OrgMember).filter(OrgMember.org_id == org_id).count()
    pending_seats  = db.query(func.count(func.distinct(func.lower(Invitation.email)))).filter(
        Invitation.org_id == org_id, Invitation.status == "pending"
    ).scalar() or 0
    existing_user = db.query(User).filter(func.lower(User.email) == email).first()
    is_existing_member = bool(existing_user and db.query(OrgMember).filter(
        OrgMember.org_id == org_id,
        OrgMember.user_id == existing_user.id,
    ).first())
    already_pending = db.query(Invitation).filter(
        Invitation.org_id == org_id,
        func.lower(Invitation.email) == email,
        Invitation.status == "pending",
    ).first() is not None
    additional_seat = 0 if is_existing_member or already_pending else 1
    if active_seats + pending_seats + additional_seat > max_seats:
        raise HTTPException(
            status_code=400,
            detail=f"Seat limit reached ({max_seats} max). Upgrade to invite more members.",
        )

    valid_count = db.query(Business).filter(
        Business.id.in_(business_ids), Business.org_id == org_id
    ).count()
    if valid_count != len(business_ids):
        raise HTTPException(status_code=400, detail="One or more selected business IDs are invalid.")

    if not settings.resend_api_key:
        raise HTTPException(status_code=503, detail="Invitation email service is not configured.")

    invite_token = secrets.token_urlsafe(32)
    token_digest = _invite_token_digest(invite_token)
    created_invites = []

    try:
        previous = db.query(Invitation).filter(
            Invitation.org_id == org_id,
            func.lower(Invitation.email) == email,
            Invitation.status == "pending",
        ).with_for_update().all()
        for invitation in previous:
            invitation.status = "revoked"
            invitation.token = None

        for business_id in business_ids:
            invitation = Invitation(
                org_id=org_id,
                business_id=business_id,
                email=email,
                role=body.role,
                status="pending",
                token=token_digest,
                created_at=datetime.now(timezone.utc),
            )
            db.add(invitation)
            created_invites.append(invitation)
        db.flush()

        invite_link = f"{settings.frontend_url}/accept-invite?token={invite_token}"
        escaped_org = html.escape(org.name)
        escaped_admin = html.escape(admin_user.email)
        escaped_link = html.escape(invite_link, quote=True)
        resend.Emails.send({
            "from":    settings.resend_from_email,
            "to":      [email],
            "subject": f"You've been invited to join {org.name}",
            "html":    f"""
                <div style="font-family:sans-serif;padding:20px;color:#333">
                    <h2>You're invited!</h2>
                    <p><strong>{escaped_admin}</strong> invited you to join their workspace: <strong>{escaped_org}</strong>.</p>
                    <div style="margin:24px 0">
                        <a href="{escaped_link}" style="background:#000;color:#fff;padding:12px 24px;text-decoration:none;border-radius:6px;font-weight:bold;display:inline-block">
                            Accept Invitation
                        </a>
                    </div>
                    <p style="font-size:12px;color:#666">Or copy: {escaped_link}</p>
                </div>
            """,
        })
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Invitation creation or delivery failed")
        raise HTTPException(status_code=502, detail="Invitation email could not be delivered.")

    return {
        "id": f"pending_{created_invites[0].id}",
        "email": email,
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
    business, org, _ = require_business_access(db, user, business_id, admin=True)
    if business.org_id != org_id:
        raise HTTPException(status_code=404, detail="Business not found in this organization.")

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

    require_org_access(db, user, org_id, admin=True)

    invitation = db.query(Invitation).filter(
        Invitation.id     == invitation_id,
        Invitation.org_id == org_id,
        Invitation.status == "pending",
    ).first()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found or already accepted.")

    email = invitation.email
    token = invitation.token
    related = db.query(Invitation).filter(
        Invitation.org_id == org_id,
        Invitation.token == token,
        Invitation.status == "pending",
    ).with_for_update().all()
    for related_invitation in related:
        related_invitation.status = "revoked"
        related_invitation.token = None
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

    org, _ = require_org_access(db, current_user, org_id, admin=True)
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

    require_org_access(db, current_user, body.org_id, admin=True)

    if body.status not in {"pending", "accepted", "revoked"}:
        raise HTTPException(status_code=400, detail="Invalid invitation status.")

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

    org, _ = require_org_access(db, user, body.org_id, admin=True)
    owner = get_billing_owner(db, org)
    config = PLAN_CONFIG.get((owner.plan or "free").lower(), PLAN_CONFIG["free"])
    business_count = db.query(Business).filter(Business.org_id == org.id).count()
    if business_count >= config.get("max_businesses", 1):
        raise HTTPException(status_code=400, detail="Business limit reached for this organization's plan.")

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

    business, org, _ = require_business_access(db, user, settings_data.business_id, admin=True)
    if org.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the org owner can change allocations.")

    billing_owner = get_billing_owner(db, org)
    plan_limit = PLAN_CONFIG.get((billing_owner.plan or "free").lower(), PLAN_CONFIG["free"]).get("monthly_searches", 50)
    total_allocated = (
        db.query(func.sum(Business.query_allocation))
        .filter(Business.org_id == org.id)
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
MAX_LLM_CALLS_PER_REQUEST = 50


@app.post("/ask")
def ask_question(
    body: AskRequest,
    db: Session = Depends(get_db),
    current_context=Depends(get_current_user),
):
    user, _ = current_context

    # ------------------------------------------------------------------
    # 1. Validate business / organization access
    # ------------------------------------------------------------------

    business, org, _ = require_business_access(db, user, body.business_id)
    billing_owner = get_billing_owner(db, org)
    user_plan = (billing_owner.plan or "free").lower()

    config = PLAN_CONFIG.get(
        user_plan,
        PLAN_CONFIG["free"],
    )

    # ------------------------------------------------------------------
    # 2. Check search limits
    # ------------------------------------------------------------------

    try:
        allowed, current, limit = check_search_limit(org.id, user_plan)
    except QuotaBackendUnavailable as exc:
        raise HTTPException(status_code=503, detail="Search quota service is temporarily unavailable.") from exc

    if not allowed:
        raise HTTPException(
            status_code=402,
            detail={
                "message": f"Monthly limit of {limit} searches reached.",
                "current": current,
                "limit": limit,
                "upgrade_url": "/billing",
            },
        )

    remaining_plan_calls = MAX_LLM_CALLS_PER_REQUEST

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
        logger.debug("Search cache hit")

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
        logger.debug("Search cache miss")

        try:
            reserved, current, limit = consume_search_quota(org.id, user_plan)
        except QuotaBackendUnavailable as exc:
            raise HTTPException(status_code=503, detail="Search quota service is temporarily unavailable.") from exc
        if not reserved:
            raise HTTPException(
                status_code=402,
                detail={
                    "message": f"Monthly limit of {limit} searches reached.",
                    "current": current,
                    "limit": limit,
                    "upgrade_url": "/billing",
                },
            )
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

        logger.debug("Initial retrieval completed with %d candidates", len(retrieval_results))

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
                logger.debug("Retrieval candidate pool exhausted")
                break

            if retrieval_limit >= MAX_RETRIEVAL_SIZE:
                logger.debug("Maximum retrieval size reached")

                retrieval_fully_exhausted = True
                break

            new_retrieval_limit = min(
                retrieval_limit + RETRIEVAL_EXPAND_SIZE,
                MAX_RETRIEVAL_SIZE,
            )

            logger.debug("Expanding retrieval window")

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

            logger.debug(
                "Expanded retrieval returned %d candidates (%d new)",
                len(expanded_results),
                len(new_results),
            )

            retrieval_limit = new_retrieval_limit

            if not new_results:
                retrieval_fully_exhausted = True

                logger.debug("Expanded retrieval returned no new candidates")

                break

            retrieval_results.extend(
                new_results
            )

            logger.debug("Retrieval pool now contains %d candidates", len(retrieval_results))

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

        logger.debug("Processing an LLM batch with %d candidates", len(chunks))

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
                logger.warning("LLM returned a non-object tabular decision")
                return

            chunk_id = record.get(
                "chunk_id"
            )

            if chunk_id is None:
                logger.warning("LLM returned a tabular decision without a chunk ID")
                return

            try:
                chunk_id = int(
                    chunk_id
                )

            except (TypeError, ValueError):
                logger.warning("LLM returned an invalid chunk ID")
                return

            # ----------------------------------------------------------
            # Reject chunk IDs that were not actually sent.
            # ----------------------------------------------------------

            if chunk_id not in expected_ids:
                logger.warning("LLM returned a chunk ID outside the requested batch")
                return

            # ----------------------------------------------------------
            # Only one decision per spreadsheet row.
            # ----------------------------------------------------------

            if chunk_id in returned_ids:
                logger.warning("LLM returned a duplicate chunk decision")
                return

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

                return

            # ----------------------------------------------------------
            # MATCH
            # ----------------------------------------------------------

            answer_text = normalize_answer_text(
                record.get("answer")
            )

            if not answer_text:
                logger.warning("LLM returned a positive match without an answer")

                # Do NOT add it to returned_ids.
                #
                # That makes this row eligible for retry.
                return

            returned_ids.add(
                chunk_id
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
                logger.warning("LLM returned a non-object text answer")
                continue

            answer_text = normalize_answer_text(
                text_answer.get("answer")
            )

            if not answer_text:
                continue

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
            logger.warning("LLM omitted %d tabular decisions", len(missing_tabular_ids))

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

            logger.debug("Retrying %d missing tabular decisions", len(missing_tabular_ids))

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
                    logger.warning("A missing tabular decision could not be mapped to its chunk")
                    continue

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
            logger.warning("LLM omitted tabular decisions after all retries; batch was not committed")

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

    logger.debug("Answer pagination produced %d results", len(page_answers))

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
    user, _ = current_user
    require_business_access(db, user, business_id)

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
    user, _ = current_user
    require_business_access(db, user, business_id, admin=True)

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
