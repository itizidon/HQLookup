"""Regression tests for public signup email verification."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest
from fastapi import Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.auth import hash_password
from app.database import Base
from app.email_verification import send_email_verification
from app.models import EmailOutbox, User
from app.routes import auth as auth_routes
from app.settings import settings


PASSWORD = "A sufficiently unique signup passphrase!"
WRONG_PASSWORD = "A different unique signup passphrase!"


@pytest.fixture
def auth_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[User.__table__, EmailOutbox.__table__],
    )
    db = sessionmaker(bind=engine)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def signup_environment(monkeypatch):
    monkeypatch.setattr(
        auth_routes,
        "settings",
        replace(settings, app_env="production", public_signup_enabled=True),
    )
    monkeypatch.setattr(auth_routes, "verify_turnstile", lambda *_args, **_kwargs: None)


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/auth/signup",
            "headers": [],
            "client": ("192.0.2.1", 1234),
        }
    )


def _signup(*, password: str = PASSWORD) -> auth_routes.SignupRequest:
    return auth_routes.SignupRequest(
        name="Retry Name",
        email="Person@Example.com",
        password=password,
    )


def test_duplicate_signup_requeues_verification_for_matching_unverified_account(
    auth_session,
    signup_environment,
    monkeypatch,
) -> None:
    user = User(
        name="Original Name",
        email="person@example.com",
        hashed_password=hash_password(PASSWORD),
    )
    auth_session.add(user)
    auth_session.flush()
    send_email_verification(user, auth_session)
    auth_session.commit()

    user_id = user.id
    original_password_hash = user.hashed_password
    original_token_hash = user.email_verification_token_hash
    limited_user_ids: list[int] = []
    monkeypatch.setattr(
        auth_routes,
        "limit_verification_email",
        limited_user_ids.append,
    )

    result = auth_routes.signup(
        _signup(),
        _request(),
        Response(),
        auth_session,
    )

    auth_session.expire_all()
    refreshed_user = auth_session.get(User, user_id)
    queued_messages = auth_session.query(EmailOutbox).all()

    assert result.verification_required is True
    assert result.email == "person@example.com"
    assert limited_user_ids == [user_id]
    assert auth_session.query(User).count() == 1
    assert refreshed_user is not None
    assert refreshed_user.name == "Original Name"
    assert refreshed_user.hashed_password == original_password_hash
    assert refreshed_user.email_verification_token_hash != original_token_hash
    assert len(queued_messages) == 1
    assert queued_messages[0].recipient == "person@example.com"
    assert queued_messages[0].kind == "email_verification"


@pytest.mark.parametrize(
    ("password", "verified_at"),
    [
        (WRONG_PASSWORD, None),
        (PASSWORD, datetime.now(timezone.utc)),
    ],
    ids=["wrong-password", "verified-account"],
)
def test_duplicate_signup_does_not_requeue_without_unverified_account_password(
    auth_session,
    signup_environment,
    monkeypatch,
    password: str,
    verified_at: datetime | None,
) -> None:
    user = User(
        name="Original Name",
        email="person@example.com",
        hashed_password=hash_password(PASSWORD),
        email_verified_at=verified_at,
    )
    auth_session.add(user)
    auth_session.commit()

    monkeypatch.setattr(
        auth_routes,
        "limit_verification_email",
        lambda _user_id: pytest.fail("verification email should not be rate limited"),
    )
    monkeypatch.setattr(
        auth_routes,
        "send_email_verification",
        lambda _user, _db: pytest.fail("verification email should not be queued"),
    )

    result = auth_routes.signup(
        _signup(password=password),
        _request(),
        Response(),
        auth_session,
    )

    assert result.message == (
        "If this address can be registered, check your email for the next step."
    )
    assert result.verification_required is True
    assert auth_session.query(User).count() == 1
    assert auth_session.query(EmailOutbox).count() == 0

