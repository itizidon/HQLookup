"""Explicitly destructive development-only database seed utility."""

import os

from sqlalchemy import text

from app.auth import hash_password, validate_password
from app.database import Base, SessionLocal, engine
from app.models import Business, Organization, OrgMember, User
from app.settings import settings


def _require_development_confirmation() -> tuple[str, str]:
    if settings.app_env not in {"development", "test"}:
        raise RuntimeError("The seed utility is disabled outside development and test environments.")
    if os.getenv("ALLOW_DESTRUCTIVE_DB_RESET") != "I_UNDERSTAND":
        raise RuntimeError(
            "Set ALLOW_DESTRUCTIVE_DB_RESET=I_UNDERSTAND to confirm the destructive reset."
        )

    email = os.getenv("SEED_ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("SEED_ADMIN_PASSWORD", "")
    if not email or "@" not in email:
        raise RuntimeError("SEED_ADMIN_EMAIL must be configured.")
    try:
        validate_password(password)
    except ValueError as exc:
        raise RuntimeError("SEED_ADMIN_PASSWORD does not meet password requirements.") from exc
    return email, password


def seed() -> None:
    email, password = _require_development_confirmation()

    Base.metadata.drop_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        admin = User(
            email=email,
            name=os.getenv("SEED_ADMIN_NAME", "Development Admin").strip() or "Development Admin",
            hashed_password=hash_password(password),
            role="superadmin",
            plan="free",
        )
        db.add(admin)
        db.flush()

        organization = Organization(
            name=os.getenv("SEED_ORGANIZATION_NAME", "Development Workspace").strip()
            or "Development Workspace",
            owner_id=admin.id,
            is_active=True,
        )
        db.add(organization)
        db.flush()
        db.add(OrgMember(org_id=organization.id, user_id=admin.id, role="admin"))
        db.add(Business(
            org_id=organization.id,
            name=os.getenv("SEED_BUSINESS_NAME", "Development Location").strip()
            or "Development Location",
        ))
        db.commit()

    print("Development database reset and seeded successfully.")


if __name__ == "__main__":
    seed()
