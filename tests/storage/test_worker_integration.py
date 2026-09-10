from hashlib import sha256
from io import BytesIO
from multiprocessing import get_context
from pathlib import Path
from uuid import uuid4

import pytest
from doc_insight.contracts.ingest import DocumentUploaded
from doc_insight.testing.embedding import FakeEmbedder
from doc_insight.testing.ingest import InMemoryObjectStore
from doc_insight.testing.structure import (
    FakeLanguageDetector,
    FakeNerExtractor,
    FakeTokenizer,
)
from doc_insight.worker import service
from doc_insight.worker.pipeline import Pipeline
from doc_insight.worker.processing import DocumentProcessor
from doc_insight.worker.repository import PostgresRepository
from doc_insight.worker.service import Worker
from doc_insight.worker.settings import Settings
from doc_insight.worker.streams import RedisStreamConsumer
from redis import Redis
from sqlalchemy import create_engine

pytestmark = pytest.mark.integration
FIXTURE = Path(__file__).parents[1] / "fixtures" / "text_hr.pdf"


def pipeline(settings, embedder=None):
    return Pipeline(
        settings,
        FakeLanguageDetector("hr"),
        FakeNerExtractor(),
        FakeTokenizer(),
        embedder or FakeEmbedder(),
    )


@pytest.fixture
def event_setup(database, monkeypatch, redis_client):
    stream = f"test-worker:{uuid4().hex}"
    monkeypatch.setattr(service, "STREAM", stream)
    monkeypatch.setattr(service, "DLQ", stream + ":dlq")
    repository = PostgresRepository(database)
    data = FIXTURE.read_bytes()
    tenant, digest = uuid4().hex, sha256(data).hexdigest()
    record = repository.register_upload(
        tenant,
        "fixture.pdf",
        digest,
        "application/pdf",
        len(data),
        f"{tenant}/{digest}",
    )
    event = DocumentUploaded(
        tenant_id=tenant,
        document_id=record.id,
        sha256=digest,
        object_key=record.object_key,
        media_type=record.media_type,
        size_bytes=len(data),
    )
    yield repository, event, data, stream
    redis_client.delete(stream, stream + ":dlq")
    for key in redis_client.scan_iter(f"di:worker:{stream}*"):
        redis_client.delete(key)


@pytest.mark.parametrize("real_objects", [False, True])
def test_worker_real_redis_postgres_and_object_store(
    event_setup, redis_client, request, real_objects
):
    repository, event, data, stream_name = event_setup
    objects = request.getfixturevalue("s3") if real_objects else InMemoryObjectStore()
    objects.put(event.object_key, BytesIO(data), len(data), event.media_type)
    try:
        stream = RedisStreamConsumer(redis_client)
        settings = Settings(worker_block_ms=1)
        worker = Worker(
            stream,
            DocumentProcessor(repository, objects, pipeline(settings)),
            settings,
            stream_name,
        )
        key = stream.xadd(stream_name, event.stream_fields())
        worker.run_once()
        record = repository.get_document(event.tenant_id, event.document_id)
        assert record.status == "processed" and record.chunks and record.entities
        assert stream.xpending(stream_name, "worker", key) == 0
        assert repository.get_document("other", event.document_id) is None
        assert redis_client.ttl(f"di:worker:{stream_name}") > 0
        duplicate = stream.xadd(stream_name, event.stream_fields())
        worker.run_once()
        assert stream.xpending(stream_name, "worker", duplicate) == 0
        assert (
            repository.get_document(event.tenant_id, event.document_id).processed_at
            == record.processed_at
        )
    finally:
        if real_objects:
            objects.client.delete_object(Bucket=objects.bucket, Key=event.object_key)


class PausedEmbedder(FakeEmbedder):
    def __init__(self, reached, release):
        super().__init__()
        self.reached, self.release = reached, release

    def embed_passages(self, texts):
        self.reached.set()
        if not self.release.wait(40):
            raise RuntimeError("Test synchronization timed out")
        return super().embed_passages(texts)


