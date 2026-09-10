"""Validated once at service startup."""

from functools import cache
from pathlib import Path

from doc_insight.contracts.settings import EmbeddingSettings
from pydantic import Field, SecretStr


class Settings(EmbeddingSettings):
    database_url: str = "postgresql+psycopg://di_app@localhost:5432/di"
    openai_model: str = Field(default="gpt-4.1-mini-2025-04-14", min_length=1)
    openai_api_key: SecretStr = SecretStr("")
    openai_api_key_file: Path | None = None
    llm_max_output_tokens: int = Field(default=700, ge=64, le=4096)
    llm_concurrency: int = Field(default=4, ge=1, le=32)
    llm_daily_tokens: int = Field(default=250_000, ge=0)
    llm_timeout_seconds: float = Field(default=10, gt=0, allow_inf_nan=False)
    llm_breaker_failures: int = Field(default=3, ge=1)
    llm_breaker_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)
    abstain_threshold: float = Field(default=0.6, ge=0, le=1)
    rrf_k: int = Field(default=60, ge=1)
    query_top_k_max: int = Field(default=20, ge=1, le=20)

    def api_key(self) -> str:
        """Read a mounted secret once at runtime creation, never serialize its value."""
        if self.openai_api_key_file is not None:
            value = self.openai_api_key_file.read_text(encoding="utf-8-sig").strip()
            if value:
                return value
        return self.openai_api_key.get_secret_value()


@cache
def get_settings() -> Settings:
    return Settings()
