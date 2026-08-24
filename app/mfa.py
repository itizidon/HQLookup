"""TOTP MFA secrets, short-lived login challenges, and recovery codes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import secrets

from cryptography.fernet import Fernet
import jwt
import pyotp

from app.settings import settings


_cipher = Fernet(settings.data_encryption_key.encode("ascii"))


def encrypt_secret(secret: str) -> str:
    return _cipher.encrypt(secret.encode("ascii")).decode("ascii")


def decrypt_secret(encrypted: str) -> str:
    return _cipher.decrypt(encrypted.encode("ascii")).decode("ascii")


def verify_totp(
    encrypted_secret: str,
    code: str,
    *,
    last_counter: int | None = None,
) -> int | None:
    totp = pyotp.TOTP(decrypt_secret(encrypted_secret))
    current = totp.timecode(datetime.now(timezone.utc))
    for counter in (current - 1, current, current + 1):
        if (last_counter is None or counter > last_counter) and hmac.compare_digest(
            totp.generate_otp(counter), code.strip()
        ):
            return counter
    return None


def provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=settings.mfa_issuer)


def _recovery_hash(code: str) -> str:
    return hmac.new(
        settings.jwt_secret_key.encode(),
        code.strip().lower().encode(),
        hashlib.sha256,
    ).hexdigest()


def generate_recovery_codes() -> tuple[list[str], str]:
    codes = [f"{secrets.token_hex(4)}-{secrets.token_hex(4)}" for _ in range(10)]
    return codes, json.dumps([_recovery_hash(code) for code in codes])


def consume_recovery_code(serialized_hashes: str | None, code: str) -> tuple[bool, str | None]:
    try:
        hashes = json.loads(serialized_hashes or "[]")
    except json.JSONDecodeError:
        return False, serialized_hashes
    candidate = _recovery_hash(code)
    for index, stored in enumerate(hashes):
        if isinstance(stored, str) and hmac.compare_digest(stored, candidate):
            hashes.pop(index)
            return True, json.dumps(hashes)
    return False, serialized_hashes


def create_mfa_challenge(user_id: int) -> tuple[str, str, datetime]:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=5)
    jti = secrets.token_hex(16)
    token = jwt.encode({
        "sub": str(user_id),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "nbf": now,
        "exp": expires_at,
        "jti": jti,
        "typ": "mfa_challenge",
    }, settings.jwt_secret_key, algorithm="HS256")
    return token, jti, expires_at


def decode_mfa_challenge(token: str) -> tuple[int, str]:
    payload = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=["HS256"],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
        options={"require": ["sub", "exp", "iat", "nbf", "jti"]},
    )
    if payload.get("typ") != "mfa_challenge" or not str(payload.get("sub", "")).isdigit():
        raise jwt.InvalidTokenError
    jti = payload.get("jti")
    if not isinstance(jti, str) or len(jti) != 32:
        raise jwt.InvalidTokenError
    return int(payload["sub"]), jti