def consume_process(
    url, redis_url, event_fields, data, stream_name, reached=None, release=None
):
    # Spawned processes use real durable DB/stream state and local deterministic model providers.
    service.STREAM, service.DLQ = stream_name, stream_name + ":dlq"
    engine = create_engine(url, hide_parameters=True)
    client = Redis.from_url(redis_url, decode_responses=True)
    try:
        event = DocumentUploaded.model_validate(event_fields)
        objects = InMemoryObjectStore()
        objects.put(event.object_key, BytesIO(data), len(data), event.media_type)
        settings = Settings(worker_block_ms=1, worker_claim_min_idle_ms=1)
        embedder = (
            PausedEmbedder(reached, release) if reached is not None else FakeEmbedder()
        )
        processor = DocumentProcessor(
            PostgresRepository(engine), objects, pipeline(settings, embedder)
        )
        Worker(
            RedisStreamConsumer(client),
            processor,
            settings,
            stream_name + ("-old" if reached else "-new"),
        ).run_once()
    finally:
        client.close()
        engine.dispose()


def test_kill_halfway_restart_reclaims_and_completes(
    event_setup, redis_client, database, storage_settings
):
    repository, event, data, stream_name = event_setup
    key = redis_client.xadd(stream_name, event.stream_fields())
    context = get_context("spawn")
    reached, release = context.Event(), context.Event()
    args = (
        database.url.render_as_string(hide_password=False),
        storage_settings.redis_url,
        event.stream_fields(),
        data,
        stream_name,
    )
    child = context.Process(target=consume_process, args=(*args, reached, release))
    child.start()
    try:
        assert reached.wait(30), "Child did not reach the middle of the pipeline"
        assert (
            repository.get_document(event.tenant_id, event.document_id).status
            == "processing"
        )
        assert repository.get_document(event.tenant_id, event.document_id).chunks == []
        child.terminate()
        child.join(10)
        assert not child.is_alive()
        pending = redis_client.xpending_range(stream_name, "worker", key, key, 1)
        assert pending[0]["times_delivered"] == 1
        # Make idle time deterministic; no sleeps or timing races in the reclaim test.
        redis_client.xclaim(
            stream_name,
            "worker",
            stream_name + "-old",
            0,
            [key],
            idle=1000,
            justid=True,
        )
        restarted = context.Process(target=consume_process, args=args)
        restarted.start()
        try:
            restarted.join(30)
            assert restarted.exitcode == 0
        finally:
            if restarted.is_alive():
                restarted.terminate()
                restarted.join(10)
        stored = repository.get_document(event.tenant_id, event.document_id)
        assert stored.status == "processed" and stored.chunks and stored.entities
        assert (
            RedisStreamConsumer(redis_client).xpending(stream_name, "worker", key) == 0
        )
    finally:
        if child.is_alive():
            child.terminate()
        child.join(10)


def test_real_redis_poison_and_delivery_limit(event_setup, redis_client):
    repository, event, data, stream_name = event_setup
    objects = InMemoryObjectStore()
    objects.put(event.object_key, BytesIO(data), len(data), event.media_type)
    settings = Settings(
        worker_block_ms=1, worker_max_attempts=1, worker_claim_min_idle_ms=1
    )
    stream = RedisStreamConsumer(redis_client)
    stream.xgroup_create(stream_name, "worker")
    bad = stream.xadd(stream_name, {"type": "poison"})
    worker = Worker(
        stream,
        DocumentProcessor(repository, objects, pipeline(settings)),
        settings,
        stream_name,
    )
    worker.run_once()
    assert stream.xpending(stream_name, "worker", bad) == 0
    assert (
        redis_client.xrange(stream_name + ":dlq")[0][1]["error"]
        == "ValidationError: invalid event"
    )
    key = stream.xadd(stream_name, event.stream_fields())
    stream.xreadgroup(stream_name, "worker", "dead", 1, 1)
    redis_client.xclaim(stream_name, "worker", "dead", 0, [key], idle=1000, justid=True)
    worker.next_reclaim = 0
    worker.run_once()
    assert (
        repository.get_document(event.tenant_id, event.document_id).status == "failed"
    )
    assert redis_client.xrange(stream_name + ":dlq")[-1][1]["attempts"] == "2"
    assert stream.xpending(stream_name, "worker", key) == 0
