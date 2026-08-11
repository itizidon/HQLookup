"""Tenant boundary tests for centralized authorization helpers."""

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.access import require_business_access
from app.models import Business, Organization, OrgMember, User, user_business


def test_member_is_limited_to_assigned_business_while_admin_is_not(
    db_session: Session,
) -> None:
    owner = User(email="owner@example.com", name="Owner", hashed_password="unused")
    member = User(email="member@example.com", name="Member", hashed_password="unused")
    admin = User(email="admin@example.com", name="Admin", hashed_password="unused")
    db_session.add_all([owner, member, admin])
    db_session.flush()

    organization = Organization(name="Workspace", owner_id=owner.id, is_active=True)
    db_session.add(organization)
    db_session.flush()
    db_session.add_all(
        [
            OrgMember(org_id=organization.id, user_id=owner.id, role="admin"),
            OrgMember(org_id=organization.id, user_id=member.id, role="member"),
            OrgMember(org_id=organization.id, user_id=admin.id, role="admin"),
        ]
    )
    assigned = Business(name="Assigned", org_id=organization.id)
    unassigned = Business(name="Unassigned", org_id=organization.id)
    db_session.add_all([assigned, unassigned])
    db_session.flush()
    db_session.execute(
        user_business.insert().values(user_id=member.id, business_id=assigned.id)
    )
    db_session.commit()

    allowed_business, _, _ = require_business_access(db_session, member, assigned.id)
    assert allowed_business.id == assigned.id

    with pytest.raises(HTTPException) as exc_info:
        require_business_access(db_session, member, unassigned.id)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Business access denied."

    admin_business, _, _ = require_business_access(db_session, admin, unassigned.id)
    assert admin_business.id == unassigned.id
