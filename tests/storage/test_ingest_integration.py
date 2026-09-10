from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from doc_insight.ingest.adapters import RedisPublisher
from doc_insight.ingest.main import create_app
from doc_insight.ingest.relay import OutboxRelay
from doc_insight.ingest.runtime import Resources
from doc_insight.testing.ingest import RecordingPublisher
from doc_insight.worker.repository import PostgresRepository
from doc_insight.worker.uploads import set_tenant
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError, ProgrammingError

pytestmark = pytest.mark.integration


def register(repository, tenant, digest=None):
    digest = digest or uuid4().hex * 2
    return repository.register_upload(
        tenant, "fixture.pdf", digest, "application/pdf", 10, f"{tenant}/{digest}"
    )


def pending(database, tenant):
    with database.begin() as connection:
        set_tenant(connection, tenant)
        return (
            connection.execute(text("SELECT * FROM outbox ORDER BY created_at, id"))
            .mappings()
            .all()
        )


def test_pdf_to_stream(database, s3, redis_client, storage_settings):
    tenant = uuid4().hex
    repository = PostgresRepository(database)
    data = (Path(__file__).parents[1] / "fixtures/text_hr.pdf").read_bytes()
    group = f"test-{tenant}"
    redis_client.xgroup_create("di:documents", group, id="$", mkstream=True)
    objects = Resources(repository, s3, lambda: None, lambda: None)
    fields = None
    try:
        with TestClient(create_app(objects, storage_settings)) as client:
            response = client.post(
                "/ingest",
                files={"file": ("fixture.pdf", data)},
                headers={"X-Tenant-Id": tenant},
            )
            assert response.status_code == 202
            saved = repository.find_by_sha256(tenant, sha256(data).hexdigest())
            assert saved.status == "uploaded" and saved.size_bytes == len(data)
            assert pending(database, tenant)[0]["aggregate_id"] == saved.id
            assert (
                OutboxRelay(database, RedisPublisher(redis_client)).run_once(tenant)
                == 1
            )
            entries = redis_client.xreadgroup(
                group, "worker", {"di:documents": ">"}, count=100
            )
            messages = [
                (key, payload) for _, items in entries for key, payload in items
            ]
            key, fields = next(
                (key, payload)
                for key, payload in messages
                if payload["tenant_id"] == tenant
            )
            assert fields["document_id"] == str(saved.id)
            assert fields["size_bytes"] == str(len(data))
            assert fields["type"] == "document.uploaded"
            assert pending(database, tenant)[0]["published_at"] is not None
            assert (
                OutboxRelay(database, RedisPublisher(redis_client)).run_once(tenant)
                == 0
            )
            redis_client.xack("di:documents", group, key)
            redis_client.xdel("di:documents", key)
    finally:
        s3.client.delete_object(
            Bucket=s3.bucket, Key=f"{tenant}/{sha256(data).hexdigest()}"
        )
        redis_client.xgroup_destroy("di:documents", group)


def test_concurrent_registrations_emit_one_event(database):
    repository = PostgresRepository(database)
    tenant, digest = uuid4().hex, uuid4().hex * 2
    with ThreadPoolExecutor(2) as pool:
        records = list(
            pool.map(lambda _: register(repository, tenant, digest), range(2))
        )
    assert records[0].id == records[1].id
    assert len(pending(database, tenant)) == 1


def test_outbox_failure_rolls_back_document(database):
    repository = PostgresRepository(database)
    tenant, digest = uuid4().hex, uuid4().hex * 2

    def fail(connection, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO outbox"):
            raise RuntimeError("injected outbox failure")

    event.listen(database, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError):
            register(repository, tenant, digest)
    finally:
        event.remove(database, "before_cursor_execute", fail)
    assert repository.find_by_sha256(tenant, digest) is None
    assert pending(database, tenant) == []


def test_two_relays_skip_locked_rows(database):
    repository = PostgresRepository(database)
    tenant = uuid4().hex
    first, second = register(repository, tenant), register(repository, tenant)
    entered, release = Event(), Event()

    class BlockedPublisher(RecordingPublisher):
        def publish(self, event):
            entered.set()
            assert release.wait(10)
            super().publish(event)

    blocked, other = BlockedPublisher(), RecordingPublisher()
    relay_a, relay_b = OutboxRelay(database, blocked), OutboxRelay(database, other)
    with ThreadPoolExecutor(2) as pool:
        running = pool.submit(relay_a.run_once, tenant, 1)
        try:
            assert entered.wait(10)
            assert pool.submit(relay_b.run_once, tenant, 1).result(timeout=10) == 1
        finally:
            release.set()
        assert running.result(timeout=10) == 1
    assert {e.document_id for e in blocked.events + other.events} == {
        first.id,
        second.id,
    }
    assert len(blocked.events) == len(other.events) == 1


def test_publish_failure_retries_same_event(database):
    tenant = uuid4().hex
    register(PostgresRepository(database), tenant)

    class FailAfterPublish(RecordingPublisher):
        def publish(self, event):
            super().publish(event)
            raise OSError("lost acknowledgement")

    failing = FailAfterPublish()
    with pytest.raises(OSError):
        OutboxRelay(database, failing).run_once(tenant)
    assert pending(database, tenant)[0]["published_at"] is None
    successful = RecordingPublisher()
    assert OutboxRelay(database, successful).run_once(tenant) == 1
    assert failing.events == successful.events


def test_outbox_rls(database):
    tenant, other = uuid4().hex, uuid4().hex
    repository = PostgresRepository(database)
    register(repository, tenant)
    register(repository, other)
    row = pending(database, tenant)[0]
    assert [item["tenant_id"] for item in pending(database, tenant)] == [tenant]
    with database.begin() as connection:
        assert connection.execute(text("SELECT * FROM outbox")).all() == []
        assert (
            connection.execute(text("UPDATE outbox SET published_at = now()")).rowcount
            == 0
        )
        assert connection.execute(text("DELETE FROM outbox")).rowcount == 0
    for scope in (None, other):
        with pytest.raises(ProgrammingError), database.begin() as connection:
            if scope is not None:
                set_tenant(connection, scope)
            connection.execute(repository.outbox.insert().values(dict(row, id=uuid4())))
    with database.begin() as connection:
        set_tenant(connection, other)
        assert (
            connection.execute(
                repository.outbox.update()
                .where(repository.outbox.c.tenant_id == tenant)
                .values(published_at=None)
            ).rowcount
            == 0
        )
        assert (
            connection.execute(
                repository.outbox.delete().where(
                    repository.outbox.c.tenant_id == tenant
                )
            ).rowcount
            == 0
        )
    publisher = RecordingPublisher()
    assert OutboxRelay(database, publisher).run_once(tenant) == 1
    assert [e.tenant_id for e in publisher.events] == [tenant]
    assert pending(database, other)[0]["published_at"] is None


def test_downgrade_refuses_unprocessed_rows(empty_database, migrate_schema):
    migrate_schema(empty_database, "head")
    saved = register(PostgresRepository(empty_database), uuid4().hex)
    with pytest.raises(IntegrityError):
        migrate_schema(empty_database, "0002_row_level_security", downgrade=True)
    assert PostgresRepository(empty_database).get_document(saved.tenant_id, saved.id)
