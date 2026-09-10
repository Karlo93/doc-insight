"""Authenticate, charge one token, then stream to the selected service."""

from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
from doc_insight.contracts.gateway import (
    BackendUnavailable,
    Identity,
    RateLimiter,
    Upstream,
)
from doc_insight.gateway.auth import Authenticator, InvalidToken
from doc_insight.gateway.responses import error, upstream_response
from doc_insight.gateway.settings import Settings
from doc_insight.observability import inject
from opentelemetry.trace import get_current_span
from starlette.requests import ClientDisconnect, Request
from starlette.responses import Response


class UploadTooLarge(Exception):
    """The declared or observed request body exceeds the configured limit."""


def check_length(request: Request, limit: int) -> None:
    """Reject ambiguous or oversized declared lengths before reading the body."""
    lengths = request.headers.getlist("content-length")
    if not lengths:
        return
    if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
        raise ValueError("Invalid content length")
    if int(lengths[0]) > limit:
        raise UploadTooLarge


async def limited_body(request: Request, limit: int) -> AsyncIterator[bytes]:
    """Enforce the byte limit even when Content-Length is absent or misleading."""
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise UploadTooLarge
        yield chunk


def forwarded_headers(request: Request, identity: Identity) -> dict[str, str]:
    """Allowlist request headers and replace identity with verified JWT claims.

    Inject the active gateway context so ordinary clients also get one connected
    trace. Caller baggage and credentials never cross the boundary.
    """
    headers = {
        name: request.headers[name]
        for name in ("content-type", "accept")
        if name in request.headers
    }
    headers.update(
        {
            "x-tenant-id": identity.tenant,
            "x-user-id": identity.user,
            "x-request-id": request.state.request_id,
            "accept-encoding": "identity",
        }
    )
    return inject(headers)


@dataclass
class Gateway:
    """Authenticate and charge per-user quota before forwarding a bounded body.

    Internal upstreams trust these identity headers and must remain private.
    This class does not authenticate service-to-service peers.
    """

    settings: Settings
    auth: Authenticator
    limiter: RateLimiter
    ingest: Upstream
    query: Upstream

    async def quota(self, identity: Identity) -> Response | int | None:
        """Return remaining quota, an error response, or None when failing open."""
        try:
            decision = await self.limiter.consume(identity)
        except BackendUnavailable:
            if self.settings.rate_limit_fail_open:
                return None
            return error(503, "rate_limit_unavailable", "rate limiter unavailable")
        if decision.allowed:
            return decision.remaining
        response = error(429, "rate_limited", "request rate exceeded")
        response.headers["retry-after"] = str(decision.retry_after)
        response.headers["x-ratelimit-remaining"] = str(decision.remaining)
        return response

    async def proxy(self, request: Request, path: str, ingest: bool) -> Response:
        """Authenticate and enforce tenant access and quota before upstream I/O."""
        try:
            authorization = request.headers.getlist("authorization")
            if len(authorization) != 1:
                raise InvalidToken
            identity = await self.auth.authenticate(authorization[0])
        except InvalidToken:
            response: Response = error(401, "unauthorized", "invalid token")
            response.headers["www-authenticate"] = "Bearer"
            return response
        if self.settings.tenants and identity.tenant not in self.settings.tenants.split(
            ","
        ):
            return error(403, "tenant_unavailable", "tenant is not provisioned")
        span = get_current_span()
        span.set_attributes({"tenant.id": identity.tenant, "user.id": identity.user})
        quota = await self.quota(identity)
        if isinstance(quota, Response):
            return quota
        response = await self.forward(request, path, ingest, identity)
        if quota is not None:
            response.headers["x-ratelimit-remaining"] = str(quota)
        return response

    async def forward(
        self, request: Request, path: str, ingest: bool, identity: Identity
    ) -> Response:
        """Stream a bounded request and translate transport failures to safe errors."""
        try:
            check_length(request, self.settings.max_upload_bytes)
            upstream = self.ingest if ingest else self.query
            reply = await upstream.exchange(
                request.method,
                path,
                forwarded_headers(request, identity),
                limited_body(request, self.settings.max_upload_bytes),
                self.settings.upstream_timeout_seconds * (4 if ingest else 1),
            )
            return upstream_response(reply)
        except UploadTooLarge:
            return error(413, "payload_too_large", "request body too large")
        except (ValueError, ClientDisconnect):
            return error(400, "invalid_request", "invalid request body")
        except (httpx.TimeoutException, TimeoutError):
            return error(504, "upstream_timeout", "upstream timed out")
        except httpx.HTTPError:
            return error(502, "bad_gateway", "upstream request failed")
