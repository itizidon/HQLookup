# app/routes/auth_routes.py
from datetime import datetime, timedelta, timezone
import html
import secrets
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import List

from app.database import get_db
from app.models import EmailOutbox, MfaLoginChallenge, PasswordReset, User, UserSession
from app.auth import (
    hash_password,
    verify_password,
    set_jwt_cookie,
    remove_jwt_cookie,
    get_current_user,
    validate_password,
    decode_access_token,
    password_hash_needs_upgrade,
    perform_dummy_password_check,
    MIN_PASSWORD_LENGTH,
)
from app.access import get_user_organization_ids, get_accessible_businesses
from app.email_verification import (
    send_email_verification,
    verification_token_hash,
)
from app.email_outbox import enqueue_email
from app.mfa import (
    consume_recovery_code,
    create_mfa_challenge,
    decode_mfa_challenge,
    encrypt_secret,
    generate_recovery_codes,
    provisioning_uri,
    verify_totp,
)
from app.rate_limit import (
    limit_login,
    limit_login_account,
    limit_email_verify,
    limit_mfa_attempt,
    limit_password_reset,
    limit_password_reset_account,
    limit_signup,
    limit_verification_email,
)
from app.settings import settings
from app.security_events import record_auth_event
from app.turnstile import verify_turnstile
import jwt
import pyotp

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)
    turnstile_token: str = Field(default="", alias="turnstileToken", max_length=2048)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required.")
        return value

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, value: str) -> str:
        return validate_password(value)


class BusinessResponse(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


class SignupResponse(BaseModel):
    message: str
    email: str
    verification_required: bool


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=32, max_length=512)


class PasswordResetRequest(BaseModel):
    email: EmailStr
    turnstile_token: str = Field(default="", alias="turnstileToken", max_length=2048)


