"""SQLAlchemy Core adapter; the migration owns the schema, reflected once per instance."""

from typing import cast
from uuid import UUID, uuid5

from doc_insight.contracts.storage import (
    SearchHit,
    StoredDocument,
    prepare_document,
    validate_vector,
)
from doc_insight.contracts.structure import Chunk, Document, Entity
from pgvector.sqlalchemy import VECTOR
from sqlalchemy import Connection, Engine, MetaData, Table, func, select, text
from sqlalchemy.dialects.postgresql import insert


def _set_tenant(connection: Connection, tenant_id: str) -> None:
    # Transaction-local state is cleared on commit/rollback before pool reuse.
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": tenant_id}
    )


class PostgresRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        metadata = MetaData()
        self.docs, self.chunks, self.entities = (
            Table(name, metadata, autoload_with=engine)
            for name in ("documents", "chunks", "entities")
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
        values = record.model_dump(exclude={"chunks", "entities"})
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

    def get_document(self, tenant_id: str, document_id: UUID) -> StoredDocument | None:
        # One snapshot prevents a concurrent replacement mixing metadata and children.
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            _set_tenant(connection, tenant_id)
            query = select(self.docs).filter_by(tenant_id=tenant_id, id=document_id)
            row = connection.execute(query).mappings().one_or_none()
            if row is None:
                return None
            children = {}
            for table, order in ((self.chunks, "ord"), (self.entities, "char_start")):
                rows = connection.execute(
                    select(table)
                    .filter_by(tenant_id=tenant_id, document_id=document_id)
                    .order_by(table.c.page, table.c[order])
                ).mappings()
                children[table.name] = list(rows)
            return StoredDocument.model_validate(dict(row, **children))

    def nearest_chunks(
        self, tenant_id: str, vector: list[float], k: int
    ) -> list[SearchHit]:
        validate_vector(vector, self.dimension)
        if k < 1:
            raise ValueError("k must be positive")
        distance = self.chunks.c.embedding.cosine_distance(vector)
        statement = (
            select(self.chunks, (1 - distance).label("score"))
            .where(self.chunks.c.tenant_id == tenant_id)
            .order_by(distance, self.chunks.c.document_id, self.chunks.c.ord)
            .limit(k)
        )
        with self.engine.connect() as connection:
            _set_tenant(connection, tenant_id)
            return [
                SearchHit(
                    document_id=row["document_id"],
                    chunk=Chunk.model_validate(row),
                    score=row["score"],
                )
                for row in connection.execute(statement).mappings()
            ]
