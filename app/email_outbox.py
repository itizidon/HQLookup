"""Encrypted transactional email outbox and bounded retry worker."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging

from cryptography.fernet import Fernet, InvalidToken
import resend
from sqlalchemy.orm import Session

from app.models import EmailOutbox
from app.settings import settings


logger = logging.getLogger(__name__)
_cipher = Fernet(settings.data_encryption_key.encode("ascii"))
resend.api_key = settings.resend_api_key


def enqueue_email(
    db: Session,
    *,
    recipient: str,
    subject: str,
    html: str,
    kind: str,
    expires_at: datetime,
) -> None:
    encrypted_html = _cipher.encrypt(html.encode("utf-8")).decode("ascii")
    db.add(EmailOutbox(
        recipient=recipient,
        subject=subject.replace("\r", " ").replace("\n", " ")[:300],
        encrypted_html=encrypted_html,
        kind=kind[:50],
        expires_at=expires_at,
    ))


def deliver_pending_email(db: Session, *, batch_size: int = 20) -> int:
    """Deliver one locked batch; callers invoke this from a dedicated worker."""

    now = datetime.now(timezone.utc)
    db.query(EmailOutbox).filter(
        EmailOutbox.sent_at.is_(None),
        EmailOutbox.expires_at <= now,
    ).delete(synchronize_session=False)
    messages = (
        db.query(EmailOutbox)
        .filter(
            EmailOutbox.sent_at.is_(None),
            EmailOutbox.next_attempt_at <= now,
            EmailOutbox.expires_at > now,
            EmailOutbox.attempts < 10,
        )
        .order_by(EmailOutbox.id.asc())
        .with_for_update(skip_locked=True)
        .limit(batch_size)
        .all()
    )
    delivered = 0
    for message in messages:
        try:
            html = _cipher.decrypt(message.encrypted_html.encode("ascii")).decode("utf-8")
            resend.Emails.send({
                "from": settings.resend_from_email,
                "to": [message.recipient],
                "subject": message.subject,
                "html": html,
            })
            message.sent_at = datetime.now(timezone.utc)
            delivered += 1
            db.delete(message)
        except (InvalidToken, UnicodeError):
            db.delete(message)
            logger.error("Discarded an undecryptable email outbox record", extra={"outbox_id": message.id})
        except Exception:
            message.attempts += 1
            if message.attempts >= 10:
                db.delete(message)
                continue
            delay_minutes = min(2 ** message.attempts, 360)
            message.next_attempt_at = datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)
            logger.warning("Email outbox delivery failed", extra={"outbox_id": message.id, "attempt": message.attempts})
    db.commit()
    return delivered
