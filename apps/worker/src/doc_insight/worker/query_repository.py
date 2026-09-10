"""Reads bound to one PostgreSQL snapshot; full-text expressions need no migration."""

from typing import Any
from uuid import UUID

from doc_insight.contracts.query import QueryFilter
from doc_insight.contracts.storage import SearchHit, StoredDocument, validate_vector
from doc_insight.contracts.structure import Chunk
from sqlalchemy import (
    ColumnElement,
    Connection,
    Select,
    Table,
    func,
    literal_column,
    select,
)


class PostgresQueryReader:
    def __init__(
        self,
        connection: Connection,
        docs: Table,
        chunks: Table,
        entities: Table,
        dimension: int,
    ) -> None:
        self.connection, self.docs, self.chunks = connection, docs, chunks
        self.entities, self.dimension = entities, dimension

    def _read(
        self, statement: Select[Any], tenant_id: str, k: int, filter: QueryFilter | None
    ) -> list[SearchHit]:
        if k < 1:
            raise ValueError("k must be positive")
        statement = statement.where(self.chunks.c.tenant_id == tenant_id)
        if filter is not None:
            if filter.document_ids is not None:
                statement = statement.where(
                    self.chunks.c.document_id.in_(filter.document_ids)
                )
            if filter.language is not None:
                statement = statement.where(self.chunks.c.language == filter.language)
        statement = statement.order_by(self.chunks.c.document_id, self.chunks.c.ord)
        return [
            SearchHit(
                document_id=row["document_id"],
                chunk=Chunk.model_validate(row),
                score=row["score"],
            )
            for row in self.connection.execute(statement.limit(k)).mappings()
        ]

    def nearest_chunks(
        self,
        tenant_id: str,
        vector: list[float],
        k: int,
        filter: QueryFilter | None = None,
    ) -> list[SearchHit]:
        validate_vector(vector, self.dimension)
        distance = self.chunks.c.embedding.cosine_distance(vector)
        statement = select(self.chunks, (1 - distance).label("score")).order_by(
            distance
        )
        return self._read(statement, tenant_id, k, filter)

    def search_text(
        self, tenant_id: str, query: str, k: int, filter: QueryFilter | None = None
    ) -> list[SearchHit]:
        config: ColumnElement[str] = literal_column("'simple'::regconfig")
        vector = func.to_tsvector(config, self.chunks.c.text)
        terms = func.websearch_to_tsquery(config, query)
        rank = func.ts_rank_cd(vector, terms)
        statement = (
            select(self.chunks, rank.label("score"))
            .where(vector.op("@@")(terms))
            .order_by(rank.desc())
        )
        return self._read(statement, tenant_id, k, filter)

    def get_document(self, tenant_id: str, document_id: UUID) -> StoredDocument | None:
        row = (
            self.connection.execute(
                select(self.docs).filter_by(tenant_id=tenant_id, id=document_id)
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        children = {}
        for table, order in ((self.chunks, "ord"), (self.entities, "char_start")):
            children[table.name] = list(
                self.connection.execute(
                    select(table)
                    .filter_by(tenant_id=tenant_id, document_id=document_id)
                    .order_by(table.c.page, table.c[order])
                ).mappings()
            )
        return StoredDocument.model_validate(dict(row, **children))
