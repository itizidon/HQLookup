"""Invitation revocation and one-time token behavior."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.main import _invite_token_digest, app
from app.models import Business, Invitation, Organization, OrgMember, User


def _workspace(db_session: Session) -> tuple[User, Organization, Business]:
    owner = User(email="owner@example.com", name="Owner", hashed_password="unused")
    db_session.add(owner)
    db_session.flush()
    organization = Organization(name="Workspace", owner_id=owner.id, is_active=True)
    db_session.add(organization)
    db_session.flush()
    db_session.add(OrgMember(org_id=organization.id, user_id=owner.id, role="admin"))
    business = Business(name="Location", org_id=organization.id)
    db_session.add(business)
    db_session.commit()
    return owner, organization, business


def test_accepted_invitation_token_cannot_be_reused(api_client, db_session: Session) -> None:
    _, organization, business = _workspace(db_session)
    invited_user = User(
        email="invitee@example.com",
        name="Invitee",
        hashed_password="already-created-account",
    )
    db_session.add(invited_user)
    raw_token = "one-time-invitation-token-with-sufficient-entropy"
    invitation = Invitation(
        org_id=organization.id,
        business_id=business.id,
        email=invited_user.email,
        role="member",
        status="pending",
        token=_invite_token_digest(raw_token),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(invitation)
    db_session.commit()

    first = api_client.post("/auth/accept-invite", json={"token": raw_token})
    second = api_client.post("/auth/accept-invite", json={"token": raw_token})

    assert first.status_code == 200
    assert second.status_code == 400
    assert "already-used" in second.json()["detail"]
    db_session.refresh(invitation)
    assert invitation.status == "accepted"
    assert invitation.token is None


def test_revoked_invitation_token_fails_verification(api_client, db_session: Session) -> None:
    owner, organization, business = _workspace(db_session)
    raw_token = "revocable-invitation-token-with-sufficient-entropy"
    invitation = Invitation(
        org_id=organization.id,
        business_id=business.id,
        email="invitee@example.com",
        role="member",
        status="pending",
        token=_invite_token_digest(raw_token),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(invitation)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: (owner, None)

    revoked = api_client.delete(
        f"/organizations/{organization.id}/invitations/{invitation.id}"
    )
    verified = api_client.get("/auth/verify-invite", params={"token": raw_token})

    assert revoked.status_code == 200
    assert verified.status_code == 400
    db_session.refresh(invitation)
    assert invitation.status == "revoked"
    assert invitation.token is None
