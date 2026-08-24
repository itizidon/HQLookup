"""Issue hashed, expiring email-verification credentials."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import html
import secrets

from sqlalchemy.orm import Session

from app.email_outbox import enqueue_email
from app.models import EmailOutbox, User
from app.settings import settings


def verification_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def send_email_verification(user: User, db: Session) -> None:
    """Replace older credentials and atomically queue the encrypted message."""

    raw_token = secrets.token_urlsafe(32)
    db.query(EmailOutbox).filter(
        EmailOutbox.recipient == user.email,
        EmailOutbox.kind == "email_verification",
        EmailOutbox.sent_at.is_(None),
    ).delete(synchronize_session=False)
    user.email_verification_token_hash = verification_token_hash(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(
        hours=settings.email_verification_hours
    )
    user.email_verification_expires_at = expires_at
    link = f"{settings.frontend_url}/verify-email#token={raw_token}"
    safe_name = html.escape(user.name)
    safe_link = html.escape(link, quote=True)

    enqueue_email(
        db,
        recipient=user.email,
        subject="Verify your HQLookup email",
        kind="email_verification",
        expires_at=expires_at,
        html=f"""
                <h2>Verify your email</h2>
                <p>Hi {safe_name},</p>
                <p>Confirm this email address to finish creating your HQLookup account.</p>
                <p><a href="{safe_link}" style="background:#18181b;color:#fff;padding:12px 24px;text-decoration:none;border-radius:6px;font-weight:bold;display:inline-block">Verify email</a></p>
                <p>This link expires in {settings.email_verification_hours} hours.</p>
                <p style="font-size:12px;color:#666">If you did not create this account, you can ignore this email.</p>
            """,
    )
