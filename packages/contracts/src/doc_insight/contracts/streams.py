"""Small synchronous Redis Streams boundary with decoded string fields."""

from dataclasses import dataclass
from typing import Literal, Protocol, Self
from uuid import UUID

from doc_insight.contracts.extraction import MediaType
from doc_insight.contracts.ingest import DocumentUploaded
from pydantic import AwareDatetime, model_validator


class WorkerEvent(DocumentUploaded):
    # Producer defaults must not silently repair an incomplete wire message.
    event_id: UUID
    type: Literal["document.uploaded"]
    occurred_at: AwareDatetime
    media_type: MediaType

    @model_validator(mode="after")
    def valid_key(self) -> Self:
        if self.object_key != f"{self.tenant_id}/{self.sha256}":
            raise ValueError("Object key does not match tenant and digest")
        return self


@dataclass(frozen=True)
class StreamMessage:
    id: str
    fields: dict[str, str]


class StreamConsumer(Protocol):
    def xgroup_create(self, stream: str, group: str) -> None: ...
    def xreadgroup(
        self, stream: str, group: str, consumer: str, count: int, block_ms: int
    ) -> list[StreamMessage]: ...
    def xack(self, stream: str, group: str, message_id: str) -> None: ...
    def xadd(self, stream: str, fields: dict[str, str]) -> str: ...
    def xautoclaim(
        self,
        stream: str,
        group: str,
        consumer: str,
        min_idle_ms: int,
        start: str,
        count: int,
    ) -> tuple[str, list[StreamMessage]]: ...
    def xpending(self, stream: str, group: str, message_id: str) -> int: ...
    def heartbeat(self, consumer: str) -> None: ...
