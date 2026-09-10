"""Select a generator per request without storing mutable provider reporting state."""

import httpx
from doc_insight.contracts.query import Generation, GenerationInfo, Generator
from doc_insight.query.extractive import ExtractiveGenerator


class FallbackGenerator:
    def __init__(self, primary: Generator | None = None, model: str = "") -> None:
        self.primary, self.model = primary, model
        self.fallback = ExtractiveGenerator()

    def generate(
        self, question: str, passages: list[str]
    ) -> tuple[Generation, GenerationInfo]:
        if self.primary is not None and passages:
            try:
                return self.primary.generate(question, passages), GenerationInfo(
                    provider="mistral", model=self.model
                )
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
                pass
        return self.fallback.generate(question, passages), GenerationInfo(
            provider="extractive", model="sentence-window-v1"
        )
