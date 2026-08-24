"""Privacy-conscious structured authentication security events."""

from __future__ import annotations

import hashlib
import json
import logging


logger = logging.getLogger("hqlookup.security")


def record_auth_event(
    event: str,
    *,
    outcome: str,
    user_id: int | None = None,
    email: str | None = None,
    client_ip: str | None = None,
    identifier: str | None = None,
) -> None:
    payload: dict[str, object] = {"event": event, "outcome": outcome}
    if user_id is not None:
        payload["user_id"] = user_id
    if email:
        payload["email_hash"] = hashlib.sha256(email.strip().lower().encode()).hexdigest()[:16]
    if client_ip:
        payload["client_ip"] = client_ip
    if identifier:
        payload["identifier_hash"] = hashlib.sha256(identifier.encode()).hexdigest()[:16]
    logger.info(json.dumps(payload, separators=(",", ":"), sort_keys=True))
