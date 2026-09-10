"""Query API and provider boundaries; passage indexes are zero-based internally."""

from contextlib import AbstractContextManager
from typing import Annotated, Literal, Protocol
from uuid import UUID

from doc_insight.contracts.storage import QueryFilter, SearchHit, StoredDocument
from doc_insight.contracts.usage import TokenUsage
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

__all__ = ["QueryFilter"]


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    top_k: int = Field(default=5, ge=1, le=20, strict=True)
    filter: QueryFilter = Field(default_factory=QueryFilter)


class Generation(BaseModel):
    answer: str
    supported: bool
    cited_passage_indexes: list[int] = Field(default_factory=list)
    usage: TokenUsage | None = None


class Generator(Protocol):
    def generate(self, question: str, passages: list[str]) -> Generation:
        """Answer from passages using zero-based citations, or return unsupported output."""
        ...


class QueryReader(Protocol):
    def document_names(self, tenant_id: str) -> list[tuple[UUID, str]]:
        """Return tenant-owned IDs and filenames only, within this read snapshot."""
        ...

    def nearest_chunks(
        self,
        tenant_id: str,
        vector: list[float],
        k: int,
        filter: QueryFilter | None = None,
    ) -> list[SearchHit]: ...
    def search_text(
        self,
        tenant_id: str,
        query: str,
        k: int,
        filter: QueryFilter | None = None,
    ) -> list[SearchHit]: ...
    def get_document(
        self, tenant_id: str, document_id: UUID
    ) -> StoredDocument | None: ...


class QueryRepository(Protocol):
    def snapshot(self, tenant_id: str) -> AbstractContextManager[QueryReader]:
        """Own a consistent tenant read scope until the context manager exits."""
        ...


class Source(BaseModel):
    document_id: UUID
    page: int
    chunk_ord: int
    char_start: int
    char_end: int
    text: str
    score: float


class CitedEntity(BaseModel):
    text: str
    label: str
    count: int
    document_id: UUID


class RetrievalInfo(BaseModel):
    top_k: int
    hits: int
    hybrid: bool = True


class GenerationInfo(BaseModel):
    provider: Literal["openai", "extractive"]
    model: str
    usage: TokenUsage | None = None
    fallback_reason: str | None = None


class QueryResponse(BaseModel):
    answer: str
    confidence: float = Field(ge=0, le=1)
    abstained: bool
    sources: list[Source]
    entities: list[CitedEntity]
    retrieval: RetrievalInfo
    generation: GenerationInfo
    latency_ms: int
