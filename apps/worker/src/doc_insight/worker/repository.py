"""SQLAlchemy Core adapter; the migration owns the schema, reflected once per instance."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast
from uuid import UUID, uuid5

from doc_insight.contracts.query import QueryFilter, QueryReader
from doc_insight.contracts.storage import (
    SearchHit,
    StoredDocument,
    prepare_document,
    validate_vector,
)
from doc_insight.contracts.structure import Chunk, Document, Entity
from doc_insight.worker.query_repository import PostgresQueryReader
from doc_insight.worker.uploads import UploadRepository
from pgvector.sqlalchemy import VECTOR
from sqlalchemy import Connection, Engine, MetaData, Table, func, select, text
from sqlalchemy.dialects.postgresql import insert


def _set_tenant(connection: Connection, tenant_id: str) -> None:
    # Transaction-local state is cleared on commit/rollback before pool reuse.
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": tenant_id}
    )


class PostgresRepository(UploadRepository):
    """Tenant-scoped SQL adapter over migration-owned, reflected tables.

    Use a restricted runtime role: transactions bind the RLS tenant context, while
    explicit filters and composite foreign keys preserve ownership. Upserts replace
    metadata and derived rows together; snapshots keep multi-query reads consistent.
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        metadata = MetaData()
        self.docs, self.chunks, self.entities, self.outbox = (
            Table(name, metadata, autoload_with=engine)
            for name in ("documents", "chunks", "entities", "outbox")
        )
        self.dimension = cast(int, cast(VECTOR, self.chunks.c.embedding.type).dim)

    def _replace(
        self,
        connection: Connection,
        tenant_id: str,
        document_id: UUID,
        chunks: list[Chunk],
        entities: list[Entity],
    ) -> None:
        for chunk in chunks:
            validate_vector(chunk.embedding or [], self.dimension)
        for table, items in ((self.chunks, chunks), (self.entities, entities)):
            connection.execute(
                table.delete().where(
                    table.c.tenant_id == tenant_id, table.c.document_id == document_id
                )
            )
            if items:
                rows = [
                    dict(
                        item.model_dump(),
                        id=uuid5(document_id, f"{table.name}:{index}"),
                        tenant_id=tenant_id,
                        document_id=document_id,
                    )
                    for index, item in enumerate(items)
                ]
                connection.execute(table.insert(), rows)

    def upsert_document(
        self, tenant_id: str, filename: str, document: Document
    ) -> StoredDocument:
        record = prepare_document(tenant_id, filename, document)
        values = record.model_dump(
            exclude={"chunks", "entities", "size_bytes", "object_key"}
        )
        values["processed_at"] = func.clock_timestamp()
        statement = insert(self.docs).values(**values)
        updates = {
            key: value
            for key, value in values.items()
            if key not in {"id", "tenant_id", "sha256", "created_at"}
        }
        # The conflict update locks this document until its replacement commits.
        upsert = statement.on_conflict_do_update(
            index_elements=["tenant_id", "sha256"], set_=updates
        ).returning(self.docs)
        with self.engine.begin() as connection:
            _set_tenant(connection, tenant_id)
            row = connection.execute(upsert).mappings().one()
            self._replace(
                connection, tenant_id, row["id"], record.chunks, record.entities
            )
            return StoredDocument(**row, chunks=record.chunks, entities=record.entities)

    def replace_chunks_and_entities(
        self,
        tenant_id: str,
        document_id: UUID,
        chunks: list[Chunk],
        entities: list[Entity],
    ) -> None:
        with self.engine.begin() as connection:
            _set_tenant(connection, tenant_id)
            owner = connection.execute(
                select(self.docs.c.id)
                .filter_by(tenant_id=tenant_id, id=document_id)
                .with_for_update()
            ).scalar_one_or_none()
            if owner is None:
                raise LookupError("Document not found for tenant")
            self._replace(connection, tenant_id, document_id, chunks, entities)

    @contextmanager
    def snapshot(self, tenant_id: str) -> Iterator[QueryReader]:
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            _set_tenant(connection, tenant_id)
            yield PostgresQueryReader(
                connection, self.docs, self.chunks, self.entities, self.dimension
            )

    def get_document(self, tenant_id: str, document_id: UUID) -> StoredDocument | None:
        with self.snapshot(tenant_id) as reader:
            return reader.get_document(tenant_id, document_id)

    def nearest_chunks(
        self,
        tenant_id: str,
        vector: list[float],
        k: int,
        filter: QueryFilter | None = None,
    ) -> list[SearchHit]:
        with self.snapshot(tenant_id) as reader:
            return reader.nearest_chunks(tenant_id, vector, k, filter)

    def search_text(
        self,
        tenant_id: str,
        query: str,
        k: int,
        filter: QueryFilter | None = None,
    ) -> list[SearchHit]:
        with self.snapshot(tenant_id) as reader:
            return reader.search_text(tenant_id, query, k, filter)
