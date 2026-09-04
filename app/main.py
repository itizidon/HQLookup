import uvicorn
import hashlib
import html
import json
import math
import secrets
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Depends, Query, HTTPException, Form, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from typing import List, Literal, Optional
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pathlib import Path
from app.settings import settings

settings.validate()

from app.database import get_db
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.routes.auth import router as auth_router
from app.models import Business, User, Document, QueryLog, Organization, OrgMember, Invitation, user_business
from app.rag import (
    ingest_document,
    retrieve_chunks,
    retrieve_chunks_multi,
    QuotaBackendUnavailable,
    reserve_search,
    clear_active_query,
    get_active_query,
    set_active_query,
    get_embedder,
    normalize_query,
    PLAN_CONFIG,
)
from app.llm import generate_answer
from pydantic import BaseModel, Field, EmailStr, field_validator
from app.auth import MIN_PASSWORD_LENGTH, get_current_user, hash_password, validate_password, verify_password
from app.access import (
    get_accessible_businesses,
    get_billing_owner,
    get_user_organization_ids,
    require_business_access,
    require_businesses_access,
    require_organization_access,
)
from app.security import CookieOriginMiddleware, UploadBodyLimitMiddleware
from app.rate_limit import (
    limit_document_upload,
    limit_invite_accept,
    limit_invite_send,
    limit_invite_verify,
    limit_search,
)
from app.uploads import UnsafeUpload, count_spreadsheet_rows, store_upload
from datetime import datetime, timedelta, timezone
from app.routes.billing import router as billing_router

from app.email_outbox import enqueue_email


# ── Request / Response models ──────────────────────────────────────────────────
class BusinessSettingsUpdate(BaseModel):
    business_id:      int = Field(..., description="The unique ID of the business being updated")
    query_allocation: int = Field(..., ge=0, description="The maximum number of allowed searches")

class AskRequest(BaseModel):
    question:    str = Field(..., min_length=1, max_length=4000)
    get_k:       int = Field(default=3, ge=1, le=50)
    offset:      int = Field(default=0, ge=0, le=10_000)
    business_id: int = Field(..., gt=0)

class CreateBusinessRequest(BaseModel):
    name:   str = Field(..., min_length=1, max_length=200)
    org_id: int = Field(..., gt=0)

class BusinessResponse(BaseModel):
    id:   int
    name: str
    model_config = {"from_attributes": True}

class DocumentRequest(BaseModel):
    business_ids: List[int] = Field(default_factory=list, max_length=100)
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
    total: int

class OrgCreateSchema(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)

class OrgResponseSchema(BaseModel):
    id:       int
    name:     str
    owner_id: int
    is_active: bool
    model_config = {"from_attributes": True}

class WorkspaceQueryRequest(BaseModel):
    org_id:      int
    business_id: int
    status:      Literal["pending"] = "pending"

class AcceptInviteRequest(BaseModel):
    token:    str = Field(..., min_length=32, max_length=512)
    password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=256)
    name:     str = Field(default="User", min_length=1, max_length=200)

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, value: str) -> str:
        return validate_password(value)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required.")
        return value


class VerifyInviteRequest(BaseModel):
    token: str = Field(..., min_length=32, max_length=512)

class OrgInviteRequest(BaseModel):
    email:        EmailStr
    role:         Literal["admin", "member"] = "member"
    business_ids: List[int] = Field(
        default_factory=list,
        min_length=1,
        max_length=100,
    )

class MultiOrgBusinessesRequest(BaseModel):
    org_ids: List[int] = Field(
        default_factory=list,
        max_length=100,
        description="List of target organization IDs to filter businesses by",
    )


# ── App setup ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.is_production:
        get_embedder()
    yield


app = FastAPI(
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)


app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=list(settings.trusted_hosts),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Accept", "Content-Type"],
)
app.add_middleware(
    CookieOriginMiddleware,
    allowed_origins=settings.cors_origins,
    cookie_names=("token", "__Host-token"),
)
app.add_middleware(
    UploadBodyLimitMiddleware,
    # Keep JSON/form endpoints bounded while leaving room for multipart
    # boundaries and the optional context form field.
    max_bytes=1024 * 1024,
    path_limits={
        "/upload-multiple": (settings.max_upload_total_mb + 2) * 1024 * 1024,
        "/billing/webhook": 1024 * 1024,
    },
)


