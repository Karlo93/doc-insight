"""Upload boundaries and the string-valued Redis wire contract."""

from datetime import UTC, datetime
from typing import BinaryIO, Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

TenantId = str
DocumentStatus = Literal["uploaded", "processing", "processed", "failed"]


class DocumentUploaded(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    type: Literal["document.uploaded"] = "document.uploaded"
    tenant_id: str = Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")
    document_id: UUID
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    object_key: str
    media_type: str
    size_bytes: int = Field(ge=0)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    traceparent: str | None = None

    def stream_fields(self) -> dict[str, str]:
        return {
            key: str(value)
            for key, value in self.model_dump(mode="json", exclude_none=True).items()
        }


class ObjectStore(Protocol):
    def put(self, key: str, stream: BinaryIO, size: int, media_type: str) -> None: ...
    def get(self, key: str) -> BinaryIO: ...
    def exists(self, key: str) -> bool: ...


class EventPublisher(Protocol):
    def publish(self, event: DocumentUploaded) -> None: ...
