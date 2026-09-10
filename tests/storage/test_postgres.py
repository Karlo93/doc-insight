from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from doc_insight.worker.repository import PostgresRepository
from sqlalchemy import event, inspect, text
from sqlalchemy.exc import IntegrityError


@pytest.mark.integration
def test_migration_from_empty_and_downgrade(empty_database, migrate_schema):
    engine = empty_database
    assert inspect(engine).get_table_names() == []
    migrate_schema(engine, "head")
    assert set(inspect(engine).get_table_names()) == {
        "alembic_version",
        "documents",
        "chunks",
        "entities",
        "outbox",
    }
    with engine.connect() as connection:
        indexes = (
            connection.execute(
                text("SELECT indexdef FROM pg_indexes WHERE tablename = 'chunks'")
            )
            .scalars()
            .all()
        )
        assert any("hnsw" in item and "vector_cosine_ops" in item for item in indexes)
    for table in ("documents", "chunks", "entities"):
        if table != "documents":
            assert all(
                not column["nullable"] for column in inspect(engine).get_columns(table)
            )
        assert any(
            index["column_names"] == ["tenant_id"]
            for index in inspect(engine).get_indexes(table)
        )
    migrate_schema(engine, "base", downgrade=True)
    assert inspect(engine).get_table_names() == ["alembic_version"]
    migrate_schema(engine, "head")


@pytest.mark.integration
def test_database_failure_rolls_back_metadata_chunks_and_entities(database, document):
    repository = PostgresRepository(database)
    tenant = uuid4().hex
    saved = repository.upsert_document(tenant, "a.pdf", document)

    def fail_entities(connection, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO entities"):
            raise RuntimeError("simulated failure after chunks were replaced")

    event.listen(database, "before_cursor_execute", fail_entities)
    try:
        document.pipeline_version = "failed"
        with pytest.raises(RuntimeError, match="simulated"):
            repository.upsert_document(tenant, "changed.pdf", document)
    finally:
        event.remove(database, "before_cursor_execute", fail_entities)
    assert repository.get_document(tenant, saved.id) == saved


@pytest.mark.integration
def test_concurrent_replays_and_database_tenant_constraint(
    database, migration_database, document
):
    repository = PostgresRepository(database)
    tenant = uuid4().hex
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: repository.upsert_document(tenant, "a.pdf", document),
                range(2),
            )
        )
    assert results[0].id == results[1].id
    assert len(repository.get_document(tenant, results[0].id).chunks) == 1
    with pytest.raises(IntegrityError), migration_database.begin() as connection:
        connection.execute(
            text("UPDATE chunks SET tenant_id = 'wrong' WHERE document_id = :id"),
            {"id": results[0].id},
        )
    with migration_database.begin() as connection:
        connection.execute(
            text("DELETE FROM documents WHERE tenant_id = :tenant"), {"tenant": tenant}
        )
    assert repository.nearest_chunks(tenant, document.chunks[0].embedding, 5) == []
