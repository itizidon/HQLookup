"""JWT claims and cookie hardening regression tests."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException, Response
from jose import jwt
from starlette.requests import Request

from app import auth


def test_access_token_round_trip_has_typed_identity_claims() -> None:
    token = auth.create_token(user_id=42, business_id=7, expire_hours=1)

    payload = jwt.decode(
        token,
        auth.SECRET_KEY,
        algorithms=[auth.ALGORITHM],
        audience=auth.TOKEN_AUDIENCE,
        issuer=auth.TOKEN_ISSUER,
    )

    assert payload["sub"] == "42"
    assert payload["business_id"] == "7"
    assert payload["type"] == "access"
    assert payload["jti"]
    assert payload["exp"] > payload["iat"]


def test_current_user_rejects_a_non_access_token() -> None:
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": "42",
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "iss": auth.TOKEN_ISSUER,
            "aud": auth.TOKEN_AUDIENCE,
            "type": "invitation",
        },
        auth.SECRET_KEY,
        algorithm=auth.ALGORITHM,
    )
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"cookie", f"token={token}".encode())],
        }
    )

    with pytest.raises(HTTPException) as exc_info:
        auth.get_current_user(request, db=None)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid token"


def test_jwt_cookie_uses_production_security_attributes(monkeypatch) -> None:
    monkeypatch.setattr(auth.settings, "jwt_cookie_secure", True)
    monkeypatch.setattr(auth.settings, "jwt_cookie_samesite", "strict")
    monkeypatch.setattr(auth.settings, "jwt_cookie_domain", ".example.com")
    response = Response()

    auth.set_jwt_cookie(response, user_id=42)

    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=strict" in cookie
    assert "Domain=.example.com" in cookie
    assert "Path=/" in cookie
    assert f"Max-Age={auth.TOKEN_EXPIRE_H * 3600}" in cookie
