"""Centralized organization and business authorization helpers."""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Business, Organization, OrgMember, User, user_business

ADMIN_ROLES = {"admin"}
INVITABLE_ROLES = {"admin", "member"}


def require_org_access(
    db: Session,
    user: User,
    org_id: int,
    *,
    admin: bool = False,
    owner: bool = False,
) -> tuple[Organization, OrgMember]:
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")
    if not org.is_active:
        raise HTTPException(status_code=403, detail="Organization is inactive.")

    membership = db.query(OrgMember).filter(
        OrgMember.org_id == org_id,
        OrgMember.user_id == user.id,
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="Organization access denied.")

    is_owner = org.owner_id == user.id
    if owner and not is_owner:
        raise HTTPException(status_code=403, detail="Organization owner permissions required.")
    if admin and not (is_owner or membership.role in ADMIN_ROLES):
        raise HTTPException(status_code=403, detail="Organization admin permissions required.")
    return org, membership


def require_business_access(
    db: Session,
    user: User,
    business_id: int,
    *,
    admin: bool = False,
) -> tuple[Business, Organization, OrgMember]:
    business = db.query(Business).filter(Business.id == business_id).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found.")

    org, membership = require_org_access(db, user, business.org_id, admin=admin)
    is_org_admin = org.owner_id == user.id or membership.role in ADMIN_ROLES
    if not is_org_admin:
        assignment = db.execute(
            user_business.select().where(
                user_business.c.user_id == user.id,
                user_business.c.business_id == business.id,
            )
        ).first()
        if not assignment:
            raise HTTPException(status_code=403, detail="Business access denied.")
    return business, org, membership


def get_billing_owner(db: Session, org: Organization) -> User:
    owner = db.query(User).filter(User.id == org.owner_id).first()
    if not owner:
        raise HTTPException(status_code=500, detail="Organization billing owner is unavailable.")
    return owner
