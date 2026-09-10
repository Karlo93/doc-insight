from io import BytesIO
from uuid import uuid4

import pytest
from doc_insight.contracts.ingest import DocumentUploaded
from doc_insight.ingest.adapters import RedisPublisher, S3ObjectStore
from doc_insight.testing.ingest import InMemoryObjectStore, RecordingPublisher


@pytest.fixture(params=["fake", pytest.param("s3", marks=pytest.mark.integration)])
def object_store(request):
    if request.param == "fake":
        yield InMemoryObjectStore()
        return
    store = request.getfixturevalue("s3")
    keys = []
    original = store.put

    def track(key, *args):
        keys.append(key)
        original(key, *args)

    store.put = track
    yield store
    for key in keys:
        store.client.delete_object(Bucket=store.bucket, Key=key)


def test_object_store_contract(object_store):
    # The fake and real object stores must agree on existence, streaming and object identity.
    key = f"test-{uuid4().hex}/{'a' * 64}"
    assert not object_store.exists(key)
    data = b"%PDF-1.7\ncontract"
    object_store.put(key, BytesIO(data), len(data), "application/pdf")
    assert object_store.exists(key)
    with object_store.get(key) as stream:
        assert stream.read(5) + stream.read() == data
    object_store.put(key, BytesIO(data), len(data), "application/pdf")
    with object_store.get(key) as stream:
        assert stream.read() == data
    if isinstance(object_store, S3ObjectStore):
        metadata = object_store.client.head_object(Bucket=object_store.bucket, Key=key)
        assert metadata["ServerSideEncryption"] == "AES256"
        assert metadata["ContentType"] == "application/pdf"


@pytest.fixture(params=["fake", pytest.param("redis", marks=pytest.mark.integration)])
def publisher(request):
    if request.param == "fake":
        fake = RecordingPublisher()
        yield fake, lambda event: [e.stream_fields() for e in fake.events]
        return
    client = request.getfixturevalue("redis_client")
    published_ids = []

    def read(event):
        entries = [
            (key, fields)
            for key, fields in client.xrange("di:documents")
            if fields["event_id"] == str(event.event_id)
        ]
        published_ids.extend(key for key, _ in entries)
        return [fields for _, fields in entries]

    yield RedisPublisher(client), read
    if published_ids:
        client.xdel("di:documents", *published_ids)


def test_event_publisher_contract(publisher):
    adapter, read = publisher
    event = DocumentUploaded(
        tenant_id=uuid4().hex,
        document_id=uuid4(),
        sha256="a" * 64,
        object_key="demo/" + "a" * 64,
        media_type="application/pdf",
        size_bytes=15,
        traceparent="00-" + "1" * 32 + "-" + "2" * 16 + "-01",
    )
    adapter.publish(event)
    adapter.publish(event)
    assert read(event) == [event.stream_fields(), event.stream_fields()]
    assert all(isinstance(value, str) for value in event.stream_fields().values())
    assert (
        "traceparent"
        not in event.model_copy(update={"traceparent": None}).stream_fields()
    )
