"""Authentication helpers.

Session JWTs are deliberately small and contain no authorization decision. A
business ID in a token is UI context only; every resource endpoint must resolve
authorization from the database on every request.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import unicodedata
import uuid

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
import bcrypt
from fastapi import Depends, HTTPException, Request, Response, status
import jwt
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UserSession
from app.settings import settings


ALGORITHM = "HS256"
MIN_PASSWORD_LENGTH = 15
MAX_PASSWORD_LENGTH = 256
_POSITIVE_INTEGER = re.compile(r"^[1-9][0-9]*$")
_ARGON2 = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=1, hash_len=32)
_PASSWORD_BLOCKLIST = frozenset(
    line.strip().casefold()
    for line in (Path(__file__).parent / "data" / "common_passwords.txt").read_text().splitlines()
    if line.strip() and not line.startswith("#")
)
_DUMMY_HASH = _ARGON2.hash("dummy-password-that-is-never-valid")


def validate_password(password: str) -> str:
    """Validate a password before bcrypt sees it."""

    normalized = unicodedata.normalize("NFC", password)
    if len(normalized) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
        )
    if len(normalized) > MAX_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must be at most {MAX_PASSWORD_LENGTH} characters long."
        )
    folded = normalized.casefold()
    if (
        folded in _PASSWORD_BLOCKLIST
        or "hqlookup" in folded
        or len(set(folded)) == 1
    ):
        raise ValueError("Choose a password that is not common or easily guessed.")
    return normalized


def hash_password(password: str) -> str:
    validated = validate_password(password)
    return _ARGON2.hash(validated)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify existing ``$2a$``/``$2b$`` bcrypt hashes without Passlib."""

    try:
        normalized = unicodedata.normalize("NFC", plain)
        if hashed.startswith("$argon2"):
            return _ARGON2.verify(hashed, normalized)
        if len(normalized.encode("utf-8")) > 72:
            return False
        return bcrypt.checkpw(normalized.encode("utf-8"), hashed.encode("ascii"))
    except (InvalidHashError, VerificationError, VerifyMismatchError, TypeError, ValueError, UnicodeError):
        # Treat malformed stored hashes and invalid inputs like bad credentials.
        return False


def perform_dummy_password_check(password: str) -> None:
    """Equalize unknown-account login work without exposing a valid hash."""

    verify_password(password, _DUMMY_HASH)


def password_hash_needs_upgrade(hashed: str) -> bool:
    return not hashed.startswith("$argon2") or _ARGON2.check_needs_rehash(hashed)


def create_token(
    user_id: int,
    business_id: int | None = None,
    expire_hours: int | None = None,
) -> tuple[str, str, datetime]:
    if user_id <= 0 or (business_id is not None and business_id <= 0):
        raise ValueError("Token identifiers must be positive integers.")
    now = datetime.now(timezone.utc)
    lifetime_hours = settings.jwt_expire_hours if expire_hours is None else expire_hours
    if lifetime_hours <= 0:
        raise ValueError("Token lifetime must be positive.")
    payload: dict[str, object] = {
        "sub": str(user_id),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(hours=lifetime_hours),
        "jti": uuid.uuid4().hex,
        "typ": "access",
    }
    if business_id is not None:
        payload["business_id"] = str(business_id)
    return (
        jwt.encode(payload, settings.jwt_secret_key, algorithm=ALGORITHM),
        str(payload["jti"]),
        payload["exp"],
    )


def set_jwt_cookie(
    response: Response,
    db: Session,
    user_id: int,
    business_id: int | None = None,
) -> None:
    token, jti, expires_at = create_token(user_id, business_id)
    db.add(UserSession(jti=jti, user_id=user_id, expires_at=expires_at))
    db.flush()
    response.set_cookie(
        key=settings.jwt_cookie_name,
        value=token,
        httponly=True,
        secure=settings.jwt_cookie_secure,
        samesite="lax",
        max_age=settings.jwt_expire_hours * 3600,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"


def remove_jwt_cookie(response: Response) -> None:
    response.delete_cookie(
        settings.jwt_cookie_name,
        path="/",
        secure=settings.jwt_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"


def decode_access_token(token: str) -> tuple[int, int | None, str]:
    """Validate a session token and return its typed identifiers."""

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[ALGORITHM],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={
                "require": ["sub", "exp", "iat", "nbf", "iss", "aud", "jti"],
            },
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        ) from exc

    subject = payload.get("sub")
    if payload.get("typ") != "access" or not isinstance(subject, str):
        raise HTTPException(status_code=401, detail="Invalid session")
    if len(subject) > 20 or not _POSITIVE_INTEGER.fullmatch(subject):
        raise HTTPException(status_code=401, detail="Invalid session")

    business_claim = payload.get("business_id")
    if business_claim is None:
        business_id = None
    elif (
        isinstance(business_claim, str)
        and len(business_claim) <= 20
        and _POSITIVE_INTEGER.fullmatch(business_claim)
    ):
        business_id = int(business_claim)
    else:
        raise HTTPException(status_code=401, detail="Invalid session")

    jti = payload.get("jti")
    if not isinstance(jti, str) or not re.fullmatch(r"[0-9a-f]{32}", jti):
        raise HTTPException(status_code=401, detail="Invalid session")
    return int(subject), business_id, jti


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> tuple[User, int | None]:
    token = request.cookies.get(settings.jwt_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_id, business_id, jti = decode_access_token(token)
    now = datetime.now(timezone.utc)
    session = db.query(UserSession).filter(
        UserSession.jti == jti,
        UserSession.user_id == user_id,
        UserSession.revoked_at.is_(None),
        UserSession.expires_at > now,
    ).first()
    if session is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user, business_id
