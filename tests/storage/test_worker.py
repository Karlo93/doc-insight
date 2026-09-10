from hashlib import sha256
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError
from doc_insight.contracts.extraction import PIPELINE_VERSION
from doc_insight.testing.embedding import FakeEmbedder
from doc_insight.testing.ingest import InMemoryObjectStore
from doc_insight.testing.storage import InMemoryRepository
from doc_insight.testing.streams import InMemoryStreamConsumer
from doc_insight.testing.structure import (
    FakeLanguageDetector,
    FakeNerExtractor,
    FakeTokenizer,
)
from doc_insight.worker.pipeline import Pipeline
from doc_insight.worker.processing import DocumentProcessor
from doc_insight.worker.service import DLQ, STREAM, Worker
from doc_insight.worker.settings import Settings
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import OperationalError

FIXTURE = Path(__file__).parents[1] / "fixtures" / "text_hr.pdf"


@pytest.fixture
def setup_worker():
    settings = Settings(
        worker_batch=2, worker_claim_min_idle_ms=100, worker_reclaim_seconds=1
    )
    repository, objects, stream = (
        InMemoryRepository(384),
        InMemoryObjectStore(),
        InMemoryStreamConsumer(),
    )
    pipeline = Pipeline(
        settings,
        FakeLanguageDetector("hr"),
        FakeNerExtractor(),
        FakeTokenizer(),
        FakeEmbedder(),
    )
    worker = Worker(
        stream,
        DocumentProcessor(repository, objects, pipeline),
        settings,
        "host-1",
        lambda: stream.now_ms / 1000,
    )
    data = FIXTURE.read_bytes()
    digest = sha256(data).hexdigest()
    record = repository.register_upload(
        "demo", "original.pdf", digest, "application/pdf", len(data), f"demo/{digest}"
    )
    event = repository.events[0]
    objects.put(event.object_key, BytesIO(data), len(data), event.media_type)
    message_id = stream.xadd(STREAM, event.stream_fields())
    return worker, record, event, message_id


def test_full_pipeline_ack_duplicate_version_replacement_and_privacy(
    setup_worker, caplog, capsys
):
    # A replay must preserve one complete indexed result before its stream entry is acknowledged.
    worker, record, event, key = setup_worker
    caplog.set_level("INFO")
    worker.run_once()
    repository, stream = worker.processor.repository, worker.stream
    stored = repository.get_document("demo", record.id)
    assert stored.status == "processed" and stored.chunks and stored.entities
    assert stored.filename == "original.pdf" and stored.object_key == event.object_key
    assert stored.pipeline_version == PIPELINE_VERSION
    assert stream.xpending(STREAM, "worker", key) == 0
    assert stream.heartbeats[worker.consumer] == 30000
    sentence = stored.chunks[0].text
    assert sentence not in caplog.text and "original.pdf" not in caplog.text
    assert capsys.readouterr().out == ""
    process = worker.processor.process
    worker.processor.process = Mock(side_effect=AssertionError("duplicate reprocessed"))
    duplicate = stream.xadd(STREAM, event.stream_fields())
    worker.run_once()
    worker.processor.process.assert_not_called()
    assert stream.xpending(STREAM, "worker", duplicate) == 0
    repository.documents["demo", record.id].pipeline_version = "old"
    worker.processor.process = Mock(wraps=process)
    stream.xadd(STREAM, event.stream_fields())
    worker.run_once()
    worker.processor.process.assert_called_once()
    revised = repository.get_document("demo", record.id)
    assert revised.pipeline_version == PIPELINE_VERSION
    assert len(revised.chunks) == len(stored.chunks)
    assert len(repository.documents) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"event_id": None},
        {"type": "bad"},
        {"tenant_id": "../demo"},
        {"size_bytes": "-1"},
        {"sha256": "bad"},
        {"object_key": "other/key"},
        {"occurred_at": "2026-09-10T10:00:00"},
        {"media_type": "text/plain"},
    ],
)
def test_malformed_immediate_dlq_without_status_change(setup_worker, change):
    worker, record, _event, key = setup_worker
    fields = worker.stream.streams[STREAM][0].fields
    for name, value in change.items():
        if value is None:
            fields.pop(name)
        else:
            fields[name] = value
    worker.run_once()
    assert worker.stream.xpending(STREAM, "worker", key) == 0
    assert (
        worker.stream.streams[DLQ][0].fields["error"]
        == "ValidationError: invalid event"
    )
    assert (
        worker.processor.repository.get_document("demo", record.id).status == "uploaded"
    )


@pytest.mark.parametrize(
    "change",
    [
        {"tenant_id": "other"},
        {"document_id": str(uuid4())},
        {"size_bytes": "1"},
        {"sha256": "a" * 64},
    ],
)
def test_wrong_tenant_or_metadata_cannot_read_object_or_change_row(
    setup_worker, change
):
    worker, record, _event, key = setup_worker
    fields = worker.stream.streams[STREAM][0].fields
    fields.update(change)
    fields["object_key"] = f"{fields['tenant_id']}/{fields['sha256']}"
    worker.processor.objects.get = Mock(side_effect=AssertionError("must not read"))
    worker.run_once()
    worker.processor.objects.get.assert_not_called()
    assert (
        worker.processor.repository.get_document("demo", record.id).status == "uploaded"
    )
    assert worker.stream.xpending(STREAM, "worker", key) == 0


