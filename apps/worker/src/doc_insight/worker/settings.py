"""Process-wide configuration for extraction and structured analysis."""

from functools import cache
from typing import Self

from doc_insight.contracts.settings import EmbeddingSettings
from pydantic import Field, model_validator


class Settings(EmbeddingSettings):
    ocr_min_chars: int = Field(default=20, ge=0)
    ocr_dpi: int = Field(default=200, gt=0)
    ocr_langs: str = "eng+hrv"
    tesseract_cmd: str = "tesseract"
    languages: str = "en,hr,de"
    lang_sample_chars: int = Field(default=4000, gt=0)
    lang_min_confidence: float = Field(default=0.5, ge=0, le=1)
    ner_max_chars: int = Field(default=100_000, ge=0)
    ner_models: dict[str, str] = Field(
        default_factory=lambda: {"en": "en_core_web_sm", "hr": "hr_core_news_sm"}
    )
    # MiniLM's 128-token sentence input includes two special tokens.
    chunk_tokens: int = Field(default=120, gt=0, le=126)
    chunk_overlap: int = Field(default=24, ge=0)
    database_url: str = "postgresql+psycopg://di_app:di_app@localhost:5432/di"
    migration_database_url: str = "postgresql+psycopg://di:di@localhost:5432/di"

    @model_validator(mode="after")
    def valid_overlap(self) -> Self:
        if self.chunk_overlap >= self.chunk_tokens:
            raise ValueError("chunk_overlap must be smaller than chunk_tokens")
        return self


@cache
def get_settings() -> Settings:
    return Settings()
