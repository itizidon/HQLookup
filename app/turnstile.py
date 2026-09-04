"""Cloudflare Turnstile server-side verification."""

from __future__ import annotations

import json
import logging
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
import uuid

from fastapi import HTTPException

from app.settings import settings


logger = logging.getLogger(__name__)
SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
_TEST_SECRETS = {
    "1x0000000000000000000000000000000AA",
    "2x0000000000000000000000000000000AA",
    "3x0000000000000000000000000000000AA",
}


def verify_turnstile(token: str, *, action: str, remote_ip: str | None) -> None:
    """Fail closed unless Cloudflare confirms this exact form interaction."""

    secret = settings.turnstile_secret_key
    if not secret and not settings.is_production:
        return
    if not secret:
        raise HTTPException(status_code=503, detail="Human verification is unavailable.")
    if not token or len(token) > 2048:
        raise HTTPException(status_code=400, detail="Complete the human verification challenge.")

    payload = {
        "secret": secret,
        "response": token,
        "idempotency_key": str(uuid.uuid4()),
    }
    if remote_ip:
        payload["remoteip"] = remote_ip

    request = Request(
        SITEVERIFY_URL,
        data=urlencode(payload).encode("ascii"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=5) as response:  # noqa: S310 - fixed HTTPS origin
            result = json.loads(response.read(16_384))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
        logger.error("Cloudflare Turnstile verification was unavailable")
        raise HTTPException(
            status_code=503,
            detail="Human verification is temporarily unavailable. Try again.",
        ) from None

    expected_hostname = urlparse(settings.frontend_url).hostname
    hostname_matches = (
        isinstance(result, dict)
        and bool(expected_hostname)
        and str(result.get("hostname", "")).rstrip(".").lower()
        == expected_hostname.rstrip(".").lower()
    )
    # Cloudflare's documented test credentials return placeholder metadata and
    # can omit ``action`` entirely. They are useful locally, while Settings
    # rejects every test secret in production so this exception cannot weaken
    # deployed action or hostname checks.
    test_credential = not settings.is_production and secret in _TEST_SECRETS
    metadata_matches = test_credential or (
        isinstance(result, dict)
        and result.get("action") == action
        and hostname_matches
    )
    if (
        not isinstance(result, dict)
        or result.get("success") is not True
        or not metadata_matches
    ):
        raise HTTPException(
            status_code=400,
            detail="Human verification failed. Please try again.",
        )
