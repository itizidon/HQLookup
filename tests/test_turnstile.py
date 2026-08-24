import json
from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from app import turnstile


class _SiteverifyResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _limit: int) -> bytes:
        return json.dumps(self.payload).encode()


def _settings():
    return SimpleNamespace(
        turnstile_secret_key="test-secret",
        is_production=True,
        frontend_url="https://app.example.test",
    )


def test_turnstile_requires_matching_action_and_hostname(monkeypatch) -> None:
    monkeypatch.setattr(turnstile, "settings", _settings())
    monkeypatch.setattr(
        turnstile,
        "urlopen",
        lambda *_args, **_kwargs: _SiteverifyResponse({
            "success": True,
            "action": "signup",
            "hostname": "app.example.test",
        }),
    )

    turnstile.verify_turnstile("valid-token", action="signup", remote_ip="192.0.2.1")

    with pytest.raises(HTTPException) as exc_info:
        turnstile.verify_turnstile("valid-token", action="login", remote_ip="192.0.2.1")

    assert exc_info.value.status_code == 400


def test_turnstile_fails_closed_when_provider_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(turnstile, "settings", _settings())

    def unavailable(*_args, **_kwargs):
        raise TimeoutError

    monkeypatch.setattr(turnstile, "urlopen", unavailable)

    with pytest.raises(HTTPException) as exc_info:
        turnstile.verify_turnstile("valid-token", action="login", remote_ip=None)

    assert exc_info.value.status_code == 503


def test_turnstile_allows_synthetic_hostname_only_for_local_test_secret(monkeypatch) -> None:
    monkeypatch.setattr(
        turnstile,
        "settings",
        SimpleNamespace(
            turnstile_secret_key="1x0000000000000000000000000000000AA",
            is_production=False,
            frontend_url="http://localhost:3000",
        ),
    )
    monkeypatch.setattr(
        turnstile,
        "urlopen",
        lambda *_args, **_kwargs: _SiteverifyResponse({
            "success": True,
            "action": "login",
            "hostname": "dummy-key-pass",
        }),
    )

    turnstile.verify_turnstile("test-token", action="login", remote_ip=None)
