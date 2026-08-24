"""Bounded cleanup for expired authentication records."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import MfaLoginChallenge, PasswordReset, UserSession


def cleanup_expired_auth_records(db: Session) -> None:
    now = datetime.now(timezone.utc)
    db.query(UserSession).filter(UserSession.expires_at <= now).delete(synchronize_session=False)
    db.query(MfaLoginChallenge).filter(MfaLoginChallenge.expires_at <= now).delete(synchronize_session=False)
    db.query(PasswordReset).filter(PasswordReset.expires_at <= now).delete(synchronize_session=False)
    db.commit()
