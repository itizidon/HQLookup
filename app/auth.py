# app/auth.py
from datetime import datetime, timedelta
import os

from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User

# ── CONFIG ─────────────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "CHANGE_THIS_TO_A_LONG_RANDOM_STRING_IN_PRODUCTION")
ALGORITHM = "HS256"
TOKEN_EXPIRE_H = 24 * 7  # 1 week
JWT_COOKIE_SECURE = os.environ.get("JWT_COOKIE_SECURE", "false").lower() == "true"

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── UTILS ───────────────────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    password = password[:72]  # truncate
    return pwd_ctx.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)


def create_token(user_id: int, business_id: int | None = None, expire_hours: int = TOKEN_EXPIRE_H) -> str:
    expire = datetime.utcnow() + timedelta(hours=expire_hours)
    payload = {
        "sub": str(user_id),
        "exp": expire,
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
        secure=JWT_COOKIE_SECURE,  # only True if using HTTPS in production
        samesite="lax",
        max_age=TOKEN_EXPIRE_H * 3600,
    )

def remove_jwt_cookie(response: Response):
    response.delete_cookie("token")


# ── Get current user and optional business_id ─────────────────────
def get_current_user(request: Request, db: Session = Depends(get_db)) -> tuple[User, int | None]:
    token = request.cookies.get("token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        business_id = payload.get("business_id")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user, int(business_id) if business_id else None
