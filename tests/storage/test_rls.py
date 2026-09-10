from uuid import uuid4

import pytest
from doc_insight.worker.repository import PostgresRepository
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

pytestmark = pytest.mark.integration
TABLES = ("documents", "chunks", "entities")


@pytest.fixture
def tenants(database, document):
    repository = PostgresRepository(database)
    first, second = uuid4().hex, uuid4().hex
    repository.upsert_document(first, "a.pdf", document)
    repository.upsert_document(second, "b.pdf", document)
    return repository, first, second


def set_tenant(connection, tenant):
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": tenant}
    )


def insert_row(repository, migration_database, table, tenant):
    table = getattr(repository, "docs" if table == "documents" else table)
    with migration_database.connect() as connection:
        row = dict(
            connection.execute(select(table).where(table.c.tenant_id == tenant))
            .mappings()
            .one()
        )
    row["id"] = uuid4()
    if table.name == "documents":
        row["sha256"] = uuid4().hex * 2
    return table.insert().values(**row)


@pytest.mark.parametrize("table", TABLES)
def test_raw_select_update_delete_are_tenant_scoped(database, tenants, table):
    _, first, second = tenants
    with database.connect() as connection:
        set_tenant(connection, first)
        assert connection.execute(
            text(f"SELECT tenant_id FROM {table}")
        ).scalars().all() == [first]
        for statement in (
            f"SELECT * FROM {table} WHERE tenant_id = :other",
            f"UPDATE {table} SET tenant_id = tenant_id WHERE tenant_id = :other RETURNING id",
            f"DELETE FROM {table} WHERE tenant_id = :other RETURNING id",
        ):
            assert connection.execute(text(statement), {"other": second}).all() == []
        assert (
            connection.execute(
                text(f"UPDATE {table} SET tenant_id = tenant_id")
            ).rowcount
            == 1
        )
        assert connection.execute(text(f"DELETE FROM {table}")).rowcount == 1


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize("operation", ["insert", "update"])
def test_raw_cross_tenant_writes_are_rejected(
    database, migration_database, tenants, table, operation
):
    repository, first, second = tenants
    statement = (
        insert_row(repository, migration_database, table, second)
        if operation == "insert"
        else text(f"UPDATE {table} SET tenant_id = :other")
    )
    with pytest.raises(ProgrammingError) as caught, database.begin() as connection:
        set_tenant(connection, first)
        connection.execute(statement, {"other": second})
    assert caught.value.orig.sqlstate == "42501"


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize("empty_tenant", [False, True])
def test_no_tenant_denies_all_row_operations(
    database, migration_database, tenants, table, empty_tenant
):
    repository, first, _ = tenants
    with database.connect() as connection:
        assert connection.execute(
            text("SELECT current_setting('app.tenant_id', true)")
        ).scalar() in (None, "")
        assert connection.execute(text(f"SELECT * FROM {table}")).all() == []
        assert (
            connection.execute(
                text(f"UPDATE {table} SET tenant_id = tenant_id")
            ).rowcount
            == 0
        )
        assert connection.execute(text(f"DELETE FROM {table}")).rowcount == 0
    with pytest.raises(ProgrammingError) as caught, database.begin() as connection:
        statement = insert_row(repository, migration_database, table, first)
        if empty_tenant:
            statement = statement.values(tenant_id="")
        connection.execute(statement)
    assert caught.value.orig.sqlstate == "42501"


@pytest.mark.parametrize("finish", ["commit", "rollback", "exception"])
def test_pool_reuse_clears_tenant(database, tenants, finish):
    _, first, second = tenants
    with database.connect() as connection:
        pid = connection.execute(text("SELECT pg_backend_pid()")).scalar()
        set_tenant(connection, first)
        if finish == "exception":
            with pytest.raises(ProgrammingError):
                connection.execute(text("SELECT * FROM missing_rls_test_table"))
        else:
            getattr(connection, finish)()
    with database.connect() as connection:
        assert connection.execute(text("SELECT pg_backend_pid()")).scalar() == pid
        assert connection.execute(text("SELECT * FROM documents")).all() == []
        set_tenant(connection, second)
        assert connection.execute(
            text("SELECT tenant_id FROM documents")
        ).scalars().all() == [second]


@pytest.mark.parametrize("table", TABLES)
def test_force_applies_to_a_restricted_table_owner(
    database, migration_database, tenants, table
):
    _, first, _ = tenants
    role = database.url.username
    with migration_database.connect() as connection:
        connection.execute(text(f"GRANT CREATE ON SCHEMA public TO {role}"))
        connection.execute(text(f"ALTER TABLE {table} OWNER TO {role}"))
        connection.execute(text(f"SET LOCAL ROLE {role}"))
        assert connection.execute(text(f"SELECT * FROM {table}")).all() == []
        set_tenant(connection, first)
        assert connection.execute(
            text(f"SELECT tenant_id FROM {table}")
        ).scalars().all() == [first]


def test_rls_migration_downgrade_and_upgrade(empty_database, migrate_schema):
    migrate_schema(empty_database, "head")
    for revision, enabled in (
        ("head", True),
        ("0001_core_tables", False),
        ("head", True),
    ):
        migrate_schema(empty_database, revision, downgrade=not enabled)
        with empty_database.connect() as connection:
            flags = connection.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname IN ('documents', 'chunks', 'entities')"
                )
            ).all()
            assert flags == [(enabled, enabled)] * 3
            policies = connection.execute(
                text(
                    "SELECT tablename, policyname, cmd, qual, with_check FROM pg_policies "
                    "WHERE schemaname = 'public'"
                )
            ).all()
            assert len(policies) == (3 if enabled else 0)
            for policy in policies:
                assert policy.tablename in TABLES
                assert policy.policyname == "tenant_isolation" and policy.cmd == "ALL"
                assert policy.qual == policy.with_check


def test_runtime_role_cannot_bypass_or_disable_rls(database):
    with database.connect() as connection:
        assert connection.execute(
            text(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
            )
        ).one() == (False, False)
    with pytest.raises(ProgrammingError), database.begin() as connection:
        connection.execute(text("ALTER TABLE documents DISABLE ROW LEVEL SECURITY"))


def test_tenant_is_bound_as_data(database, document):
    repository = PostgresRepository(database)
    tenant = "quoted'; RESET app.tenant_id; --"
    saved = repository.upsert_document(tenant, "a.pdf", document)
    assert repository.get_document(tenant, saved.id) == saved
    assert repository.nearest_chunks(tenant, document.chunks[0].embedding, 1)
