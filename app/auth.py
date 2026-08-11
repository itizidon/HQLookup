# app/auth.py
from datetime import datetime, timedelta, timezone
import uuid

from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.settings import settings

# ── CONFIG ─────────────────────────────────────────────────────────────────────
SECRET_KEY = settings.jwt_secret_key.get_secret_value()
ALGORITHM = "HS256"
TOKEN_EXPIRE_H = settings.jwt_expire_hours
TOKEN_ISSUER = "hqlookup-api"
TOKEN_AUDIENCE = "hqlookup-web"

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── UTILS ───────────────────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    validate_password(password)
    return pwd_ctx.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    if len(plain.encode("utf-8")) > 72:
        return False
    try:
        return pwd_ctx.verify(plain, hashed)
    except (TypeError, ValueError):
        return False


def validate_password(password: str) -> None:
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters long")
    if len(password.encode("utf-8")) > 72:
        raise ValueError("Password must be at most 72 UTF-8 bytes")


def create_token(user_id: int, business_id: int | None = None, expire_hours: int = TOKEN_EXPIRE_H) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(hours=expire_hours)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": expire,
        "iss": TOKEN_ISSUER,
        "aud": TOKEN_AUDIENCE,
        "jti": uuid.uuid4().hex,
        "type": "access",
    }
    if business_id is not None:
        payload["business_id"] = str(business_id)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)



def set_jwt_cookie(response: Response, user_id: int, business_id: int | None = None):
    """
    Sets a JWT cookie with both user_id and optional business_id.
    """
    token = create_token(user_id, business_id)
    response.set_cookie(
        key="token",
        value=token,
        httponly=True,
        secure=settings.jwt_cookie_secure,
        samesite=settings.jwt_cookie_samesite,
        domain=settings.jwt_cookie_domain,
        path="/",
        max_age=TOKEN_EXPIRE_H * 3600,
    )

def remove_jwt_cookie(response: Response):
    response.delete_cookie(
        "token",
        domain=settings.jwt_cookie_domain,
        path="/",
        secure=settings.jwt_cookie_secure,
        samesite=settings.jwt_cookie_samesite,
        httponly=True,
    )


# ── Get current user and optional business_id ─────────────────────
def get_current_user(request: Request, db: Session = Depends(get_db)) -> tuple[User, int | None]:
    token = request.cookies.get("token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            audience=TOKEN_AUDIENCE,
            issuer=TOKEN_ISSUER,
            options={"require_sub": True, "require_exp": True},
        )
        user_id = payload.get("sub")
        business_id = payload.get("business_id")
        if payload.get("type") != "access" or not str(user_id).isdigit():
            raise HTTPException(status_code=401, detail="Invalid token")
    except (JWTError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user, int(business_id) if business_id else None
