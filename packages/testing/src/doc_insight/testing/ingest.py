"""Isolated object bytes and recorded event delivery for offline tests."""

from io import BytesIO
from typing import BinaryIO

from doc_insight.contracts.ingest import DocumentUploaded


class InMemoryObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, stream: BinaryIO, size: int, media_type: str) -> None:
        data = stream.read()
        if len(data) != size:
            raise ValueError("Object size mismatch")
        self.objects[key] = data

    def get(self, key: str) -> BinaryIO:
        return BytesIO(self.objects[key])

    def exists(self, key: str) -> bool:
        return key in self.objects


class RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[DocumentUploaded] = []

    def publish(self, event: DocumentUploaded) -> None:
        self.events.append(event.model_copy(deep=True))
