"""The embedding provider returns one vector per input, preserving input order."""

from typing import Protocol


class Embedder(Protocol):
    @property
    def dimension(self) -> int: ...

    @property
    def model_id(self) -> str: ...

    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...
