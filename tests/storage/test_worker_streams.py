from uuid import uuid4

import pytest
from doc_insight.testing.streams import InMemoryStreamConsumer
from doc_insight.worker.streams import RedisStreamConsumer


@pytest.fixture(params=["fake", pytest.param("redis", marks=pytest.mark.integration)])
def stream_adapter(request):
    if request.param == "fake":
        yield InMemoryStreamConsumer(), None
    else:
        client = request.getfixturevalue("redis_client")
        yield RedisStreamConsumer(client), client


def test_stream_contract(stream_adapter):
    # Run the same delivery and recovery contract against the fake and Redis adapter.
    adapter, client = stream_adapter
    stream, group, consumer = f"test:{uuid4().hex}", "contract", uuid4().hex
    try:
        first = adapter.xadd(stream, {"event_id": "first"})
        adapter.xgroup_create(stream, group)
        adapter.xgroup_create(stream, group)
        second = adapter.xadd(stream, {"event_id": "second"})
        entries = adapter.xreadgroup(stream, group, "dead", 1, 1)
        assert [(e.id, e.fields) for e in entries] == [(first, {"event_id": "first"})]
        assert adapter.xpending(stream, group, first) == 1
        assert adapter.xpending(stream, group, second) == 0
        assert adapter.xreadgroup(stream, group, "alive", 2, 1)[0].id == second
        assert adapter.xreadgroup(stream, group, "alive", 2, 1) == []
        assert adapter.xautoclaim(stream, group, consumer, 60000, "0-0", 1) == (
            "0-0",
            [],
        )
        cursor, claimed = adapter.xautoclaim(stream, group, consumer, 0, "0-0", 1)
        assert [e.id for e in claimed] == [first]
        assert cursor == second
        assert adapter.xpending(stream, group, first) == 2
        cursor, claimed = adapter.xautoclaim(stream, group, consumer, 0, cursor, 1)
        assert cursor == "0-0" and claimed[0].id == second
        adapter.xack(stream, group, first)
        adapter.xack(stream, group, first)
        assert adapter.xpending(stream, group, first) == 0
        adapter.heartbeat(consumer)
        if client:
            assert 0 < client.ttl(f"di:worker:{consumer}") <= 30
        else:
            assert adapter.heartbeats[consumer] == 30000
    finally:
        if client:
            client.delete(stream, f"di:worker:{consumer}")


def test_fake_clock_and_scan_cursor():
    adapter = InMemoryStreamConsumer()
    adapter.xgroup_create("s", "g")
    keys = [adapter.xadd("s", {"n": str(n)}) for n in range(12)]
    adapter.xreadgroup("s", "g", "dead", 12, 1)
    assert adapter.xautoclaim("s", "g", "new", 100, "0-0", 1) == (keys[10], [])
    adapter.now_ms = 100
    _, messages = adapter.xautoclaim("s", "g", "new", 100, keys[10], 1)
    assert messages[0].id == keys[10]
    assert adapter.groups["s", "g"].pending[keys[10]].consumer == "new"
