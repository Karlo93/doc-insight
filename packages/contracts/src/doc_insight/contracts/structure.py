"""Structured output and the three replaceable providers used in M2."""

from collections import Counter
from typing import Protocol

from doc_insight.contracts.extraction import ExtractedDocument, Page
from pydantic import BaseModel, Field, computed_field


class LanguageGuess(BaseModel):
    language: str
    confidence: float = Field(ge=0, le=1)


class Chunk(BaseModel):
    text: str
    page: int
    ord: int
    char_start: int
    char_end: int
    token_count: int


class Entity(BaseModel):
    text: str
    label: str
    page: int
    char_start: int
    char_end: int
    count: int = 1


class Document(ExtractedDocument):
    chunks: list[Chunk]
    entities: list[Entity]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def language(self) -> str:
        votes: Counter[str] = Counter()
        for page in self.pages:
            votes[page.language] += page.char_count
        return next(
            (code for code, count in votes.items() if count > votes.total() / 2),
            "und",
        )


class LanguageDetector(Protocol):
    def detect(self, text: str) -> LanguageGuess: ...


class NerExtractor(Protocol):
    def extract(self, page: Page) -> list[Entity]: ...


class Tokenizer(Protocol):
    def encode(self, text: str) -> list[tuple[int, int]]: ...
