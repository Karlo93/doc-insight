"""HTTP adapters reuse one client and never buffer incoming uploads."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from doc_insight.contracts.gateway import UpstreamReply


@asynccontextmanager
async def stream(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    timeout: float,
    headers: dict[str, str] | None = None,
    body: AsyncIterator[bytes] | None = None,
) -> AsyncIterator[httpx.Response]:
    """Own response cleanup while streaming a request through the shared client."""
    request = client.build_request(
        method, url, timeout=timeout, headers=headers, content=body
    )
    # A shared client must never replay an upstream session cookie across identities.
    request.headers.pop("cookie", None)
    response = await client.send(request, stream=True, follow_redirects=False)
    try:
        yield response
    finally:
        await response.aclose()


async def bounded_read(response: httpx.Response, limit: int) -> bytes:
    """Bound decoded response bytes, including compressed upstream responses."""
    result = bytearray()
    async for chunk in response.aiter_bytes():
        if len(result) + len(chunk) > limit:
            raise ValueError("Response too large")
        result.extend(chunk)
    return bytes(result)


class HttpJwksSource:
    def __init__(self, client: httpx.AsyncClient, url: str) -> None:
        self.client, self.url = client, url

    async def fetch(self) -> dict[str, Any]:
        """Fetch a size-limited JWKS object within a total five-second deadline."""
        async with (
            asyncio.timeout(5),
            stream(self.client, "GET", self.url, 5) as r,
        ):
            r.raise_for_status()
            document = json.loads(await bounded_read(r, 256 * 1024))
            if not isinstance(document, dict):
                raise TypeError("Invalid JWKS")
            return document


class HttpUpstream:
    def __init__(
        self,
        client: httpx.AsyncClient,
        url: str,
        max_response_bytes: int = 16 * 1024 * 1024,
    ) -> None:
        self.client, self.url = client, url.rstrip("/")
        self.max_response_bytes = max_response_bytes

    async def exchange(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        body: AsyncIterator[bytes],
        timeout: float,
    ) -> UpstreamReply:
        """Stream uploads out, then buffer only a bounded upstream response."""
        async with (
            # Bound the whole exchange, not just individual socket operations.
            asyncio.timeout(timeout),
            stream(
                self.client, method, self.url + path, timeout, headers, body
            ) as response,
        ):
            limit = (
                self.max_response_bytes
                if 200 <= response.status_code < 300
                else 64 * 1024
            )
            try:
                data = await bounded_read(response, limit)
            except ValueError:
                return UpstreamReply(502, b"")
            return UpstreamReply(
                response.status_code,
                data,
                response.headers.get("content-type") or "application/json",
            )

    async def ready(self) -> bool:
        try:
            async with (
                asyncio.timeout(2),
                stream(self.client, "GET", self.url + "/readyz", 2) as response,
            ):
                return response.status_code == 200
        except (httpx.HTTPError, TimeoutError):
            return False
