"""Central organization and business authorization policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Business, Organization, OrgMember, User, user_business


ORG_ROLES = frozenset({"admin", "member"})


@dataclass(frozen=True)
class OrganizationAccess:
    organization: Organization
    membership: OrgMember | None
    is_owner: bool
    is_admin: bool


def require_organization_access(
    db: Session,
    user: User,
    org_id: int,
    *,
    admin: bool = False,
) -> OrganizationAccess:
    """Require org membership, and optionally owner/admin privileges."""

    organization = db.query(Organization).filter(Organization.id == org_id).first()
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found.")
    if not getattr(organization, "is_active", True):
        raise HTTPException(status_code=403, detail="Organization is inactive.")

    is_owner = organization.owner_id == user.id
    membership = db.query(OrgMember).filter(
        OrgMember.org_id == org_id,
        OrgMember.user_id == user.id,
    ).first()
    role = (membership.role or "").lower() if membership else ""
    is_admin = is_owner or role == "admin"

    if not is_owner and (membership is None or role not in ORG_ROLES):
        raise HTTPException(status_code=403, detail="Not authorized for this organization.")
    if admin and not is_admin:
        raise HTTPException(status_code=403, detail="Admin permissions required.")

    return OrganizationAccess(
        organization=organization,
        membership=membership,
        is_owner=is_owner,
        is_admin=is_admin,
    )


def require_business_access(
    db: Session,
    user: User,
    business_id: int,
    *,
    org_id: int | None = None,
    admin: bool = False,
) -> Business:
    """Apply the canonical tenant policy to one business.

    Organization owners and admins can access every business in their org.
    Regular members must have an explicit ``user_business`` assignment.
    """

    business = db.query(Business).filter(Business.id == business_id).first()
    if business is None or (org_id is not None and business.org_id != org_id):
        raise HTTPException(status_code=404, detail="Business not found.")

    access = require_organization_access(db, user, business.org_id, admin=admin)
    if access.is_admin:
        return business

    assignment = db.execute(
        user_business.select().where(
            user_business.c.user_id == user.id,
            user_business.c.business_id == business.id,
        )
    ).first()
    if assignment is None:
        raise HTTPException(status_code=403, detail="Not authorized for this business.")

    return business


def require_businesses_access(
    db: Session,
    user: User,
    business_ids: Iterable[int],
) -> list[Business]:
    """Authorize a set without silently dropping inaccessible IDs."""

    unique_ids = list(dict.fromkeys(business_ids))
    return [require_business_access(db, user, business_id) for business_id in unique_ids]


def get_accessible_businesses(
    db: Session,
    user: User,
    org_id: int,
) -> list[Business]:
    access = require_organization_access(db, user, org_id)
    query = db.query(Business).filter(Business.org_id == org_id)
    if access.is_admin:
        return query.all()
    return (
        query.join(user_business, Business.id == user_business.c.business_id)
        .filter(user_business.c.user_id == user.id)
        .all()
    )


def get_user_organization_ids(db: Session, user: User) -> list[int]:
    member_ids = {
        row.org_id
        for row in db.query(OrgMember).filter(OrgMember.user_id == user.id).all()
    }
    owned_ids = {
        row.id
        for row in db.query(Organization).filter(Organization.owner_id == user.id).all()
    }
    return sorted(member_ids | owned_ids)


def get_billing_owner(db: Session, organization: Organization) -> User:
    owner = db.query(User).filter(User.id == organization.owner_id).first()
    if owner is None:
        raise HTTPException(status_code=500, detail="Organization owner is unavailable.")
    return owner
