"""Apply public response policy even to preflight and unexpected failures."""

import re
from uuid import uuid4

from doc_insight.gateway.responses import error
from doc_insight.gateway.settings import Settings, get_settings
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class CorsPolicy:
    def __init__(self, app: ASGIApp, settings: Settings | None = None) -> None:
        settings = settings or get_settings()
        self.app = app
        if settings.cors_origins:
            self.app = CORSMiddleware(
                app,
                allow_origins=[
                    o.strip().rstrip("/")
                    for o in settings.cors_origins.split(",")
                    if o.strip()
                ],
                allow_methods=["GET", "POST"],
                allow_headers=[
                    "Authorization",
                    "Content-Type",
                    "X-Request-Id",
                    "traceparent",
                ],
                expose_headers=["X-Request-Id", "Retry-After", "X-RateLimit-Remaining"],
            )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.app(scope, receive, send)


class ResponsePolicy:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = Headers(scope=scope).get("x-request-id", "")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", request_id):
            request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        started = False

        async def send_response(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = MutableHeaders(scope=message)
                headers["cache-control"] = "no-store"
                headers["x-content-type-options"] = "nosniff"
                headers["x-request-id"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_response)
        except Exception:
            if started:
                raise
            await error(500, "internal_error", "request failed")(
                scope, receive, send_response
            )
