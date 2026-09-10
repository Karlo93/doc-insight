"""Tenant-scoped persistence; upsert commits metadata and all derived output together."""

from datetime import UTC, datetime
from math import isfinite
from typing import Protocol
from uuid import UUID, uuid4

from doc_insight.contracts.structure import Chunk, Document, Entity
from pydantic import BaseModel


class StoredDocument(BaseModel):
    id: UUID
    tenant_id: str
    filename: str
    sha256: str
    media_type: str
    page_count: int
    language: str
    status: str = "processed"
    pipeline_version: str
    embed_model: str
    created_at: datetime
    processed_at: datetime
    chunks: list[Chunk] = []
    entities: list[Entity] = []


class SearchHit(BaseModel):
    document_id: UUID
    chunk: Chunk
    score: float


def validate_vector(vector: list[float], dimension: int) -> None:
    if len(vector) != dimension or not all(map(isfinite, vector)) or not any(vector):
        raise ValueError("Expected a finite nonzero vector matching the dimension")


def prepare_document(
    tenant_id: str, filename: str, document: Document
) -> StoredDocument:
    if not all((tenant_id.strip(), document.embed_model, document.embed_dimension)):
        raise ValueError("A tenant and an embedded document are required")
    for chunk in document.chunks:
        validate_vector(chunk.embedding or [], document.embed_dimension or 0)
    values = document.model_dump(exclude={"pages", "embed_dimension"})
    now = datetime.now(UTC)
    return StoredDocument(
        **values,
        id=uuid4(),
        tenant_id=tenant_id,
        filename=filename,
        created_at=now,
        processed_at=now,
    )


class DocumentRepository(Protocol):
    def upsert_document(
        self, tenant_id: str, filename: str, document: Document
    ) -> StoredDocument: ...
    def replace_chunks_and_entities(
        self,
        tenant_id: str,
        document_id: UUID,
        chunks: list[Chunk],
        entities: list[Entity],
    ) -> None: ...
    def get_document(
        self, tenant_id: str, document_id: UUID
    ) -> StoredDocument | None: ...
    def nearest_chunks(
        self, tenant_id: str, vector: list[float], k: int
    ) -> list[SearchHit]: ...
