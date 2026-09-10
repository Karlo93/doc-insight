"""Process-wide configuration for extraction and structured analysis."""

from functools import cache
from typing import Self

from doc_insight.contracts.settings import EmbeddingSettings
from pydantic import Field, SecretStr, model_validator


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

    redis_url: str = "redis://127.0.0.1:6379/0"
    worker_group: str = Field(default="worker", min_length=1, pattern=r"^\S+$")
    worker_block_ms: int = Field(default=1000, gt=0, le=10000)
    worker_batch: int = Field(default=1, gt=0, le=100)
    worker_reclaim_seconds: float = Field(default=30, gt=0)
    worker_claim_min_idle_ms: int = Field(default=300000, gt=0)
    worker_max_attempts: int = Field(default=5, gt=0)
    s3_endpoint: str = "http://127.0.0.1:9000"
    s3_region: str = "us-east-1"
    s3_bucket: str = "documents"
    s3_access_key: SecretStr = SecretStr("")
    s3_secret_key: SecretStr = SecretStr("")
    s3_use_ssl: bool = False

    @model_validator(mode="after")
    def valid_overlap(self) -> Self:
        if self.chunk_overlap >= self.chunk_tokens:
            raise ValueError("chunk_overlap must be smaller than chunk_tokens")
        return self


@cache
def get_settings() -> Settings:
    return Settings()
