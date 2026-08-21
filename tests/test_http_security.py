"""HTTP boundary regression tests."""

import asyncio
from types import SimpleNamespace

from fastapi import HTTPException
import pytest
import redis
from starlette.requests import Request
from starlette.responses import JSONResponse

from app import rate_limit
from app.security import CookieOriginMiddleware, UploadBodyLimitMiddleware


async def _downstream(scope, receive, send):
    await JSONResponse({"ok": True})(scope, receive, send)


def _request_status(
    middleware,
    *,
    origin: str | None,
    include_cookie: bool = True,
) -> int:
    headers = [(b"cookie", b"token=session")] if include_cookie else []
    if origin:
        headers.append((b"origin", origin.encode()))
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/mutate",
        "raw_path": b"/mutate",
        "query_string": b"",
        "headers": headers,
        "client": ("192.0.2.1", 1234),
        "server": ("app.example.test", 443),
    }
    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    asyncio.run(middleware(scope, receive, send))
    return next(message["status"] for message in messages if message["type"] == "http.response.start")


def test_cookie_authenticated_mutations_require_an_allowed_origin() -> None:
    middleware = CookieOriginMiddleware(
        _downstream,
        allowed_origins=("https://app.example.test",),
        cookie_names=("token",),
    )

    assert _request_status(middleware, origin=None) == 403
    assert _request_status(middleware, origin="https://app.example.test") == 200
    assert (
        _request_status(
            middleware,
            origin="https://evil.example.test",
            include_cookie=False,
        )
        == 403
    )


def test_chunked_upload_body_is_rejected_when_it_crosses_limit() -> None:
    async def consume_body(scope, receive, send):
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break
        await JSONResponse({"ok": True})(scope, receive, send)

    middleware = UploadBodyLimitMiddleware(consume_body, max_bytes=4)
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/upload-multiple",
        "raw_path": b"/upload-multiple",
        "query_string": b"",
        "headers": [],
        "client": ("192.0.2.1", 1234),
        "server": ("app.example.test", 443),
    }
    messages = []
    request_messages = iter([
        {"type": "http.request", "body": b"abc", "more_body": True},
        {"type": "http.request", "body": b"def", "more_body": False},
    ])

    async def receive():
        return next(request_messages)

    async def send(message):
        messages.append(message)

    asyncio.run(middleware(scope, receive, send))
    status = next(
        message["status"]
        for message in messages
        if message["type"] == "http.response.start"
    )
    assert status == 413


def test_chunked_webhook_body_is_rejected_when_it_crosses_limit() -> None:
    async def consume_body(scope, receive, send):
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break
        await JSONResponse({"ok": True})(scope, receive, send)

    middleware = UploadBodyLimitMiddleware(
        consume_body,
        max_bytes=4,
        path="/billing/webhook",
    )
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/billing/webhook",
        "raw_path": b"/billing/webhook",
        "query_string": b"",
        "headers": [],
        "client": ("192.0.2.1", 1234),
        "server": ("app.example.test", 443),
    }
    messages = []
    request_messages = iter([
        {"type": "http.request", "body": b"abc", "more_body": True},
        {"type": "http.request", "body": b"def", "more_body": False},
    ])

    async def receive():
        return next(request_messages)

    async def send(message):
        messages.append(message)

    asyncio.run(middleware(scope, receive, send))
    status = next(
        message["status"]
        for message in messages
        if message["type"] == "http.response.start"
    )
    assert status == 413


def test_default_body_limit_covers_public_json_routes() -> None:
    middleware = UploadBodyLimitMiddleware(
        _downstream,
        max_bytes=4,
        path_limits={"/upload-multiple": 100},
    )
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/api/auth/signup",
        "raw_path": b"/api/auth/signup",
        "query_string": b"",
        "headers": [(b"content-length", b"5")],
        "client": ("192.0.2.1", 1234),
        "server": ("app.example.test", 443),
    }
    messages = []

    async def receive():
        return {"type": "http.request", "body": b"12345", "more_body": False}

    async def send(message):
        messages.append(message)

    asyncio.run(middleware(scope, receive, send))
    assert next(
        message["status"]
        for message in messages
        if message["type"] == "http.response.start"
    ) == 413


def test_public_rate_limit_returns_retry_after(monkeypatch) -> None:
    class LimitedRedis:
        def eval(self, *_args):
            return [11, 37]

    monkeypatch.setattr(rate_limit, "redis_client", LimitedRedis())
    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/login",
        "headers": [],
        "client": ("192.0.2.1", 1234),
    })

    with pytest.raises(HTTPException) as exc_info:
        rate_limit.enforce_rate_limit(
            request,
            bucket="test",
            limit=10,
            window_seconds=60,
        )

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers == {"Retry-After": "37"}


def test_public_rate_limit_fails_closed_in_production(monkeypatch) -> None:
    class FailingRedis:
        def eval(self, *_args):
            raise redis.ConnectionError("unavailable")

    monkeypatch.setattr(rate_limit, "redis_client", FailingRedis())
    monkeypatch.setattr(rate_limit, "settings", SimpleNamespace(is_production=True))
    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/login",
        "headers": [],
        "client": ("192.0.2.1", 1234),
    })

    with pytest.raises(HTTPException) as exc_info:
        rate_limit.enforce_rate_limit(
            request,
            bucket="test",
            limit=10,
            window_seconds=60,
        )

    assert exc_info.value.status_code == 503
