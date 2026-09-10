"""Process-wide configuration for extraction and structured analysis."""

from functools import cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DI_")

    ocr_min_chars: int = Field(default=20, ge=0)
    ocr_dpi: int = Field(default=200, gt=0)
    ocr_langs: str = "eng+hrv"
    tesseract_cmd: str = "tesseract"
    languages: str = "en,hr,de"
    lang_sample_chars: int = Field(default=4000, gt=0)
    lang_min_confidence: float = Field(default=0.5, ge=0, le=1)
    ner_max_chars: int = Field(default=100_000, ge=0)
    ner_models: dict[str, str] = {"en": "en_core_web_sm", "hr": "hr_core_news_sm"}
    # MiniLM's 128-token sentence input includes two special tokens.
    chunk_tokens: int = Field(default=120, gt=0, le=126)
    chunk_overlap: int = Field(default=24, ge=0)
    embed_model: Literal[
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    ] = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embed_batch: int = Field(default=32, gt=0)
    embed_onnx_repo: Literal["Qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q"] = (
        "Qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q"
    )
    embed_revision: str = "faf4aa4225822f3bc6376869cb1164e8e3feedd0"
    tokenizer_revision: str = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
    model_cache: Path = Path.home() / ".cache" / "doc-insight" / "models"
    database_url: str = "postgresql+psycopg://di_app:di_app@localhost:5432/di"
    migration_database_url: str = "postgresql+psycopg://di:di@localhost:5432/di"

    @property
    def embed_dim(self) -> int:
        return 384

    @model_validator(mode="after")
    def valid_overlap(self) -> Self:
        if self.chunk_overlap >= self.chunk_tokens:
            raise ValueError("chunk_overlap must be smaller than chunk_tokens")
        self.model_cache = self.model_cache.expanduser().resolve()
        return self


@cache
def get_settings() -> Settings:
    return Settings()
