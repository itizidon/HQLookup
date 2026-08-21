"""Authentication helpers.

Session JWTs are deliberately small and contain no authorization decision. A
business ID in a token is UI context only; every resource endpoint must resolve
authorization from the database on every request.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
import uuid

import bcrypt
from fastapi import Depends, HTTPException, Request, Response, status
import jwt
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.settings import settings


ALGORITHM = "HS256"
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72
_POSITIVE_INTEGER = re.compile(r"^[1-9][0-9]*$")


def validate_password(password: str) -> str:
    """Validate a password before bcrypt sees it."""

    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
        )
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(
            f"Password must be at most {MAX_PASSWORD_BYTES} UTF-8 bytes."
        )
    return password


def hash_password(password: str) -> str:
    validated = validate_password(password)
    return bcrypt.hashpw(validated.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify existing ``$2a$``/``$2b$`` bcrypt hashes without Passlib."""

    try:
        if len(plain.encode("utf-8")) > MAX_PASSWORD_BYTES:
            return False
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
    except (TypeError, ValueError, UnicodeError):
        # Treat malformed stored hashes and invalid inputs like bad credentials.
        return False


def create_token(
    user_id: int,
    business_id: int | None = None,
    expire_hours: int | None = None,
) -> str:
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
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=ALGORITHM)


def set_jwt_cookie(
    response: Response,
    user_id: int,
    business_id: int | None = None,
) -> None:
    token = create_token(user_id, business_id)
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


def decode_access_token(token: str) -> tuple[int, int | None]:
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

    return int(subject), business_id


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> tuple[User, int | None]:
    token = request.cookies.get(settings.jwt_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_id, business_id = decode_access_token(token)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user, business_id
