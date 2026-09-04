"""Regression tests for authentication and tenant security boundaries."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import bcrypt
from fastapi import HTTPException, Response
from fastapi.exceptions import RequestValidationError
import jwt
from pydantic import ValidationError
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import main as main_app
from app.access import require_business_access
from app.auth import (
    ALGORITHM,
    create_token,
    decode_access_token,
    hash_password,
    set_jwt_cookie,
    validate_password,
    verify_password,
)
from app.database import Base
from app.models import (
    Business,
    Invitation,
    Organization,
    OrgMember,
    User,
    UserSession,
    user_business,
)
from app.settings import settings


def test_bcrypt_5_hashes_and_verifies_existing_hashes() -> None:
    password = "correct horse battery staple"
    existing_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    assert verify_password(password, existing_hash)
    assert verify_password(password, hash_password(password))
    assert not verify_password("wrong password", existing_hash)
    assert not verify_password(password, "not-a-bcrypt-hash")


def test_argon_passwords_support_long_unicode_and_enforce_bounded_length() -> None:
    password = "💥αβγ-safe-password-" * 8
    assert verify_password(password, hash_password(password))
    with pytest.raises(ValueError, match="256 characters"):
        validate_password("a" * 257)


def test_session_tokens_require_expected_registered_claims() -> None:
    token, jti, _expires_at = create_token(42, business_id=7)
    assert decode_access_token(token) == (42, 7, jti)

    now = datetime.now(timezone.utc)
    wrong_audience_token = jwt.encode(
        {
            "sub": "42",
            "iss": settings.jwt_issuer,
            "aud": "a-different-application",
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=5),
            "jti": "test-token",
            "typ": "access",
        },
        settings.jwt_secret_key,
        algorithm=ALGORITHM,
    )
    with pytest.raises(HTTPException) as exc_info:
        decode_access_token(wrong_audience_token)
    assert exc_info.value.status_code == 401


def test_session_cookie_is_http_only_and_uses_configured_name() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[User.__table__, UserSession.__table__])
    db = sessionmaker(bind=engine)()
    response = Response()
    set_jwt_cookie(response, db, 1)
    cookie = response.headers["set-cookie"]

    assert cookie.startswith(f"{settings.jwt_cookie_name}=")
    assert "HttpOnly" in cookie
    assert "Path=/" in cookie
    assert "SameSite=lax" in cookie
    assert response.headers["cache-control"] == "no-store"
    db.close()
    engine.dispose()


def test_validation_responses_do_not_echo_password_inputs() -> None:
    submitted_password = "tiny"
    with pytest.raises(ValidationError) as exc_info:
        main_app.AcceptInviteRequest(
            token="opaque-token-with-enough-random-looking-characters",
            password=submitted_password,
            name="Member",
        )

    response = asyncio.run(
        main_app.sanitized_validation_error(
            None,
            RequestValidationError(exc_info.value.errors()),
        )
    )
    assert response.status_code == 422
    assert submitted_password.encode() not in response.body


class _FakeResult:
    def __init__(self, assigned: bool) -> None:
        self.assigned = assigned

    def first(self):
        return (1,) if self.assigned else None


class _FakeQuery:
    def __init__(self, value) -> None:
        self.value = value

    def filter(self, *_conditions):
        return self

    def first(self):
        return self.value


class _AccessSession:
    def __init__(self, business, organization, membership, *, assigned=False) -> None:
        self.values = {
            Business: business,
            Organization: organization,
            OrgMember: membership,
        }
        self.assigned = assigned

    def query(self, model):
        return _FakeQuery(self.values[model])

    def execute(self, _statement):
        return _FakeResult(self.assigned)


def test_regular_members_need_explicit_business_assignment() -> None:
    user = SimpleNamespace(id=8)
    organization = SimpleNamespace(id=3, owner_id=1)
    business = SimpleNamespace(id=5, org_id=3)
    membership = SimpleNamespace(role="member")

    denied_session = _AccessSession(business, organization, membership)
    with pytest.raises(HTTPException) as exc_info:
        require_business_access(denied_session, user, business.id)
    assert exc_info.value.status_code == 403

    allowed_session = _AccessSession(
        business,
        organization,
        membership,
        assigned=True,
    )
    assert require_business_access(allowed_session, user, business.id) is business


def test_owner_and_admin_can_access_every_org_business() -> None:
    business = SimpleNamespace(id=5, org_id=3)
    organization = SimpleNamespace(id=3, owner_id=1)

    owner = SimpleNamespace(id=1)
    owner_session = _AccessSession(business, organization, None)
    assert require_business_access(owner_session, owner, business.id) is business

    admin = SimpleNamespace(id=2)
    admin_session = _AccessSession(
        business,
        organization,
        SimpleNamespace(role="admin"),
    )
    assert require_business_access(admin_session, admin, business.id) is business


def test_business_directory_exposes_role_specific_capabilities_and_allocation() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            Organization.__table__,
            OrgMember.__table__,
            Business.__table__,
            user_business,
        ],
    )
    db = sessionmaker(bind=engine)()

    try:
        owner = User(
            email="directory-owner@example.com",
            name="Directory Owner",
            hashed_password="unused-test-hash",
        )
        admin = User(
            email="directory-admin@example.com",
            name="Directory Admin",
            hashed_password="unused-test-hash",
        )
        member = User(
            email="directory-member@example.com",
            name="Directory Member",
            hashed_password="unused-test-hash",
        )
        db.add_all([owner, admin, member])
        db.flush()

        organization = Organization(name="Directory Workspace", owner_id=owner.id)
        db.add(organization)
        db.flush()

        business = Business(
            name="Directory Location",
            org_id=organization.id,
            query_allocation=137,
        )
        db.add(business)
        db.flush()

        db.add_all([
            OrgMember(org_id=organization.id, user_id=owner.id, role="admin"),
            OrgMember(org_id=organization.id, user_id=admin.id, role="admin"),
            OrgMember(org_id=organization.id, user_id=member.id, role="member"),
        ])
        member.businesses.append(business)
        db.commit()

        expected_capabilities = [
            (owner, True, True),
            (admin, False, True),
            (member, False, False),
        ]
        for user, can_edit_usage_limits, can_invite_members in expected_capabilities:
            result = main_app.get_my_businesses(
                main_app.MultiOrgBusinessesRequest(org_ids=[organization.id]),
                db=db,
                current_user=(user, None),
            )

            assert result == {
                "businesses": [
                    {
                        "id": business.id,
                        "name": business.name,
                        "org_id": organization.id,
                        "query_allocation": 137,
                        "can_edit_usage_limits": can_edit_usage_limits,
                        "can_invite_members": can_invite_members,
                    }
                ]
            }
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def invitation_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    tables = [
        User.__table__,
        Organization.__table__,
        OrgMember.__table__,
        Business.__table__,
        user_business,
        Invitation.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_invitation_token_is_database_backed_and_single_use(invitation_session) -> None:
    db = invitation_session
    owner = User(
        email="owner@example.com",
        name="Owner",
        hashed_password=hash_password("owner-password-long"),
    )
    db.add(owner)
    db.flush()
    organization = Organization(name="Workspace", owner_id=owner.id)
    db.add(organization)
    db.flush()
    business = Business(name="Location", org_id=organization.id)
    db.add(business)
    db.flush()

    raw_token = "opaque-token-with-enough-random-looking-characters"
    invitation = Invitation(
        org_id=organization.id,
        business_id=business.id,
        email="new.member@example.com",
        role="member",
        status="pending",
        token=None,
        token_hash=main_app.invitation_token_hash(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(invitation)
    db.commit()

    main_app.accept_workspace_invitation(
        main_app.AcceptInviteRequest(
            token=raw_token,
            password="member-password-long",
            name="New Member",
        ),
        db=db,
    )

    db.refresh(invitation)
    assert invitation.status == "accepted"
    assert invitation.token is None
    assert invitation.token_hash != raw_token

    with pytest.raises(HTTPException) as exc_info:
        main_app.accept_workspace_invitation(
            main_app.AcceptInviteRequest(
                token=raw_token,
                password="member-password-long",
                name="New Member",
            ),
            db=db,
        )
    assert exc_info.value.status_code == 400


def test_existing_user_must_confirm_password_to_accept_invite(invitation_session) -> None:
    db = invitation_session
    owner = User(
        email="owner-2@example.com",
        name="Owner",
        hashed_password=hash_password("owner-password-long"),
    )
    invited_user = User(
        email="member@example.com",
        name="Member",
        hashed_password=hash_password("correct-password-long"),
    )
    db.add_all([owner, invited_user])
    db.flush()
    organization = Organization(name="Workspace", owner_id=owner.id)
    db.add(organization)
    db.flush()
    business = Business(name="Location", org_id=organization.id)
    db.add(business)
    db.flush()

    raw_token = "another-opaque-token-with-enough-random-characters"
    invitation = Invitation(
        org_id=organization.id,
        business_id=business.id,
        email=invited_user.email,
        role="member",
        status="pending",
        token_hash=main_app.invitation_token_hash(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(invitation)
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        main_app.accept_workspace_invitation(
            main_app.AcceptInviteRequest(
                token=raw_token,
                password="wrong-password-long",
                name="Member",
            ),
            db=db,
        )

    db.refresh(invitation)
    assert exc_info.value.status_code == 401
    assert invitation.status == "pending"
