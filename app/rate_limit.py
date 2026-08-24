"""Small Redis-backed fixed-window limits for unauthenticated endpoints."""

from __future__ import annotations

import hashlib
import logging

from fastapi import HTTPException, Request
import redis

from app.settings import settings
from app.security_events import record_auth_event


logger = logging.getLogger(__name__)

_RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""

redis_client = redis.Redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)


def _client_identifier(request: Request) -> str:
    # ``request.client`` is populated by the ASGI server. Configure Uvicorn's
    # trusted proxy list at deployment time; never trust a raw X-Forwarded-For
    # header here.
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(
    request: Request,
    *,
    bucket: str,
    limit: int,
    window_seconds: int,
) -> None:
    enforce_identifier_rate_limit(
        _client_identifier(request),
        bucket=bucket,
        limit=limit,
        window_seconds=window_seconds,
    )


def enforce_identifier_rate_limit(
    identifier: str,
    *,
    bucket: str,
    limit: int,
    window_seconds: int,
) -> None:
    identifier_hash = hashlib.sha256(identifier.encode()).hexdigest()[:32]
    key = f"rate-limit:{bucket}:{identifier_hash}"
    try:
        current, ttl = redis_client.eval(
            _RATE_LIMIT_SCRIPT,
            1,
            key,
            window_seconds,
        )
    except redis.RedisError as exc:
        if settings.is_production:
            raise HTTPException(
                status_code=503,
                detail="Request protection service is temporarily unavailable.",
            ) from exc
        logger.warning("Rate limiting unavailable in non-production environment")
        return

    if int(current) > limit:
        retry_after = max(int(ttl), 1)
        record_auth_event(
            "rate_limit",
            outcome=f"blocked:{bucket}",
            identifier=identifier,
        )
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )


def limit_login(request: Request) -> None:
    enforce_rate_limit(request, bucket="login", limit=10, window_seconds=60)


def limit_login_account(email: str) -> None:
    """Apply a distributed limiter to the normalized account identifier too."""

    enforce_identifier_rate_limit(
        email.strip().lower(),
        bucket="login-account",
        limit=10,
        window_seconds=60,
    )


def limit_signup(request: Request) -> None:
    enforce_rate_limit(request, bucket="signup", limit=5, window_seconds=3600)


def limit_verification_email(user_id: int) -> None:
    enforce_identifier_rate_limit(
        str(user_id),
        bucket="verification-email",
        limit=3,
        window_seconds=3600,
    )


def limit_email_verify(request: Request) -> None:
    enforce_rate_limit(request, bucket="email-verify", limit=10, window_seconds=3600)


def limit_password_reset(request: Request) -> None:
    enforce_rate_limit(request, bucket="password-reset", limit=5, window_seconds=3600)


def limit_password_reset_account(email: str) -> None:
    enforce_identifier_rate_limit(email, bucket="password-reset-account", limit=3, window_seconds=3600)


def limit_mfa_attempt(user_id: int) -> None:
    enforce_identifier_rate_limit(str(user_id), bucket="mfa", limit=10, window_seconds=600)


def limit_invite_verify(request: Request) -> None:
    enforce_rate_limit(request, bucket="invite-verify", limit=20, window_seconds=60)


def limit_invite_accept(request: Request) -> None:
    enforce_rate_limit(request, bucket="invite-accept", limit=10, window_seconds=3600)


def limit_invite_send(user_id: int, org_id: int) -> None:
    enforce_identifier_rate_limit(
        f"{user_id}:{org_id}",
        bucket="invite-send",
        limit=20,
        window_seconds=3600,
    )


def limit_billing(user_id: int) -> None:
    enforce_identifier_rate_limit(
        str(user_id),
        bucket="billing",
        limit=20,
        window_seconds=3600,
    )


def limit_document_upload(user_id: int) -> None:
    enforce_identifier_rate_limit(
        str(user_id),
        bucket="document-upload",
        limit=10,
        window_seconds=3600,
    )


def limit_search(user_id: int) -> None:
    enforce_identifier_rate_limit(
        str(user_id),
        bucket="search",
        limit=30,
        window_seconds=60,
    )
