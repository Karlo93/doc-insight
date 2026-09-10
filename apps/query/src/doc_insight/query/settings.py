"""Validated once at service startup."""

from functools import cache

from doc_insight.contracts.settings import EmbeddingSettings
from pydantic import Field, SecretStr


class Settings(EmbeddingSettings):
    database_url: str = "postgresql+psycopg://di_app:di_app@localhost:5432/di"
    llm_model: str = Field(default="mistral-small-latest", min_length=1)
    llm_api_key: SecretStr = SecretStr("")
    llm_timeout_seconds: float = Field(default=10, gt=0, allow_inf_nan=False)
    llm_breaker_failures: int = Field(default=3, ge=1)
    llm_breaker_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)
    abstain_threshold: float = Field(default=0.6, ge=0, le=1)
    rrf_k: int = Field(default=60, ge=1)
    query_top_k_max: int = Field(default=20, ge=1, le=20)


@cache
def get_settings() -> Settings:
    return Settings()
