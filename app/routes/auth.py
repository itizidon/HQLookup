# app/routes/auth_routes.py
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import List

from app.database import get_db
from app.models import User
from app.auth import (
    hash_password,
    verify_password,
    set_jwt_cookie,
    remove_jwt_cookie,
    get_current_user,
    validate_password,
)
from app.rate_limit import enforce_rate_limit

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=12, max_length=72)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required")
        return value

    @field_validator("password")
    @classmethod
    def check_password(cls, value: str) -> str:
        validate_password(value)
        return value


class BusinessResponse(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    role: str
    businesses: List[BusinessResponse]

    model_config = {"from_attributes": True}


def build_user_response(user: User) -> UserResponse:
    return UserResponse.model_validate({
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "businesses": [
            {"id": business.id, "name": business.name}
            for business in user.businesses
        ],
    })


@router.post("/signup", response_model=UserResponse, status_code=201)
def signup(
    body: SignupRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    email = str(body.email).strip().lower()
    enforce_rate_limit(request, bucket="signup", limit=5, window_seconds=3600)
    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        name=body.name,
        email=email,
        hashed_password=hash_password(body.password),
    )

    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Email already registered") from exc
    db.refresh(user)

    set_jwt_cookie(response, user.id)

    return build_user_response(user)


@router.post("/login", response_model=UserResponse)
def login(
    request: Request,
    response: Response,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    email = form.username.strip().lower()
    enforce_rate_limit(
        request,
        bucket="login",
        limit=10,
        window_seconds=15 * 60,
        identity=email,
    )
    user = db.query(User).filter(func.lower(User.email) == email).first()

    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    set_jwt_cookie(response, user.id)

    return build_user_response(user)


@router.post("/logout")
def logout(response: Response):
    remove_jwt_cookie(response)
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
def me(current_auth=Depends(get_current_user)):
    user, _ = current_auth
    return build_user_response(user)
