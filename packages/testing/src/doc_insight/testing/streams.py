"""Deterministic pending entries and delivery counts; advance the clock explicitly."""

from dataclasses import dataclass, field

from doc_insight.contracts.streams import StreamMessage


@dataclass
class Pending:
    consumer: str
    delivered_ms: int
    attempts: int = 1


@dataclass
class Group:
    offset: int = 0
    pending: dict[str, Pending] = field(default_factory=dict)


class InMemoryStreamConsumer:
    def __init__(self) -> None:
        self.now_ms = 0
        self.streams: dict[str, list[StreamMessage]] = {}
        self.groups: dict[tuple[str, str], Group] = {}
        self.heartbeats: dict[str, int] = {}

    def xgroup_create(self, stream: str, group: str) -> None:
        self.streams.setdefault(stream, [])
        self.groups.setdefault((stream, group), Group())

    def xadd(self, stream: str, fields: dict[str, str]) -> str:
        entries = self.streams.setdefault(stream, [])
        key = f"{len(entries) + 1}-0"
        entries.append(StreamMessage(key, fields.copy()))
        return key

    def xreadgroup(
        self, stream: str, group: str, consumer: str, count: int, block_ms: int
    ) -> list[StreamMessage]:
        state = self.groups[stream, group]
        entries = self.streams[stream][state.offset : state.offset + count]
        for entry in entries:
            state.pending[entry.id] = Pending(consumer, self.now_ms)
        state.offset += len(entries)
        return [StreamMessage(entry.id, entry.fields.copy()) for entry in entries]

    def xack(self, stream: str, group: str, message_id: str) -> None:
        self.groups[stream, group].pending.pop(message_id, None)

    def xpending(self, stream: str, group: str, message_id: str) -> int:
        pending = self.groups[stream, group].pending.get(message_id)
        return pending.attempts if pending else 0

    def xautoclaim(
        self,
        stream: str,
        group: str,
        consumer: str,
        min_idle_ms: int,
        start: str,
        count: int,
    ) -> tuple[str, list[StreamMessage]]:
        pending = self.groups[stream, group].pending
        entries = [
            e
            for e in self.streams[stream]
            if e.id in pending and self._id(e.id) >= self._id(start)
        ]
        claimed = []
        scanned = 0
        for entry in entries:
            scanned += 1
            state = pending[entry.id]
            if self.now_ms - state.delivered_ms >= min_idle_ms:
                state.consumer, state.delivered_ms = consumer, self.now_ms
                state.attempts += 1
                claimed.append(StreamMessage(entry.id, entry.fields.copy()))
            if len(claimed) == count or scanned == count * 10:
                break
        cursor = entries[scanned].id if scanned < len(entries) else "0-0"
        return cursor, claimed

    @staticmethod
    def _id(value: str) -> tuple[int, ...]:
        return tuple(map(int, value.split("-")))

    def heartbeat(self, consumer: str) -> None:
        self.heartbeats[consumer] = self.now_ms + 30_000
