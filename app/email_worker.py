"""Run the durable email outbox worker as a separate process."""

from __future__ import annotations

import logging
import time

from app.settings import settings

settings.validate_email_worker()

from app.database import SessionLocal
from app.auth_maintenance import cleanup_expired_auth_records
from app.email_outbox import deliver_pending_email


logging.basicConfig(level=logging.INFO)


def main() -> None:
    next_cleanup = 0.0
    while True:
        db = SessionLocal()
        try:
            delivered = deliver_pending_email(db)
            if time.monotonic() >= next_cleanup:
                cleanup_expired_auth_records(db)
                next_cleanup = time.monotonic() + 3600
        except Exception:
            db.rollback()
            logging.exception("Email outbox worker iteration failed")
            delivered = 0
        finally:
            db.close()
        time.sleep(1 if delivered else 5)


if __name__ == "__main__":
    main()
