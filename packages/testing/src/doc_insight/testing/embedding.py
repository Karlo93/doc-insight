"""Deterministic vectors and a lexical baseline; neither loads a model."""

import hashlib
import re
import struct
from dataclasses import dataclass
from math import sqrt


def unit(values: list[float]) -> list[float]:
    norm = sqrt(sum(value * value for value in values))
    return (
        [value / norm for value in values]
        if norm
        else [1.0] + [0.0] * (len(values) - 1)
    )


@dataclass
class FakeEmbedder:
    dimension: int = 384

    def __post_init__(self) -> None:
        if self.dimension < 1:
            raise ValueError("Embedding dimension must be positive")

    @property
    def model_id(self) -> str:
        return "fake/hash"

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            digest = hashlib.shake_256(text.encode("utf-8")).digest(2 * self.dimension)
            values = struct.unpack(f"!{self.dimension}H", digest)
            vectors.append(unit([value / 32767.5 - 1 for value in values]))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed_passages([text])[0]


class KeywordEmbedder(FakeEmbedder):
    @property
    def model_id(self) -> str:
        return "baseline/keywords"

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            counts = [0.0] * self.dimension
            for word in re.findall(r"\w+", text.casefold()):
                digest = hashlib.blake2b(word.encode("utf-8"), digest_size=8).digest()
                counts[int.from_bytes(digest) % self.dimension] += 1
            vectors.append(unit(counts))
        return vectors
