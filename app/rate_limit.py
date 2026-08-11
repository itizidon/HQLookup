"""Authentication rate limiting with Redis and a bounded local fallback."""

import hashlib
import logging
import threading
import time

import redis
from fastapi import HTTPException, Request

from app.settings import settings

logger = logging.getLogger(__name__)

_redis = redis.Redis.from_url(
    settings.redis_url.get_secret_value(),
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
    health_check_interval=30,
)
_fallback_lock = threading.Lock()
_fallback: dict[str, tuple[int, float]] = {}
_fallback_warning_emitted = False


def _client_key(request: Request, identity: str = "") -> str:
    client_ip = request.client.host if request.client else "unknown"
    material = f"{client_ip}|{identity.strip().lower()}".encode()
    return hashlib.sha256(material).hexdigest()


def _local_increment(key: str, window_seconds: int) -> tuple[int, int]:
    now = time.monotonic()
    with _fallback_lock:
        count, expires_at = _fallback.get(key, (0, now + window_seconds))
        if now >= expires_at:
            count, expires_at = 0, now + window_seconds
        count += 1
        _fallback[key] = (count, expires_at)

        # Prevent unbounded growth if the service is scanned continuously.
        if len(_fallback) > 10_000:
            expired = [entry for entry, (_, expiry) in _fallback.items() if now >= expiry]
            for entry in expired[:5_000]:
                _fallback.pop(entry, None)
        return count, max(1, int(expires_at - now))


def enforce_rate_limit(
    request: Request,
    *,
    bucket: str,
    limit: int,
    window_seconds: int,
    identity: str = "",
) -> None:
    global _fallback_warning_emitted

    digest = _client_key(request, identity)
    key = f"rate-limit:{bucket}:{digest}"
    try:
        pipe = _redis.pipeline(transaction=True)
        pipe.incr(key)
        pipe.ttl(key)
        count, ttl = pipe.execute()
        if ttl < 0:
            _redis.expire(key, window_seconds)
            ttl = window_seconds
    except redis.RedisError:
        if not _fallback_warning_emitted:
            logger.warning("Redis unavailable; authentication throttling is using local fallback")
            _fallback_warning_emitted = True
        count, ttl = _local_increment(key, window_seconds)

    if count > limit:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Please try again later.",
            headers={"Retry-After": str(max(1, ttl))},
        )