class PasswordResetComplete(BaseModel):
    token: str = Field(min_length=32, max_length=512)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)
    turnstile_token: str = Field(default="", alias="turnstileToken", max_length=2048)

    @field_validator("password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        return validate_password(value)


class MfaCodeRequest(BaseModel):
    challenge: str = Field(min_length=32, max_length=4096)
    code: str = Field(min_length=6, max_length=32)


class MfaEnableRequest(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class MfaSetupRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class MfaDisableRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    code: str = Field(min_length=6, max_length=32)


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    role: str
    businesses: List[BusinessResponse]

    model_config = {"from_attributes": True}


def build_user_response(user: User, db: Session) -> UserResponse:
    businesses_by_id = {}
    for org_id in get_user_organization_ids(db, user):
        for business in get_accessible_businesses(db, user, org_id):
            businesses_by_id[business.id] = business

    return UserResponse.model_validate({
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "businesses": [
            {"id": business.id, "name": business.name}
            for business in businesses_by_id.values()
        ],
    })


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=201,
    dependencies=[Depends(limit_signup)],
)
def signup(
    body: SignupRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    if not settings.public_signup_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public signup is disabled. Use a workspace invitation.",
        )
    verify_turnstile(
        body.turnstile_token,
        action="signup",
        remote_ip=request.client.host if request.client else None,
    )
    normalized_email = str(body.email).strip().lower()
    existing_user = db.query(User).filter(func.lower(User.email) == normalized_email).first()
    if existing_user:
        # Registration responses do not disclose whether an identity exists.
        perform_dummy_password_check(body.password)
        return SignupResponse(
            message="If this address can be registered, check your email for the next step.",
            email=normalized_email,
            verification_required=True,
        )

    user = User(
        name=body.name,
        email=normalized_email,
        hashed_password=hash_password(body.password),
    )

    db.add(user)
    verification_required = settings.is_production
    try:
        db.flush()
        if verification_required:
            send_email_verification(user, db)
        else:
            user.email_verified_at = datetime.now(timezone.utc)
            set_jwt_cookie(response, db, user.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        return SignupResponse(
            message="If this address can be registered, check your email for the next step.",
            email=normalized_email,
            verification_required=True,
        )

    record_auth_event(
        "signup",
        outcome="verification_queued" if verification_required else "success",
        user_id=user.id,
        client_ip=request.client.host if request.client else None,
    )
    return SignupResponse(
        message=(
            "Check your email to finish creating your account."
            if verification_required
            else "Account created."
        ),
        email=normalized_email,
        verification_required=verification_required,
    )


@router.post(
    "/login",
    dependencies=[Depends(limit_login)],
)
def login(
    request: Request,
    response: Response,
    form: OAuth2PasswordRequestForm = Depends(),
    turnstile_token: str = Form(default="", alias="cf-turnstile-response"),
    db: Session = Depends(get_db),
):
    verify_turnstile(
        turnstile_token,
        action="login",
        remote_ip=request.client.host if request.client else None,
    )
    normalized_email = form.username.strip().lower()
    limit_login_account(normalized_email)
    user = db.query(User).filter(func.lower(User.email) == normalized_email).first()

    if user is None:
        perform_dummy_password_check(form.password)
    if not user or not verify_password(form.password, user.hashed_password):
        record_auth_event("login", outcome="failure", email=normalized_email, client_ip=request.client.host if request.client else None)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if user.email_verified_at is None:
        limit_verification_email(user.id)
        try:
            send_email_verification(user, db)
            db.commit()
        except Exception:
            db.rollback()
            raise HTTPException(
                status_code=503,
                detail="We could not queue the verification email. Try again later.",
            ) from None
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. We sent you a new verification link.",
        )

    if password_hash_needs_upgrade(user.hashed_password):
        user.hashed_password = hash_password(form.password)
    if user.mfa_enabled_at is not None and user.mfa_secret_encrypted:
        challenge, challenge_jti, challenge_expires = create_mfa_challenge(user.id)
        db.add(MfaLoginChallenge(
            jti=challenge_jti,
            user_id=user.id,
            expires_at=challenge_expires,
        ))
        db.commit()
        record_auth_event("login_password", outcome="mfa_required", user_id=user.id, client_ip=request.client.host if request.client else None)
        return {"mfa_required": True, "challenge": challenge}
    set_jwt_cookie(response, db, user.id)
    db.commit()
    record_auth_event("login", outcome="success", user_id=user.id, client_ip=request.client.host if request.client else None)

    return build_user_response(user, db)


@router.post(
    "/verify-email",
    dependencies=[Depends(limit_email_verify)],
)
def verify_email(
    body: VerifyEmailRequest,
    db: Session = Depends(get_db),
):
    token_hash = verification_token_hash(body.token)
    now = datetime.now(timezone.utc)
    user = (
        db.query(User)
        .filter(
            User.email_verification_token_hash == token_hash,
            User.email_verification_expires_at > now,
        )
        .with_for_update()
        .first()
    )
    if user is None:
        raise HTTPException(status_code=400, detail="This verification link is invalid or expired.")

    user.email_verified_at = now
    user.email_verification_token_hash = None
    user.email_verification_expires_at = None
    db.commit()
    record_auth_event("email_verification", outcome="success", user_id=user.id)
    return {"message": "Email verified. Sign in to continue."}


@router.post("/request-password-reset", dependencies=[Depends(limit_password_reset)])
def request_password_reset(
    body: PasswordResetRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    verify_turnstile(
        body.turnstile_token,
        action="password_reset_request",
        remote_ip=request.client.host if request.client else None,
    )
    email = str(body.email).strip().lower()
    limit_password_reset_account(email)
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if user:
        try:
            db.query(PasswordReset).filter(PasswordReset.user_id == user.id).delete()
            db.query(EmailOutbox).filter(
                EmailOutbox.recipient == user.email,
                EmailOutbox.kind == "password_reset",
                EmailOutbox.sent_at.is_(None),
            ).delete(synchronize_session=False)
            raw_token = secrets.token_urlsafe(32)
            reset_expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.password_reset_hours)
            db.add(PasswordReset(
                user_id=user.id,
                token_hash=verification_token_hash(raw_token),
                expires_at=reset_expires_at,
            ))
            safe_link = html.escape(f"{settings.frontend_url}/reset-password#token={raw_token}", quote=True)
            enqueue_email(
                db,
                recipient=user.email,
                subject="Reset your HQLookup password",
                kind="password_reset",
                expires_at=reset_expires_at,
                html=f"""
                    <h2>Reset your password</h2>
                    <p><a href="{safe_link}">Choose a new password</a></p>
                    <p>This link expires in {settings.password_reset_hours} hour(s). If you did not request it, ignore this email.</p>
                """,
            )
            db.commit()
        except Exception:
            db.rollback()
            record_auth_event("password_reset_request", outcome="queue_failure", user_id=user.id)
    else:
        perform_dummy_password_check("dummy-password-that-is-never-valid")
    record_auth_event("password_reset_request", outcome="accepted", email=email, client_ip=request.client.host if request.client else None)
    return {"message": "If that account exists, a reset link will be sent."}


@router.post("/reset-password", dependencies=[Depends(limit_password_reset)])
def reset_password(
    body: PasswordResetComplete,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    verify_turnstile(
        body.turnstile_token,
        action="password_reset",
        remote_ip=request.client.host if request.client else None,
    )
    now = datetime.now(timezone.utc)
    reset = (
        db.query(PasswordReset)
        .filter(
            PasswordReset.token_hash == verification_token_hash(body.token),
            PasswordReset.expires_at > now,
        )
        .with_for_update()
        .first()
    )
    if reset is None:
        raise HTTPException(status_code=400, detail="This reset link is invalid or expired.")
    user = db.query(User).filter(User.id == reset.user_id).with_for_update().first()
    if user is None:
        raise HTTPException(status_code=400, detail="This reset link is invalid or expired.")
    user.hashed_password = hash_password(body.password)
    user.email_verified_at = user.email_verified_at or now
    db.query(UserSession).filter(UserSession.user_id == user.id, UserSession.revoked_at.is_(None)).update({"revoked_at": now})
    db.delete(reset)
    db.commit()
    remove_jwt_cookie(response)
    record_auth_event("password_reset", outcome="success", user_id=user.id, client_ip=request.client.host if request.client else None)
    return {"message": "Password changed. Sign in with your new password."}


@router.post("/mfa/complete", response_model=UserResponse)
def complete_mfa(body: MfaCodeRequest, response: Response, db: Session = Depends(get_db)):
    try:
        user_id, challenge_jti = decode_mfa_challenge(body.challenge)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="MFA challenge is invalid or expired.") from None
    limit_mfa_attempt(user_id)
    now = datetime.now(timezone.utc)
    challenge = (
        db.query(MfaLoginChallenge)
        .filter(
            MfaLoginChallenge.jti == challenge_jti,
            MfaLoginChallenge.user_id == user_id,
            MfaLoginChallenge.expires_at > now,
        )
        .with_for_update()
        .first()
    )
    if challenge is None:
        raise HTTPException(status_code=401, detail="MFA challenge is invalid or expired.")
    user = db.query(User).filter(User.id == user_id).with_for_update().first()
    if user is None or not user.mfa_secret_encrypted or user.mfa_enabled_at is None:
        raise HTTPException(status_code=401, detail="MFA challenge is invalid or expired.")
    matched_counter = verify_totp(
        user.mfa_secret_encrypted,
        body.code,
        last_counter=user.mfa_last_counter,
    )
    valid = matched_counter is not None
    if not valid:
        valid, updated_hashes = consume_recovery_code(user.mfa_recovery_code_hashes, body.code)
        if valid:
            user.mfa_recovery_code_hashes = updated_hashes
    if not valid:
        record_auth_event("mfa", outcome="failure", user_id=user.id)
        raise HTTPException(status_code=401, detail="Invalid authentication code.")
    if matched_counter is not None:
        user.mfa_last_counter = matched_counter
    db.delete(challenge)
    set_jwt_cookie(response, db, user.id)
    db.commit()
    record_auth_event("mfa", outcome="success", user_id=user.id)
    return build_user_response(user, db)


@router.post("/mfa/setup")
def setup_mfa(
    body: MfaSetupRequest,
    response: Response,
    current_auth: tuple[User, int | None] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user, _ = current_auth
    if user.mfa_enabled_at is not None:
        raise HTTPException(status_code=409, detail="MFA is already enabled.")
    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    secret = pyotp.random_base32()
    user.mfa_secret_encrypted = encrypt_secret(secret)
    user.mfa_enabled_at = None
    user.mfa_recovery_code_hashes = None
    user.mfa_last_counter = None
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"secret": secret, "provisioning_uri": provisioning_uri(secret, user.email)}


@router.get("/mfa/status")
def mfa_status(current_auth: tuple[User, int | None] = Depends(get_current_user)):
    user, _ = current_auth
    return {"enabled": user.mfa_enabled_at is not None}


@router.post("/mfa/enable")
def enable_mfa(
    body: MfaEnableRequest,
    response: Response,
    current_auth: tuple[User, int | None] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user, _ = current_auth
    matched_counter = (
        verify_totp(user.mfa_secret_encrypted, body.code)
        if user.mfa_secret_encrypted
        else None
    )
    if matched_counter is None:
        raise HTTPException(status_code=400, detail="Invalid authentication code.")
    codes, serialized_hashes = generate_recovery_codes()
    user.mfa_recovery_code_hashes = serialized_hashes
    user.mfa_enabled_at = datetime.now(timezone.utc)
    user.mfa_last_counter = matched_counter
    db.query(UserSession).filter(
        UserSession.user_id == user.id,
        UserSession.revoked_at.is_(None),
    ).update({"revoked_at": datetime.now(timezone.utc)})
    db.commit()
    remove_jwt_cookie(response)
    record_auth_event("mfa_enable", outcome="success", user_id=user.id)
    return {"recovery_codes": codes}


@router.post("/mfa/disable")
def disable_mfa(
    body: MfaDisableRequest,
    response: Response,
    current_auth: tuple[User, int | None] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user, _ = current_auth
    if not verify_password(body.password, user.hashed_password) or not user.mfa_secret_encrypted:
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    matched_counter = verify_totp(
        user.mfa_secret_encrypted,
        body.code,
        last_counter=user.mfa_last_counter,
    )
    valid = matched_counter is not None
    if not valid:
        valid, updated_hashes = consume_recovery_code(user.mfa_recovery_code_hashes, body.code)
        if valid:
            user.mfa_recovery_code_hashes = updated_hashes
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    user.mfa_secret_encrypted = None
    user.mfa_recovery_code_hashes = None
    user.mfa_enabled_at = None
    user.mfa_last_counter = None
    db.query(UserSession).filter(
        UserSession.user_id == user.id,
        UserSession.revoked_at.is_(None),
    ).update({"revoked_at": datetime.now(timezone.utc)})
    db.commit()
    remove_jwt_cookie(response)
    record_auth_event("mfa_disable", outcome="success", user_id=user.id)
    return {"message": "MFA disabled."}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(settings.jwt_cookie_name)
    if token:
        try:
            _user_id, _business_id, jti = decode_access_token(token)
            session = db.query(UserSession).filter(UserSession.jti == jti).first()
            if session and session.revoked_at is None:
                session.revoked_at = datetime.now(timezone.utc)
                db.commit()
        except HTTPException:
            db.rollback()
    remove_jwt_cookie(response)
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
def me(
    current_auth: tuple[User, int | None] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current_user, _ = current_auth
    return build_user_response(current_user, db)
