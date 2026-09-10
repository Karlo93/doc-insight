import asyncio
import os
from uuid import uuid4

import httpx
import pytest
from doc_insight.contracts.gateway import BackendUnavailable, Identity
from doc_insight.gateway.main import create_app
from doc_insight.gateway.rate_limit import RedisRateLimiter, bucket_key
from doc_insight.testing.gateway import FakeRateLimiter
from redis.asyncio import Redis
from redis.exceptions import ConnectionError

pytestmark = pytest.mark.anyio


@pytest.fixture(params=["fake", pytest.param("redis", marks=pytest.mark.integration)])
async def limiter(request):
    identity = Identity("test-" + uuid4().hex, "alice")
    if request.param == "fake":
        yield FakeRateLimiter(rps=0.01, burst=7), identity
    else:
        async with Redis.from_url(os.environ["DI_REDIS_URL"]) as redis:
            yield RedisRateLimiter(redis, rps=0.01, burst=7), identity
            for other in (
                identity,
                Identity(identity.tenant, "bob"),
                Identity(identity.tenant + "b", "alice"),
            ):
                await redis.delete(bucket_key(other))


async def test_bucket_contract_atomic_and_scoped(limiter):
    provider, identity = limiter
    results = await asyncio.gather(*[provider.consume(identity) for _ in range(50)])
    assert sum(result.allowed for result in results) == 7
    assert sorted(result.remaining for result in results if result.allowed) == list(
        range(7)
    )
    assert all(result.retry_after >= 1 for result in results if not result.allowed)
    assert (await provider.consume(Identity(identity.tenant, "bob"))).allowed
    assert (await provider.consume(Identity(identity.tenant + "b", "alice"))).allowed
    assert await provider.ready()


async def test_refill_capacity_and_backwards_clock():
    clock = [0.0]
    limiter = FakeRateLimiter(rps=2, burst=2, clock=lambda: clock[0])
    identity = Identity("demo", "alice")
    assert (await limiter.consume(identity)).allowed
    assert (await limiter.consume(identity)).allowed
    assert not (await limiter.consume(identity)).allowed
    clock[0] = 0.25
    assert not (await limiter.consume(identity)).allowed
    clock[0] = 0.5
    assert (await limiter.consume(identity)).allowed
    clock[0] = -1
    assert not (await limiter.consume(identity)).allowed
    clock[0] = 100
    assert (await limiter.consume(identity)).remaining == 1


async def test_redis_failures_translate(monkeypatch):
    async def fail(*args, **kwargs):
        raise ConnectionError("private host")

    async with Redis() as redis:
        monkeypatch.setattr(redis, "eval", fail)
        monkeypatch.setattr(redis, "ping", fail)
        limiter = RedisRateLimiter(redis, 5, 10)
        with pytest.raises(BackendUnavailable):
            await limiter.consume(Identity("demo", "alice"))
        assert not await limiter.ready()


@pytest.mark.integration
async def test_real_redis_fifty_concurrent_http_requests(gateway, token):
    tenant = "test-" + uuid4().hex
    identity = Identity(tenant, "alice")
    async with Redis.from_url(os.environ["DI_REDIS_URL"]) as redis:
        gateway.limiter = RedisRateLimiter(redis, rps=0.01, burst=7)
        app = create_app(gateway)
        try:
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://gateway"
                ) as client,
            ):
                credential = token({"tenant": tenant})
                responses = await asyncio.gather(
                    *[
                        client.post(
                            "/query", headers={"authorization": "Bearer " + credential}
                        )
                        for _ in range(50)
                    ]
                )
            assert sum(r.status_code == 200 for r in responses) == 7
            assert sum(r.status_code == 429 for r in responses) == 43
            assert 0 < await redis.pttl(bucket_key(identity)) <= 700000
        finally:
            await redis.delete(bucket_key(identity))


@pytest.mark.integration
async def test_real_redis_refill_without_sleep():
    identity = Identity("test-" + uuid4().hex, "alice")
    async with Redis.from_url(os.environ["DI_REDIS_URL"]) as redis:
        limiter = RedisRateLimiter(redis, rps=2, burst=3)
        key = bucket_key(identity)
        try:
            await limiter.consume(identity)
            seconds, micros = await redis.time()
            now = seconds + micros / 1_000_000
            await redis.hset(key, mapping={"tokens": "0", "updated": str(now - 10)})
            assert (await limiter.consume(identity)).remaining == 2
            await redis.hset(key, mapping={"tokens": "0", "updated": str(now + 100)})
            assert not (await limiter.consume(identity)).allowed
        finally:
            await redis.delete(key)
