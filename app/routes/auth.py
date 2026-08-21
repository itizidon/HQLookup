# app/routes/auth_routes.py
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func
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
from app.access import get_user_organization_ids, get_accessible_businesses
from app.rate_limit import limit_login, limit_login_account, limit_signup
from app.settings import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)

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
    response_model=UserResponse,
    status_code=201,
    dependencies=[Depends(limit_signup)],
)
def signup(
    body: SignupRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    if not settings.public_signup_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public signup is disabled. Use a workspace invitation.",
        )
    normalized_email = str(body.email).strip().lower()
    if db.query(User).filter(func.lower(User.email) == normalized_email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        name=body.name,
        email=normalized_email,
        hashed_password=hash_password(body.password),
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    set_jwt_cookie(response, user.id)

    return build_user_response(user, db)


@router.post(
    "/login",
    response_model=UserResponse,
    dependencies=[Depends(limit_login)],
)
def login(
    response: Response,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    normalized_email = form.username.strip().lower()
    limit_login_account(normalized_email)
    user = db.query(User).filter(func.lower(User.email) == normalized_email).first()

    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    set_jwt_cookie(response, user.id)

    return build_user_response(user, db)


@router.post("/logout")
def logout(response: Response):
    remove_jwt_cookie(response)
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
def me(
    current_auth: tuple[User, int | None] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current_user, _ = current_auth
    return build_user_response(current_user, db)
