"""Deterministic gateway providers with explicit clocks and captured requests."""

from collections.abc import AsyncIterator, Callable
from math import ceil, floor
from typing import Any

from doc_insight.contracts.gateway import (
    BackendUnavailable,
    Identity,
    RateDecision,
    UpstreamReply,
)


class FakeJwksSource:
    def __init__(self, document: dict[str, Any]) -> None:
        self.document = document
        self.calls = 0

    async def fetch(self) -> dict[str, Any]:
        self.calls += 1
        return self.document


class FakeRateLimiter:
    def __init__(
        self, rps: float = 5, burst: int = 10, clock: Callable[[], float] = lambda: 0
    ) -> None:
        self.rps, self.burst, self.clock = rps, burst, clock
        self.buckets: dict[Identity, tuple[float, float]] = {}
        self.available = True

    async def consume(self, identity: Identity) -> RateDecision:
        if not self.available:
            raise BackendUnavailable
        now = self.clock()
        tokens, updated = self.buckets.get(identity, (float(self.burst), now))
        tokens = min(self.burst, tokens + max(0, now - updated) * self.rps)
        allowed = tokens >= 1
        tokens -= int(allowed)
        self.buckets[identity] = (tokens, max(updated, now))
        return RateDecision(
            allowed, floor(tokens), 0 if allowed else ceil((1 - tokens) / self.rps)
        )

    async def ready(self) -> bool:
        return self.available


class FakeUpstream:
    def __init__(self, reply: UpstreamReply | None = None) -> None:
        self.reply = reply or UpstreamReply(200, b"{}")
        self.available = True
        self.requests: list[tuple[str, str, dict[str, str], bytes, float]] = []

    async def exchange(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        body: AsyncIterator[bytes],
        timeout: float,
    ) -> UpstreamReply:
        data = b"".join([chunk async for chunk in body])
        self.requests.append((method, path, headers, data, timeout))
        return self.reply

    async def ready(self) -> bool:
        return self.available
