"""Shared, isolated test fixtures for the backend suite."""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


# Set deterministic test defaults before importing application modules. These
# clients are constructed at import time but no test makes an external call.
os.environ["APP_ENV"] = "test"
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:////tmp/hqlookup-test-import.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-with-at-least-32-characters")
os.environ.setdefault("OPENAI_API_KEY", "test-placeholder")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from app.database import Base  # noqa: E402
from app.models import (  # noqa: E402
    Business,
    Invitation,
    Organization,
    OrgMember,
    User,
    user_business,
)


TEST_TABLES = (
    User.__table__,
    Organization.__table__,
    OrgMember.__table__,
    Business.__table__,
    user_business,
    Invitation.__table__,
)


@pytest.fixture
def db_session() -> Iterator[Session]:
    """Create only the relational tables needed by the focused tests."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=TEST_TABLES)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def api_client(db_session: Session) -> Iterator:
    """Run API requests against the isolated session."""
    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.main import app

    def override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
