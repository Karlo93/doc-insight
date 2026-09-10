"""One embedding profile shared by worker and query settings."""

from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EmbeddingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DI_")

    embed_model: Literal[
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    ] = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embed_batch: int = Field(default=32, gt=0)
    embed_threads: int = Field(default=2, ge=1, le=16)
    embed_onnx_repo: Literal["Qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q"] = (
        "Qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q"
    )
    embed_revision: str = "faf4aa4225822f3bc6376869cb1164e8e3feedd0"
    tokenizer_revision: str = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
    model_cache: Path = Path.home() / ".cache" / "doc-insight" / "models"

    @property
    def embed_dim(self) -> int:
        return 384

    @model_validator(mode="after")
    def resolve_cache(self) -> Self:
        self.model_cache = self.model_cache.expanduser().resolve()
        return self
