import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from doc_insight.contracts.extraction import Page
from doc_insight.contracts.storage import DocumentRepository
from doc_insight.contracts.structure import Chunk, Document, Entity
from doc_insight.testing.storage import InMemoryRepository
from doc_insight.worker.repository import PostgresRepository
from doc_insight.worker.settings import Settings
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]


def migrate(engine, revision, downgrade=False):
    config = Config(str(ROOT / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        (command.downgrade if downgrade else command.upgrade)(config, revision)


LOCAL_HOSTS = {None, "localhost", "127.0.0.1", "::1"}


@contextmanager
def temporary_database():
    url = make_url(Settings().migration_database_url)
    # Creating and dropping databases on a shared server is destructive; opt in explicitly.
    if url.host not in LOCAL_HOSTS and not os.environ.get("DI_ALLOW_REMOTE_TEST_DB"):
        raise RuntimeError(
            f"Refusing to create test databases on {url.host!r};"
            " set DI_ALLOW_REMOTE_TEST_DB=1 to allow it"
        )
    name = f"di_test_{uuid4().hex}"
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(url.set(database=name), hide_parameters=True)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}"'))
        admin.dispose()


@pytest.fixture
def temporary_database_factory():
    return temporary_database


@pytest.fixture(scope="module")
def migration_database():
    with temporary_database() as engine:
        migrate(engine, "head")
        yield engine


@pytest.fixture(scope="module")
def database(migration_database):
    # A separate login proves policies without inheriting the migration role's bypass.
    role, password = f"di_app_{uuid4().hex}", uuid4().hex
    with migration_database.begin() as connection:
        connection.execute(
            text(
                f"CREATE ROLE {role} LOGIN PASSWORD '{password}'"
                " NOSUPERUSER NOBYPASSRLS NOINHERIT"
            )
        )
        connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
        connection.execute(
            text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON"
                f" documents, chunks, entities, outbox, llm_usage, llm_budgets TO {role}"
            )
        )
    engine = create_engine(
        migration_database.url.set(username=role, password=password),
        hide_parameters=True,
        pool_size=1,
        max_overflow=1,
    )
    try:
        yield engine
    finally:
        engine.dispose()
        with migration_database.begin() as connection:
            connection.execute(text(f"DROP OWNED BY {role}"))
            connection.execute(text(f"DROP ROLE {role}"))


@pytest.fixture(
    params=["memory", pytest.param("postgres", marks=pytest.mark.integration)]
)
def repository(request) -> DocumentRepository:
    if request.param == "memory":
        return InMemoryRepository(384)
    return PostgresRepository(request.getfixturevalue("database"))


@pytest.fixture
def document():
    return Document(
        sha256="a" * 64,
        media_type="application/pdf",
        pages=[
            Page(
                number=1,
                text="Alice studies astronomy.",
                source="text_layer",
                language="en",
            )
        ],
        chunks=[
            Chunk(
                text="Alice studies astronomy.",
                language="en",
                page=1,
                ord=0,
                char_start=0,
                char_end=24,
                token_count=3,
                embedding=[1.0] + [0.0] * 383,
            )
        ],
        entities=[
            Entity(text="Alice", label="PERSON", page=1, char_start=0, char_end=5)
        ],
        embed_model="fake/hash",
        embed_dimension=384,
    )


@pytest.fixture
def empty_database():
    with temporary_database() as engine:
        yield engine


@pytest.fixture
def migrate_schema():
    return migrate


from doc_insight.ingest.adapters import S3ObjectStore
from doc_insight.ingest.settings import Settings as IngestSettings
from redis import Redis


@pytest.fixture
def storage_settings():
    return IngestSettings()


@pytest.fixture
def s3(storage_settings):
    objects = S3ObjectStore.from_settings(storage_settings)
    yield objects
    objects.client.close()


@pytest.fixture
def redis_client(storage_settings):
    client = Redis.from_url(
        storage_settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=3,
    )
    yield client
    client.close()
