"""Small deterministic providers for testing the pipeline without downloads."""

import re
from dataclasses import dataclass

from doc_insight.contracts.extraction import Page
from doc_insight.contracts.structure import Entity, LanguageGuess


@dataclass
class FakeLanguageDetector:
    language: str = "en"
    confidence: float = 1

    def detect(self, text: str) -> LanguageGuess:
        return LanguageGuess(
            language=self.language if text.strip() else "und",
            confidence=self.confidence if text.strip() else 0,
        )


class FakeNerExtractor:
    def extract(self, page: Page) -> list[Entity]:
        if page.language not in ("en", "hr"):
            return []
        names = [
            ("Alice Johnson", "PER"),
            ("London", "LOC"),
            ("Marko Marić", "PER"),
            ("Zagrebu", "LOC"),
        ]
        return [
            Entity(
                text=match.group(),
                label=label,
                page=page.number,
                char_start=match.start(),
                char_end=match.end(),
            )
            for name, label in names
            for match in re.finditer(re.escape(name), page.text)
        ]


class FakeTokenizer:
    def encode(self, text: str) -> list[tuple[int, int]]:
        return [(match.start(), match.end()) for match in re.finditer(r"\S+", text)]
