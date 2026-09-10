"""Decode Redis responses once, at the service boundary."""

from typing import cast

from doc_insight.contracts.streams import StreamMessage
from redis import Redis
from redis.exceptions import ResponseError


class RedisStreamConsumer:
    def __init__(self, client: Redis, heartbeat_seconds: int = 30) -> None:
        self.client = client
        self.heartbeat_seconds = heartbeat_seconds

    def xgroup_create(self, stream: str, group: str) -> None:
        try:
            self.client.xgroup_create(stream, group, id="0-0", mkstream=True)
        except ResponseError as error:
            if not str(error).startswith("BUSYGROUP"):
                raise

    def xreadgroup(
        self, stream: str, group: str, consumer: str, count: int, block_ms: int
    ) -> list[StreamMessage]:
        rows = cast(
            list[tuple[str, list[tuple[str, dict[str, str]]]]],
            self.client.xreadgroup(
                group, consumer, {stream: ">"}, count=count, block=block_ms
            ),
        )
        return [
            StreamMessage(key, fields) for _, entries in rows for key, fields in entries
        ]

    def xack(self, stream: str, group: str, message_id: str) -> None:
        self.client.xack(stream, group, message_id)

    def xadd(self, stream: str, fields: dict[str, str]) -> str:
        return cast(str, self.client.xadd(stream, {k: v for k, v in fields.items()}))

    def xautoclaim(
        self,
        stream: str,
        group: str,
        consumer: str,
        min_idle_ms: int,
        start: str,
        count: int,
    ) -> tuple[str, list[StreamMessage]]:
        result = cast(
            tuple[str, list[tuple[str, dict[str, str]]], list[str]],
            self.client.xautoclaim(
                stream, group, consumer, min_idle_ms, start_id=start, count=count
            ),
        )
        return str(result[0]), [StreamMessage(key, fields) for key, fields in result[1]]

    def xpending(self, stream: str, group: str, message_id: str) -> int:
        rows = cast(
            list[dict[str, int]],
            self.client.xpending_range(stream, group, message_id, message_id, 1),
        )
        return int(rows[0]["times_delivered"]) if rows else 0

    def heartbeat(self, consumer: str) -> None:
        self.client.set(f"di:worker:{consumer}", "ready", ex=self.heartbeat_seconds)
