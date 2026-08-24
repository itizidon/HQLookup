"""Explicit development-only database reset and seed utility."""

from __future__ import annotations

import os

from sqlalchemy import text

from app.settings import settings

settings.validate_database()

from app.auth import hash_password
from datetime import datetime, timezone
from app.database import Base, SessionLocal, engine
from app.models import Business, Organization, OrgMember, User


def _required_seed_password(name: str) -> str:
    value = os.getenv(name, "")
    if len(value) < 15:
        raise RuntimeError(f"{name} must contain at least 15 characters")
    return value


def _assert_destructive_seed_allowed() -> None:
    if settings.app_env not in {"development", "test"}:
        raise RuntimeError("Database seeding is disabled outside development and test")
    if os.getenv("ALLOW_DESTRUCTIVE_DB_RESET") != "I_UNDERSTAND":
        raise RuntimeError(
            "Set ALLOW_DESTRUCTIVE_DB_RESET=I_UNDERSTAND to confirm the reset"
        )


def reset_schema() -> None:
    _assert_destructive_seed_allowed()
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)


def seed() -> None:
    """Reset and create opt-in development accounts without logging passwords."""

    reset_schema()
    account_specs = (
        ("SEED_ADMIN_PASSWORD", "admin@example.com", "Development Admin", "admin"),
        ("SEED_OWNER_PASSWORD", "owner@example.com", "Development Owner", "user"),
        ("SEED_USER_PASSWORD", "user@example.com", "Development User", "user"),
    )

    db = SessionLocal()
    try:
        users = []
        for password_name, email, name, role in account_specs:
            user = User(
                email=email,
                name=name,
                role=role,
                hashed_password=hash_password(_required_seed_password(password_name)),
                email_verified_at=datetime.now(timezone.utc),
            )
            db.add(user)
            users.append(user)
        db.flush()

        organization = Organization(
            name="Development Workspace",
            owner_id=users[1].id,
            is_active=True,
        )
        db.add(organization)
        db.flush()

        for user in users:
            db.add(
                OrgMember(
                    org_id=organization.id,
                    user_id=user.id,
                    role="admin" if user in users[:2] else "member",
                )
            )

        businesses = [
            Business(name="Development Location A", org_id=organization.id),
            Business(name="Development Location B", org_id=organization.id),
        ]
        db.add_all(businesses)
        db.flush()
        users[2].businesses.append(businesses[0])
        db.commit()
        print("Development seed completed; credentials were not logged.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
