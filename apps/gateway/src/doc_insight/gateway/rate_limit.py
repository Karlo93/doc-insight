"""Atomic token bucket using Redis server time, shared across gateway processes."""

from collections.abc import Awaitable
from hashlib import sha256
from typing import cast

from doc_insight.contracts.gateway import BackendUnavailable, Identity, RateDecision
from redis.asyncio import Redis
from redis.exceptions import RedisError

BUCKET = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
local rate, burst = tonumber(ARGV[1]), tonumber(ARGV[2])
local state = redis.call('HMGET', KEYS[1], 'tokens', 'updated')
local tokens = tonumber(state[1]) or burst
local updated = tonumber(state[2]) or now
tokens = math.min(burst, tokens + math.max(0, now - updated) * rate)
local allowed, retry = 0, 0
if tokens >= 1 then
    tokens = tokens - 1
    allowed = 1
else
    retry = math.ceil((1 - tokens) / rate)
end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'updated', math.max(updated, now))
redis.call('PEXPIRE', KEYS[1], math.max(1, math.ceil(burst / rate * 1000)))
return {allowed, math.floor(tokens), retry}
"""


def bucket_key(identity: Identity) -> str:
    digest = sha256(f"{identity.tenant}\0{identity.user}".encode()).hexdigest()
    return f"di:rate:{digest}"


class RedisRateLimiter:
    def __init__(self, redis: Redis, rps: float, burst: int) -> None:
        self.redis, self.rps, self.burst = redis, rps, burst

    async def consume(self, identity: Identity) -> RateDecision:
        try:
            result = await cast(
                Awaitable[list[int]],
                self.redis.eval(
                    BUCKET, 1, bucket_key(identity), str(self.rps), str(self.burst)
                ),
            )
            return RateDecision(bool(result[0]), result[1], result[2])
        except RedisError:
            raise BackendUnavailable from None

    async def ready(self) -> bool:
        try:
            return bool(await self.redis.ping())
        except RedisError:
            return False
