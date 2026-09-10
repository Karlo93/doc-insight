"""Query API and provider boundaries; passage indexes are zero-based internally."""

from contextlib import AbstractContextManager
from typing import Annotated, Literal, Protocol
from uuid import UUID

from doc_insight.contracts.storage import QueryFilter, SearchHit, StoredDocument
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


class Generator(Protocol):
    def generate(self, question: str, passages: list[str]) -> Generation: ...


class QueryReader(Protocol):
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
    def snapshot(self, tenant_id: str) -> AbstractContextManager[QueryReader]: ...


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
    provider: Literal["mistral", "extractive"]
    model: str


class QueryResponse(BaseModel):
    answer: str
    confidence: float = Field(ge=0, le=1)
    abstained: bool
    sources: list[Source]
    entities: list[CitedEntity]
    retrieval: RetrievalInfo
    generation: GenerationInfo
    latency_ms: int