@app.exception_handler(RequestValidationError)
async def sanitized_validation_error(_request, exc: RequestValidationError):
    """Return useful validation errors without echoing submitted secrets."""

    errors = [
        {
            "loc": list(error.get("loc", ())),
            "msg": str(error.get("msg", "Invalid request value")),
            "type": str(error.get("type", "value_error")),
        }
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


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

def _coerce_chunk_id(value) -> int | None:
    """Return a positive integer chunk ID without lossy coercion."""

    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        chunk_id = value
    elif isinstance(value, str) and value.strip().isdigit():
        chunk_id = int(value.strip())
    else:
        return None

    return chunk_id if chunk_id > 0 else None


def resolve_answer_sources(
    chunks: list[dict],
    requested_sources=None,
    *,
    fallback_to_all: bool = False,
) -> list[dict]:
    """Resolve LLM citations against retrieved chunks and add similarity scores."""

    chunks_by_id = {}

    for chunk in chunks:
        chunk_id = _coerce_chunk_id(
            chunk.get("id")
        )

        if chunk_id is None:
            continue

        chunks_by_id[chunk_id] = chunk

    requested_ids = []
    seen_ids = set()

    if isinstance(requested_sources, list):
        for source in requested_sources:
            if not isinstance(source, dict):
                continue

            chunk_id = source.get("chunk")

            if chunk_id is None:
                chunk_id = source.get("chunk_id")

            chunk_id = _coerce_chunk_id(
                chunk_id
            )

            if chunk_id is None:
                continue

            if chunk_id in chunks_by_id and chunk_id not in seen_ids:
                requested_ids.append(chunk_id)
                seen_ids.add(chunk_id)

    if requested_ids:
        source_chunks = [
            chunks_by_id[chunk_id]
            for chunk_id in requested_ids
        ]
    elif fallback_to_all:
        source_chunks = list(chunks_by_id.values())
    else:
        source_chunks = []

    resolved_sources = []

    for chunk in source_chunks:
        chunk_id = _coerce_chunk_id(
            chunk.get("id")
        )

        if chunk_id is None:
            continue

        raw_score = chunk.get("score")

        try:
            correlation = float(raw_score)
        except (TypeError, ValueError):
            correlation = None

        if correlation is not None and not math.isfinite(correlation):
            correlation = None

        resolved_sources.append({
            "chunk": chunk_id,
            "filename": str(chunk.get("filename") or "Unknown source"),
            "correlation": (
                round(correlation, 4)
                if correlation is not None
                else None
            ),
        })

    return resolved_sources


# ── Routes ─────────────────────────────────────────────────────────────────────
@app.get("/")
def read_root():
    return {"Hello": "World"}


INVITATION_LIFETIME = timedelta(days=7)


def invitation_token_hash(token: str) -> str:
    """Return the non-reversible identifier stored for an invitation token."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _aware_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _load_pending_invitation_group(
    db: Session,
    token: str,
    *,
    for_update: bool = False,
) -> list[Invitation]:
    token_hash = invitation_token_hash(token)
    query = db.query(Invitation).filter(
        Invitation.token_hash == token_hash,
        Invitation.status == "pending",
    )
    if for_update:
        query = query.with_for_update()
    invitations = query.order_by(Invitation.id.asc()).all()
    if not invitations:
        raise HTTPException(status_code=400, detail="Invalid invitation token.")

    now = datetime.now(timezone.utc)
    if any(
        invitation.expires_at is None
        or _aware_utc(invitation.expires_at) <= now
        for invitation in invitations
    ):
        raise HTTPException(status_code=400, detail="This invitation link has expired.")

    org_ids = {invitation.org_id for invitation in invitations}
    emails = {invitation.email.strip().lower() for invitation in invitations}
    roles = {invitation.role for invitation in invitations}
    if len(org_ids) != 1 or len(emails) != 1 or len(roles) != 1:
        raise HTTPException(status_code=400, detail="Invalid invitation token.")
    if not roles.issubset({"admin", "member"}):
        raise HTTPException(status_code=400, detail="Invalid invitation token.")

    org_id = next(iter(org_ids))
    active_org = db.query(Organization).filter(
        Organization.id == org_id,
        Organization.is_active.is_(True),
    ).first()
    if active_org is None:
        raise HTTPException(status_code=400, detail="Invalid invitation token.")

    business_ids = {invitation.business_id for invitation in invitations}
    valid_business_count = db.query(Business).filter(
        Business.id.in_(business_ids),
        Business.org_id == org_id,
    ).count()
    if valid_business_count != len(business_ids):
        raise HTTPException(status_code=400, detail="Invalid invitation token.")

    return invitations


# ── Auth: verify invite token ──────────────────────────────────────────────────
@app.post("/auth/verify-invite", dependencies=[Depends(limit_invite_verify)])
def verify_invite_token(body: VerifyInviteRequest, db: Session = Depends(get_db)):
    invitations = _load_pending_invitation_group(db, body.token)
    invitation = invitations[0]
    email = invitation.email.strip().lower()
    user_exists = db.query(User).filter(func.lower(User.email) == email).first() is not None
    return {
        "valid": True,
        "email": email,
        "org_id": invitation.org_id,
        "user_exists": user_exists,
    }


# ── Auth: accept invite ────────────────────────────────────────────────────────
@app.post("/auth/accept-invite", dependencies=[Depends(limit_invite_accept)])
def accept_workspace_invitation(body: AcceptInviteRequest, db: Session = Depends(get_db)):
    try:
        # Lock every row represented by this bearer token. A concurrent accept
        # blocks here and, after the first commit, can no longer find a pending
        # row, making the token genuinely single-use.
        invitations = _load_pending_invitation_group(db, body.token, for_update=True)
        first_invitation = invitations[0]
        email = first_invitation.email.strip().lower()
        org_id = first_invitation.org_id
        role = first_invitation.role
        business_ids = {invitation.business_id for invitation in invitations}

        target_user = (
            db.query(User).filter(func.lower(User.email) == email).with_for_update().first()
        )
        if target_user:
            if not verify_password(body.password, target_user.hashed_password):
                raise HTTPException(
                    status_code=401,
                    detail="Invalid invitation credentials.",
                )
            target_user.email_verified_at = datetime.now(timezone.utc)
            target_user.email_verification_token_hash = None
            target_user.email_verification_expires_at = None
        else:
            target_user = User(
                email=email,
                name=body.name,
                hashed_password=hash_password(body.password),
                plan="free",
                email_verified_at=datetime.now(timezone.utc),
            )
            db.add(target_user)
            db.flush()

        existing_member = db.query(OrgMember).filter(
            OrgMember.org_id == org_id,
            OrgMember.user_id == target_user.id,
        ).with_for_update().first()
        if not existing_member:
            db.add(OrgMember(org_id=org_id, user_id=target_user.id, role=role))
        elif role == "admin" and existing_member.role != "admin":
            existing_member.role = "admin"

        for business_id in business_ids:
            already_assigned = db.execute(
                user_business.select().where(
                    user_business.c.user_id == target_user.id,
                    user_business.c.business_id == business_id,
                )
            ).first()
            if not already_assigned:
                db.execute(user_business.insert().values(
                    user_id=target_user.id,
                    business_id=business_id,
                ))

        for invitation in invitations:
            invitation.status = "accepted"

        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to accept invitation.",
        ) from exc

    return {"status": "success", "message": "Invitation accepted. You can now sign in."}


# ── Auth: current user profile ─────────────────────────────────────────────────
@app.get("/auth/me")
def get_current_user_profile(current_auth = Depends(get_current_user)):
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
def get_comprehensive_usage_metrics(
    org_id:       int,
    current_auth          = Depends(get_current_user),
    db:           Session = Depends(get_db),
):
    user, _ = current_auth
    access = require_organization_access(db, user, org_id)
    org = access.organization

    is_owner = access.is_owner
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

    businesses = get_accessible_businesses(db, user, org_id)
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
def upload_documents(
    business_id:     int              = Form(...),
    file_contexts:   Optional[str]    = Form(None),
    current_context: User             = Depends(get_current_user),
    files:           List[UploadFile] = File(...),
    db:              Session          = Depends(get_db),
):
    user, _ = current_context
    business = require_business_access(db, user, business_id)
    limit_document_upload(user.id)

    if not files or len(files) > settings.max_upload_files:
        raise HTTPException(
            status_code=400,
            detail=f"Upload between 1 and {settings.max_upload_files} files at a time.",
        )

    # ── Plan limits ────────────────────────────────────────────────────────────
    billing_owner = get_billing_owner(db, business.organization)
    user_plan = (billing_owner.plan or "free").lower()
    config    = PLAN_CONFIG.get(user_plan, PLAN_CONFIG["free"])
    max_rows  = config["max_rows"]
    max_mb    = config["max_file_mb"]

    # Parse either the current index-aligned notes array or the legacy filename map.
    contexts_map: dict[str, str] = {}
    contexts_by_index: list[str] | None = None
    if file_contexts:
        if len(file_contexts) > 100_000:
            raise HTTPException(status_code=400, detail="file_contexts is too large.")
        try:
            raw_contexts = json.loads(file_contexts)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail="file_contexts must be valid JSON.",
            ) from exc
        if isinstance(raw_contexts, list):
            if len(raw_contexts) != len(files) or any(
                not isinstance(value, str) for value in raw_contexts
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "file_contexts must contain one text value per uploaded file."
                    ),
                )
            if any(len(value) > 4000 for value in raw_contexts):
                raise HTTPException(
                    status_code=400,
                    detail="A file context is too long.",
                )
            contexts_by_index = [value.strip() for value in raw_contexts]
        elif not isinstance(raw_contexts, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in raw_contexts.items()
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "file_contexts must be an array aligned with files or map "
                    "filenames to text."
                ),
            )
        else:
            if any(len(value) > 4000 for value in raw_contexts.values()):
                raise HTTPException(
                    status_code=400,
                    detail="A file context is too long.",
                )
            contexts_map = {
                Path(key).name: value.strip()
                for key, value in raw_contexts.items()
            }

    uploaded = []
    total_bytes = 0
    max_file_bytes = int(max_mb * 1024 * 1024)
    max_total_bytes = settings.max_upload_total_mb * 1024 * 1024

    for file_index, file in enumerate(files):
        stored = None
        display_filename = Path(file.filename or "upload").name[:255] or "upload"

        try:
            stored = store_upload(
                file,
                max_file_bytes=max_file_bytes,
                max_remaining_bytes=max_total_bytes - total_bytes,
            )
            total_bytes += stored.size_bytes
            specific_context = (
                contexts_by_index[file_index]
                if contexts_by_index is not None
                else contexts_map.get(stored.filename, "")
            ) or None

            # ── Row count check (spreadsheets only) ───────────────────────────
            if stored.extension in {".csv", ".xlsx", ".xlsm", ".xls"}:
                row_count = count_spreadsheet_rows(
                    stored.path,
                    stored.extension,
                    stop_after=max_rows,
                )
                if row_count > max_rows:
                    raise UnsafeUpload(
                        f"Spreadsheet exceeds the {max_rows}-row {config['display_name']} plan limit"
                    )

            # ── Create document record ─────────────────────────────────────────
            doc = Document(
                business_id=business.id,
                filename=stored.filename,
                content="",
                description=specific_context,
                status="ready",
            )
            db.add(doc)
            db.flush()

            # ── Ingest ─────────────────────────────────────────────────────────
            chunks_count = ingest_document(
                db=db,
                business_id=business.id,
                document_id=doc.id,
                file_path=stored.path,
                filename=stored.filename,
                ingestion_notes=specific_context,
            )
            if chunks_count <= 0:
                raise UnsafeUpload("Document did not contain searchable content")

            uploaded.append({
                "filename":    stored.filename,
                "document_id": doc.id,
                "chunks":      chunks_count,
            })

        except UnsafeUpload as exc:
            db.rollback()
            uploaded.append({
                "filename": display_filename,
                "error": str(exc),
            })
        except Exception:
            db.rollback()
            uploaded.append({
                "filename": display_filename,
                "error": "Upload processing failed.",
            })
        finally:
            if stored is not None:
                Path(stored.path).unlink(missing_ok=True)

    clear_active_query(user.id)
    return {"uploaded": uploaded}


# ── Get documents ──────────────────────────────────────────────────────────────
@app.post("/documents", response_model=DocumentListResponse, status_code=status.HTTP_200_OK)
def get_documents(
    payload:      DocumentRequest,
    db:           Session = Depends(get_db),
    current_auth          = Depends(get_current_user),
):
    if not payload.business_ids:
        return DocumentListResponse(documents=[], total=0)

    user, _ = current_auth
    authorized_business_ids = [
        business.id
        for business in require_businesses_access(db, user, payload.business_ids)
    ]

    # 2. Compute safe pagination bounds
    page = max(payload.page, 1)
    page_size = max(payload.page_size, 1)
    offset = (page - 1) * page_size

    # 3. Query documents
    query = db.query(Document).filter(Document.business_id.in_(authorized_business_ids))
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

    combined = []
    for org_id in dict.fromkeys(requested_org_ids):
        access = require_organization_access(db, user, org_id)
        for business in get_accessible_businesses(db, user, org_id):
            combined.append({
                "id": business.id,
                "name": business.name,
                "org_id": business.org_id,
                "query_allocation": business.query_allocation,
                "can_edit_usage_limits": access.is_owner,
                "can_invite_members": access.is_admin,
            })

    return {"businesses": combined}


# ── Organizations: create ──────────────────────────────────────────────────────
@app.post("/organizations", response_model=OrgResponseSchema, status_code=status.HTTP_201_CREATED)
def create_organization(
    payload:      OrgCreateSchema,
    db:           Session = Depends(get_db),
    current_auth          = Depends(get_current_user),
):
    user, _   = current_auth
    # Serialize entitlement checks so concurrent requests cannot exceed the
    # organization cap.
    locked_user = (
        db.query(User)
        .filter(User.id == user.id)
        .populate_existing()
        .with_for_update()
        .one()
    )
    user_plan = (locked_user.plan or "free").lower()
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
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to create organization.",
        ) from exc


# ── Organizations: list ────────────────────────────────────────────────────────
@app.get("/organizations", response_model=List[OrgResponseSchema], status_code=status.HTTP_200_OK)
def get_user_organizations(
    db:           Session = Depends(get_db),
    current_auth          = Depends(get_current_user),
):
    user, _ = current_auth
    org_ids = get_user_organization_ids(db, user)
    if not org_ids:
        return []
    return db.query(Organization).filter(Organization.id.in_(org_ids)).all()


# ── Organizations: invite user ─────────────────────────────────────────────────
@app.post("/organizations/{org_id}/invite", status_code=status.HTTP_201_CREATED)
def invite_user_to_workspace(
    org_id:       int,
    body:         OrgInviteRequest,
    db:           Session = Depends(get_db),
    current_auth          = Depends(get_current_user),
):
    admin_user, _ = current_auth
    access = require_organization_access(db, admin_user, org_id, admin=True)
    limit_invite_send(admin_user.id, org_id)
    # Serialize seat checks and invitation replacement within an organization.
    org = db.query(Organization).filter(
        Organization.id == access.organization.id
    ).with_for_update().one()
    normalized_email = str(body.email).strip().lower()
    business_ids = list(dict.fromkeys(body.business_ids))

    valid_count = db.query(Business).filter(
        Business.id.in_(business_ids),
        Business.org_id == org_id,
    ).count()
    if valid_count != len(business_ids):
        raise HTTPException(
            status_code=400,
            detail="One or more selected business IDs are invalid.",
        )

    billing_owner = get_billing_owner(db, org)
    owner_plan = (billing_owner.plan or "free").lower()
    max_seats = PLAN_CONFIG.get(owner_plan, PLAN_CONFIG["free"]).get("max_users", 2)
    active_seats = db.query(OrgMember).filter(OrgMember.org_id == org_id).count()
    target_is_member = db.query(OrgMember).join(User, OrgMember.user_id == User.id).filter(
        OrgMember.org_id == org_id,
        func.lower(User.email) == normalized_email,
    ).first() is not None
    other_pending_seats = db.query(
        func.count(func.distinct(func.lower(Invitation.email)))
    ).filter(
        Invitation.org_id == org_id,
        Invitation.status == "pending",
        Invitation.expires_at > datetime.now(timezone.utc),
        func.lower(Invitation.email) != normalized_email,
    ).scalar() or 0
    prospective_seats = active_seats + other_pending_seats + (0 if target_is_member else 1)
    if prospective_seats > max_seats:
        raise HTTPException(
            status_code=400,
            detail=f"Seat limit reached ({max_seats} max). Upgrade to invite more members.",
        )

    raw_token = secrets.token_urlsafe(32)
    token_hash = invitation_token_hash(raw_token)
    now = datetime.now(timezone.utc)
    expires_at = now + INVITATION_LIFETIME
    # Keep the bearer token in the URL fragment. Fragments are not sent to the
    # frontend server, reverse proxy, or access logs; client code removes it
    # before verification.
    invite_link = f"{settings.frontend_url}/accept-invite#token={raw_token}"
    created_invitations: list[Invitation] = []

    try:
        # A resend replaces the old grant set so an earlier email cannot grant
        # locations that an administrator subsequently removed.
        old_pending = db.query(Invitation).filter(
            Invitation.org_id == org_id,
            func.lower(Invitation.email) == normalized_email,
            Invitation.status == "pending",
        ).with_for_update().all()
        for invitation in old_pending:
            invitation.status = "revoked"
        for business_id in business_ids:
            invitation = Invitation(
                org_id=org_id,
                business_id=business_id,
                email=normalized_email,
                role=body.role,
                status="pending",
                token=None,
                token_hash=token_hash,
                expires_at=expires_at,
                created_at=now,
            )
            db.add(invitation)
            created_invitations.append(invitation)

        db.flush()
        primary_invite_id = created_invitations[0].id

        safe_admin_email = html.escape(admin_user.email)
        safe_org_name = html.escape(org.name)
        safe_invite_link = html.escape(invite_link, quote=True)
        subject_org_name = str(org.name).replace("\r", " ").replace("\n", " ")[:200]
        enqueue_email(
            db,
            recipient=normalized_email,
            subject=f"You've been invited to join {subject_org_name}",
            kind="workspace_invitation",
            expires_at=expires_at,
            html=f"""
                <div style="font-family:sans-serif;padding:20px;color:#333">
                    <h2>You're invited!</h2>
                    <p><strong>{safe_admin_email}</strong> invited you to join their workspace: <strong>{safe_org_name}</strong>.</p>
                    <div style="margin:24px 0">
                        <a href="{safe_invite_link}" style="background:#000;color:#fff;padding:12px 24px;text-decoration:none;border-radius:6px;font-weight:bold;display:inline-block">
                            Accept Invitation
                        </a>
                    </div>
                    <p style="font-size:12px;color:#666">Or copy: {safe_invite_link}</p>
                </div>
            """,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to create or deliver invitation.",
        ) from exc

    return {
        "id": f"pending_{primary_invite_id}",
        "email": normalized_email,
        "role": body.role,
        "status": "pending",
        "created_at": now.isoformat(),
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
    business = require_business_access(
        db,
        user,
        business_id,
        org_id=org_id,
        admin=True,
    )
    org = business.organization

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
            
        is_owner = int(org.owner_id) == int(u.id)
        is_admin = (m.role or "").lower() == "admin"
        is_assigned = u.id in assigned_user_ids

        if is_owner or is_admin or is_assigned:
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
            Invitation.expires_at > datetime.now(timezone.utc),
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
    require_organization_access(db, user, org_id, admin=True)

    invitation = db.query(Invitation).filter(
        Invitation.id     == invitation_id,
        Invitation.org_id == org_id,
        Invitation.status == "pending",
    ).with_for_update().first()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found or already accepted.")

    email = invitation.email
    invitation_group = [invitation]
    if invitation.token_hash:
        invitation_group = db.query(Invitation).filter(
            Invitation.org_id == org_id,
            Invitation.token_hash == invitation.token_hash,
            Invitation.status == "pending",
        ).with_for_update().all()
    for grouped_invitation in invitation_group:
        grouped_invitation.status = "revoked"
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

    access = require_organization_access(db, current_user, org_id, admin=True)
    org = access.organization
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

    require_organization_access(db, current_user, body.org_id, admin=True)

    invites = db.query(Invitation).filter(
        Invitation.org_id == body.org_id,
        Invitation.status == body.status,
        Invitation.expires_at > datetime.now(timezone.utc),
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

    require_organization_access(db, user, body.org_id, admin=True)
    # Serialize the count/create decision within this organization.
    org = db.query(Organization).filter(
        Organization.id == body.org_id
    ).with_for_update().one()
    if not org.is_active:
        raise HTTPException(status_code=402, detail="Organization is inactive.")

    billing_owner = get_billing_owner(db, org)
    owner_plan = (billing_owner.plan or "free").lower()
    max_businesses = PLAN_CONFIG.get(owner_plan, PLAN_CONFIG["free"]).get(
        "max_businesses",
        1,
    )
    business_count = db.query(Business).filter(Business.org_id == org.id).count()
    if business_count >= max_businesses:
        raise HTTPException(
            status_code=400,
            detail=f"The {owner_plan} plan allows at most {max_businesses} businesses.",
        )

    business = Business(name=business_name, org_id=org.id)
    db.add(business)
    db.commit()
    db.refresh(business)
    return business


# ── Businesses: update settings ────────────────────────────────────────────────
@app.patch("/businesses/settings")
def update_business_settings(
    settings_data: BusinessSettingsUpdate,
    current_auth           = Depends(get_current_user),
    db:            Session = Depends(get_db),
):
    user, _ = current_auth

    business = require_business_access(
        db,
        user,
        settings_data.business_id,
        admin=True,
    )
    org = business.organization
    if org.owner_id != user.id:
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
    limit_search(user.id)

    # ------------------------------------------------------------------
    # 1. Validate business / organization access
    # ------------------------------------------------------------------

    business = require_business_access(db, user, body.business_id)

    if not business or not business.organization:
        raise HTTPException(
            status_code=403,
            detail="Access denied.",
        )

    org = business.organization

    billing_owner = get_billing_owner(db, org)
    user_plan = (billing_owner.plan or "free").lower()

    config = PLAN_CONFIG.get(
        user_plan,
        PLAN_CONFIG["free"],
    )

    # ------------------------------------------------------------------
    # 2. Atomically reserve this request's search quota. Cost-bearing requests
    # fail closed if Redis is unavailable, and each HTTP request has a separate
    # hard cap on downstream model calls.
    # ------------------------------------------------------------------

    try:
        reservation = reserve_search(
            org.id,
            user_plan,
            body.business_id,
            getattr(business, "query_allocation", 25),
        )
        if len(reservation) == 3:
            allowed, current, limit = reservation
            business_current = 0
            business_limit = getattr(business, "query_allocation", 25)
            quota_reason = 0
        else:
            (
                allowed,
                current,
                limit,
                business_current,
                business_limit,
                quota_reason,
            ) = reservation
    except QuotaBackendUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="Search quota service is temporarily unavailable.",
        ) from exc

    if not allowed:
        if quota_reason == 2:
            raise HTTPException(
                status_code=402,
                detail={
                    "message": f"Business monthly allocation of {business_limit} searches reached.",
                    "current": business_current,
                    "limit": business_limit,
                    "upgrade_url": "/billing",
                },
            )
        raise HTTPException(
            status_code=402,
            detail={
                "message": f"Monthly limit of {limit} searches reached.",
                "current": current,
                "limit": limit,
                "upgrade_url": "/billing",
            },
        )

    max_llm_calls = settings.max_llm_calls_per_request
    request_deadline = time.monotonic() + settings.ask_deadline_seconds
    llm_calls = 0

    def reserve_llm_call() -> bool:
        nonlocal llm_calls
        if llm_calls >= max_llm_calls or time.monotonic() >= request_deadline:
            return False
        llm_calls += 1
        return True

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
                reserve_llm_call=reserve_llm_call,
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
                reserve_llm_call=reserve_llm_call,
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

    target_answer_count = (
        answer_offset
        + ANSWER_PAGE_SIZE
    )

    while (
        len(all_answers) < target_answer_count
        and llm_calls < max_llm_calls
        and time.monotonic() < request_deadline
    ):

        # ==============================================================
        # CURRENT RETRIEVAL POOL HAS BEEN PROCESSED
        # ==============================================================

        if retrieval_cursor >= len(retrieval_results):

            if retrieval_fully_exhausted:
                break

            if retrieval_limit >= MAX_RETRIEVAL_SIZE:
                retrieval_fully_exhausted = True
                break

            new_retrieval_limit = min(
                retrieval_limit + RETRIEVAL_EXPAND_SIZE,
                MAX_RETRIEVAL_SIZE,
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
                    reserve_llm_call=reserve_llm_call,
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
                    reserve_llm_call=reserve_llm_call,
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
                    reserve_llm_call=reserve_llm_call,
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

            retrieval_limit = new_retrieval_limit

            if not new_results:
                retrieval_fully_exhausted = True
                break

            retrieval_results.extend(
                new_results
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

        # --------------------------------------------------------------
        # Main LLM call
        # --------------------------------------------------------------

        if not reserve_llm_call():
            break

        result = generate_answer(
            body.question,
            chunks,
        )

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
                return

            chunk_id = record.get(
                "chunk_id"
            )

            if chunk_id is None:
                return

            try:
                chunk_id = int(
                    chunk_id
                )

            except (TypeError, ValueError):
                return

            # ----------------------------------------------------------
            # Reject chunk IDs that were not actually sent.
            # ----------------------------------------------------------

            if chunk_id not in expected_ids:
                return

            # ----------------------------------------------------------
            # Only one decision per spreadsheet row.
            # ----------------------------------------------------------

            if chunk_id in returned_ids:
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
                return

            # ----------------------------------------------------------
            # MATCH
            # ----------------------------------------------------------

            answer_text = normalize_answer_text(
                record.get("answer")
            )

            if not answer_text:
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
                "sources": resolve_answer_sources(
                    [original_chunk] if original_chunk else [],
                    fallback_to_all=True,
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

        text_chunks = [
            chunk
            for chunk in chunks
            if chunk.get("content_type") != "tabular"
        ]

        for text_answer in text_answers:

            if not isinstance(text_answer, dict):
                continue

            answer_text = normalize_answer_text(
                text_answer.get("answer")
            )

            if not answer_text:
                continue

            requested_sources = text_answer.get(
                "sources"
            )

            citations_omitted = (
                requested_sources is None
                or (
                    isinstance(requested_sources, list)
                    and not requested_sources
                )
            )

            batch_answers.append({
                "answer": answer_text,
                "confidence": text_answer.get(
                    "confidence",
                    0.0,
                ),
                "sources": resolve_answer_sources(
                    text_chunks,
                    requested_sources,
                    # If citations are omitted, expose the context that
                    # produced the answer. A non-empty but invalid citation
                    # list is not silently replaced with unrelated chunks.
                    fallback_to_all=citations_omitted,
                ),
            })

        # ==============================================================
        # DETECT MISSING SPREADSHEET DECISIONS
        # ==============================================================

        missing_tabular_ids = (
            input_tabular_ids
            - returned_tabular_ids
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
            and llm_calls < max_llm_calls
            and time.monotonic() < request_deadline
        ):
            retry_round += 1

            ids_to_retry = sorted(
                missing_tabular_ids
            )

            for missing_id in ids_to_retry:

                if (
                    llm_calls >= max_llm_calls
                    or time.monotonic() >= request_deadline
                ):
                    break

                missing_chunk = tabular_chunks_by_id.get(
                    missing_id
                )

                if not missing_chunk:
                    continue

                # ------------------------------------------------------
                # Retry ONE missing spreadsheet row.
                # ------------------------------------------------------

                if not reserve_llm_call():
                    break

                retry_result = generate_answer(
                    body.question,
                    [missing_chunk],
                )

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
    require_business_access(db, user, business_id)

    doc = db.query(Document).filter(Document.id == document_id, Document.business_id == business_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    from app.models import Chunk
    db.query(Chunk).filter(Chunk.document_id == document_id).delete()
    db.delete(doc)
    # Query logs and Redis retrieval caches can contain derived excerpts from
    # the deleted document. Clear them for the whole tenant, not just the
    # deleting user's browser session.
    db.query(QueryLog).filter(QueryLog.business_id == business_id).delete(
        synchronize_session=False
    )
    db.commit()
    member_ids = {
        member_id
        for (member_id,) in db.query(OrgMember.user_id).filter(
            OrgMember.org_id == business.organization.id,
        ).all()
    }
    member_ids.add(business.organization.owner_id)
    for member_id in member_ids:
        clear_active_query(member_id)
    return {"message": "Document deleted successfully"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