def test_poison_is_sanitized_and_failed_before_dlq_ack(setup_worker, caplog):
    worker, record, event, key = setup_worker
    private = "Marko Marić lives in a private document."
    worker.processor.pipeline.embedder.embed_passages = Mock(
        side_effect=RuntimeError(private)
    )
    worker.run_once()
    stored = worker.processor.repository.get_document("demo", record.id)
    assert (
        stored.status == "failed" and stored.error == "RuntimeError: processing failed"
    )
    assert stored.chunks == []
    dead = worker.stream.streams[DLQ][0].fields
    assert dead == dict(event.stream_fields(), error=stored.error, attempts="1")
    assert worker.stream.xpending(STREAM, "worker", key) == 0
    assert private not in caplog.text + stored.error + str(dead)


@pytest.mark.parametrize("boundary", ["get", "upsert_document", "mark_status"])
def test_transient_stays_pending_then_reclaims(setup_worker, boundary):
    worker, record, _event, key = setup_worker
    owner = (
        worker.processor.objects if boundary == "get" else worker.processor.repository
    )
    original = getattr(owner, boundary)
    error = (
        OSError("private")
        if boundary == "get"
        else OperationalError("sql", {}, Exception("private"))
    )
    setattr(owner, boundary, Mock(side_effect=error))
    worker.run_once()
    assert worker.stream.xpending(STREAM, "worker", key) == 1
    assert DLQ not in worker.stream.streams
    setattr(owner, boundary, original)
    worker.stream.now_ms = 1000
    worker.run_once()
    assert worker.stream.xpending(STREAM, "worker", key) == 0
    assert (
        worker.processor.repository.get_document("demo", record.id).status
        == "processed"
    )


def test_attempt_limit_marks_failed_after_all_allowed_attempts(setup_worker):
    worker, record, _event, key = setup_worker
    worker.settings.worker_max_attempts = 2
    worker.processor.objects.get = Mock(side_effect=OSError("unavailable"))
    for time in [0, 1000, 2000]:
        worker.stream.now_ms = time
        worker.run_once()
    assert worker.processor.objects.get.call_count == 2
    assert worker.stream.streams[DLQ][0].fields["attempts"] == "3"
    assert (
        worker.processor.repository.get_document("demo", record.id).status == "failed"
    )
    assert worker.stream.xpending(STREAM, "worker", key) == 0


@pytest.mark.parametrize("after_commit", [False, True])
def test_crash_restart_mid_pipeline_or_after_commit(setup_worker, after_commit):
    worker, record, _event, key = setup_worker

    class Crash(BaseException):
        pass

    owner = worker.stream if after_commit else worker.processor.pipeline.embedder
    method = "xack" if after_commit else "embed_passages"
    original = getattr(owner, method)
    setattr(owner, method, Mock(side_effect=Crash))
    with pytest.raises(Crash):
        worker.run_once()
    assert worker.stream.xpending(STREAM, "worker", key) == 1
    assert worker.processor.repository.get_document("demo", record.id).status == (
        "processed" if after_commit else "processing"
    )
    setattr(owner, method, original)
    worker.stream.now_ms = 1000
    worker.processor.process = Mock(wraps=worker.processor.process)
    restarted = Worker(
        worker.stream, worker.processor, worker.settings, "host-2", worker.clock
    )
    restarted.run_once()
    assert worker.processor.process.call_count == (0 if after_commit else 1)
    assert worker.stream.xpending(STREAM, "worker", key) == 0
    assert (
        worker.processor.repository.get_document("demo", record.id).status
        == "processed"
    )


def test_dlq_failure_never_acknowledges(setup_worker):
    worker, _record, _event, key = setup_worker
    worker.stream.streams[STREAM][0].fields["type"] = "bad"
    worker.stream.xadd = Mock(side_effect=RedisConnectionError("private"))
    with pytest.raises(RedisConnectionError):
        worker.run_once()
    assert worker.stream.xpending(STREAM, "worker", key) == 1


def test_shutdown_finishes_inflight_leaves_fetched_batch_pending(setup_worker):
    worker, record, event, key = setup_worker
    second = worker.stream.xadd(STREAM, event.stream_fields())
    process = worker.processor.process

    def finish_then_stop(*args):
        worker.stopping.set()
        process(*args)

    worker.processor.process = finish_then_stop
    worker.run_once()
    assert (
        worker.processor.repository.get_document("demo", record.id).status
        == "processed"
    )
    assert worker.stream.xpending(STREAM, "worker", key) == 0
    assert worker.stream.xpending(STREAM, "worker", second) == 1
    worker.run_once()
    assert worker.stream.xpending(STREAM, "worker", second) == 1


def test_loop_retries_redis_outage_without_logging_exception(setup_worker, caplog):
    worker, _, _, _ = setup_worker
    worker.stream.heartbeat = Mock(side_effect=RedisConnectionError("private"))
    worker.stopping.wait = Mock(side_effect=lambda _: worker.stopping.set())
    worker.run()
    assert not worker.ready
    assert "private" not in caplog.text
    worker.stopping.wait.assert_called_once()


@pytest.mark.parametrize("failure", ["digest", "size", "missing", "s3"])
def test_invalid_or_unavailable_objects(setup_worker, failure):
    worker, record, event, key = setup_worker
    objects = worker.processor.objects
    if failure in {"digest", "size"}:
        objects.objects[event.object_key] = b"x" * (
            event.size_bytes + (failure == "size")
        )
    elif failure == "missing":
        objects.objects.clear()
    else:
        objects.get = Mock(
            side_effect=ClientError(
                {"Error": {"Code": "ServiceUnavailable"}}, "GetObject"
            )
        )
    worker.run_once()
    assert worker.processor.repository.get_document("demo", record.id).status == (
        "processing" if failure == "s3" else "failed"
    )
    assert worker.stream.xpending(STREAM, "worker", key) == (
        1 if failure == "s3" else 0
    )
