"""Gateway identity and replaceable HTTP and rate-limit boundaries."""

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Identity:
    tenant: str
    user: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", self.tenant):
            raise ValueError("Invalid tenant")
        # These claims become HTTP headers; reject controls and unbounded values.
        if not re.fullmatch(r"[\x21-\x7e]{1,256}", self.user):
            raise ValueError("Invalid user")


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    remaining: int
    retry_after: int = 0


class BackendUnavailable(Exception):
    """The quota store could not make a decision."""


class JwksSource(Protocol):
    async def fetch(self) -> dict[str, Any]: ...


class RateLimiter(Protocol):
    async def consume(self, identity: Identity) -> RateDecision: ...
    async def ready(self) -> bool: ...


@dataclass(frozen=True)
class UpstreamReply:
    status: int
    body: bytes
    content_type: str = "application/json"


class Upstream(Protocol):
    async def exchange(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        body: AsyncIterator[bytes],
        timeout: float,
    ) -> UpstreamReply: ...

    async def ready(self) -> bool: ...
