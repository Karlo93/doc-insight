"""An isolated repository fake with the same replacement and tenant semantics."""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from math import sqrt
from uuid import UUID, uuid4

from doc_insight.contracts.ingest import DocumentStatus, DocumentUploaded
from doc_insight.contracts.query import QueryReader
from doc_insight.contracts.storage import (
    QueryFilter,
    SearchHit,
    StoredDocument,
    prepare_document,
    validate_vector,
)
from doc_insight.contracts.structure import Chunk, Document, Entity


class InMemoryRepository:
    def __init__(self, dimension: int) -> None:
        self.dimension = dimension
        self.documents: dict[tuple[str, UUID], StoredDocument] = {}
        self.events: list[DocumentUploaded] = []

    def find_by_sha256(self, tenant_id: str, sha256: str) -> StoredDocument | None:
        return next(
            (
                d.model_copy(deep=True)
                for d in self.documents.values()
                if (d.tenant_id, d.sha256) == (tenant_id, sha256)
            ),
            None,
        )

    def register_upload(
        self,
        tenant_id: str,
        filename: str,
        sha256: str,
        media_type: str,
        size_bytes: int,
        object_key: str,
    ) -> StoredDocument:
        if previous := self.find_by_sha256(tenant_id, sha256):
            return previous
        record = StoredDocument(
            id=uuid4(),
            tenant_id=tenant_id,
            filename=filename,
            sha256=sha256,
            media_type=media_type,
            size_bytes=size_bytes,
            object_key=object_key,
            status="uploaded",
            created_at=datetime.now(UTC),
        )
        event = DocumentUploaded(
            tenant_id=tenant_id,
            document_id=record.id,
            sha256=sha256,
            media_type=media_type,
            size_bytes=size_bytes,
            object_key=object_key,
            occurred_at=record.created_at,
        )
        self.documents[tenant_id, record.id] = record.model_copy(deep=True)
        self.events.append(event)
        return record

    def mark_status(
        self,
        tenant_id: str,
        document_id: UUID,
        status: DocumentStatus,
        error: str | None = None,
    ) -> None:
        if status not in {"uploaded", "processing", "processed", "failed"}:
            raise ValueError("Invalid document status")
        if (document := self.documents.get((tenant_id, document_id))) is None:
            raise LookupError("Document not found for tenant")
        document.status = status
        document.error = error if status == "failed" else None

    def upsert_document(
        self, tenant_id: str, filename: str, document: Document
    ) -> StoredDocument:
        record = prepare_document(tenant_id, filename, document)
        for chunk in record.chunks:
            validate_vector(chunk.embedding or [], self.dimension)
        for previous in self.documents.values():
            if (previous.tenant_id, previous.sha256) == (tenant_id, document.sha256):
                record.id, record.created_at = previous.id, previous.created_at
                record.size_bytes, record.object_key = (
                    previous.size_bytes,
                    previous.object_key,
                )
                record.processed_at = max(
                    record.processed_at or record.created_at,
                    (previous.processed_at or previous.created_at)
                    + timedelta(microseconds=1),
                )
                break
        self.documents[tenant_id, record.id] = record.model_copy(deep=True)
        return record

    def replace_chunks_and_entities(
        self,
        tenant_id: str,
        document_id: UUID,
        chunks: list[Chunk],
        entities: list[Entity],
    ) -> None:
        document = self.get_document(tenant_id, document_id)
        if document is None:
            raise LookupError("Document not found for tenant")
        for chunk in chunks:
            validate_vector(chunk.embedding or [], self.dimension)
        document.chunks, document.entities = chunks, entities
        self.documents[tenant_id, document_id] = document.model_copy(deep=True)

    def get_document(self, tenant_id: str, document_id: UUID) -> StoredDocument | None:
        document = self.documents.get((tenant_id, document_id))
        return document.model_copy(deep=True) if document else None

    def nearest_chunks(
        self,
        tenant_id: str,
        vector: list[float],
        k: int,
        filter: QueryFilter | None = None,
    ) -> list[SearchHit]:
        validate_vector(vector, self.dimension)
        if k < 1:
            raise ValueError("k must be positive")
        hits = []
        for (tenant, document_id), document in self.documents.items():
            if tenant != tenant_id:
                continue
            for chunk in document.chunks:
                if filter is not None and (
                    (
                        filter.document_ids is not None
                        and document_id not in filter.document_ids
                    )
                    or (
                        filter.language is not None
                        and chunk.language != filter.language
                    )
                ):
                    continue
                embedding = chunk.embedding or []
                score = sum(
                    a * b for a, b in zip(vector, embedding, strict=True)
                ) / sqrt(sum(a * a for a in vector) * sum(b * b for b in embedding))
                hits.append(
                    SearchHit(
                        document_id=document_id,
                        chunk=chunk.model_copy(deep=True),
                        score=score,
                    )
                )
        hits.sort(key=lambda hit: (-hit.score, hit.document_id, hit.chunk.ord))
        return hits[:k]

    @contextmanager
    def snapshot(self, tenant_id: str) -> Iterator[QueryReader]:
        reader = deepcopy(self)
        reader.documents = {
            key: document
            for key, document in reader.documents.items()
            if key[0] == tenant_id
        }
        yield reader

    def search_text(
        self, tenant_id: str, query: str, k: int, filter: QueryFilter | None = None
    ) -> list[SearchHit]:
        if k < 1:
            raise ValueError("k must be positive")
        # Simple conjunction fake; PostgreSQL tests own websearch grammar and ts_rank_cd.
        terms = set(re.findall(r"[^\W_]+", query.casefold()))
        candidates = self.nearest_chunks(
            tenant_id,
            [1.0] + [0.0] * (self.dimension - 1),
            max(k, sum(len(d.chunks) for d in self.documents.values())),
            filter,
        )
        hits = [
            hit.model_copy(update={"score": float(len(terms))})
            for hit in candidates
            if terms and terms <= set(re.findall(r"[^\W_]+", hit.chunk.text.casefold()))
        ]
        hits.sort(key=lambda hit: (-hit.score, hit.document_id, hit.chunk.ord))
        return hits[:k]
