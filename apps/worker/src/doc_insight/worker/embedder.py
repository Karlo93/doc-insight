"""Pinned CPU ONNX inference; validate the complete input before FastEmbed can truncate it."""

from dataclasses import dataclass
from functools import cache
from math import sqrt
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

from doc_insight.contracts.settings import EmbeddingSettings
from doc_insight.worker.providers import HfTokenizer
from huggingface_hub import snapshot_download

if TYPE_CHECKING:
    from fastembed import TextEmbedding

MODEL_LOCK = Lock()


@cache
def _model(
    model: str, repo: str, revision: str, cache_dir: Path, threads: int
) -> "TextEmbedding":
    # Importing ONNX probes hardware; text-only commands must not initialize it.
    from fastembed import TextEmbedding

    path = snapshot_download(
        repo,
        revision=revision,
        cache_dir=cache_dir,
        allow_patterns=["*.json", "model_optimized.onnx"],
    )
    return TextEmbedding(
        model_name=model,
        cache_dir=str(cache_dir),
        specific_model_path=path,
        providers=["CPUExecutionProvider"],
        threads=threads,
    )


@dataclass
class FastEmbedEmbedder:
    settings: EmbeddingSettings

    @property
    def dimension(self) -> int:
        return self.settings.embed_dim

    @property
    def model_id(self) -> str:
        return self.settings.embed_model

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        tokenizer = HfTokenizer(self.settings)
        if any(len(tokenizer.encode(text)) > 126 for text in texts):
            raise ValueError(
                "MiniLM input exceeds 126 content tokens; refusing truncation"
            )
        # functools.cache alone permits duplicate construction on concurrent cold calls.
        with MODEL_LOCK:
            model = _model(
                self.model_id,
                self.settings.embed_onnx_repo,
                self.settings.embed_revision,
                self.settings.model_cache,
                self.settings.embed_threads,
            )
        # MiniLM uses identical query/passage formatting, without prefixes.
        return [
            (vector / sqrt(float(vector @ vector))).tolist()
            for vector in model.embed(texts, batch_size=self.settings.embed_batch)
        ]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_passages([text])[0]
