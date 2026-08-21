"""HTTP-level security middleware shared by the API application."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp


_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class _RequestBodyTooLarge(Exception):
    pass


class UploadBodyLimitMiddleware:
    """Reject oversized request bodies while streaming.

    The class name is retained for compatibility with existing integrations;
    ``path_limits`` allows one conservative global cap with a larger upload
    allowance for the multipart endpoint.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_bytes: int,
        path: str = "/upload-multiple",
        path_limits: dict[str, int] | None = None,
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.path = path
        self.path_limits = path_limits or {}

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = self.path_limits.get(scope.get("path"))
        if limit is None:
            if scope.get("path") != self.path:
                # ``max_bytes`` remains the default for the historical
                # single-route form of this middleware.
                if self.path_limits:
                    limit = self.max_bytes
                else:
                    await self.app(scope, receive, send)
                    return
            else:
                limit = self.max_bytes

        headers = {
            key.lower(): value
            for key, value in scope.get("headers", ())
        }
        try:
            declared_length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared_length = 0
        if declared_length > limit:
            response = JSONResponse(
                {"detail": "Upload request is too large."},
                status_code=413,
            )
            await response(scope, receive, send)
            return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _RequestBodyTooLarge:
            response = JSONResponse(
                {"detail": "Upload request is too large."},
                status_code=413,
            )
            await response(scope, receive, send)


class CookieOriginMiddleware:
    """Reject cross-origin state changes and cookie requests without Origin."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        allowed_origins: tuple[str, ...],
        cookie_names: tuple[str, ...],
    ) -> None:
        self.app = app
        self.allowed_origins = frozenset(origin.rstrip("/") for origin in allowed_origins)
        self.cookie_names = cookie_names

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        has_session = any(request.cookies.get(name) for name in self.cookie_names)
        if request.method not in _SAFE_METHODS:
            origin = (request.headers.get("origin") or "").rstrip("/")
            if (origin and origin not in self.allowed_origins) or (
                has_session and not origin
            ):
                response = JSONResponse(
                    {"detail": "Request origin is not allowed."},
                    status_code=403,
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)
