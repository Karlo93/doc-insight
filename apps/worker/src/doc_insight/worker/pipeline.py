"""One sequential extract/analyze/embed/store path for the CLI and consumer."""

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from doc_insight.contracts.embedding import Embedder
from doc_insight.contracts.storage import DocumentRepository, StoredDocument
from doc_insight.contracts.structure import LanguageDetector, NerExtractor, Tokenizer
from doc_insight.observability import stage
from doc_insight.worker.embedding import embed_document
from doc_insight.worker.extraction import extract
from doc_insight.worker.settings import Settings
from doc_insight.worker.structure import analyze


@dataclass
class Pipeline:
    """Shared CLI/consumer pipeline with model providers owned by the caller.

    Extraction and inference finish before the repository's atomic write. Timing
    stages emit telemetry; ``index(report=True)`` additionally prints CLI timings.
    """

    settings: Settings
    detector: LanguageDetector
    ner: NerExtractor
    tokenizer: Tokenizer
    embedder: Embedder

    def index(
        self,
        path: Path,
        tenant: str,
        repository: DocumentRepository,
        filename: str | None = None,
        *,
        report: bool = False,
    ) -> StoredDocument:
        times = [perf_counter()]
        with stage("extract"):
            extracted = extract(path)
        times.append(perf_counter())
        with stage("analyze"):
            document = analyze(
                extracted, self.detector, self.ner, self.tokenizer, self.settings
            )
        times.append(perf_counter())
        with stage("embed"):
            embedded = embed_document(document, self.embedder)
        times.append(perf_counter())
        with stage("store"):
            stored = repository.upsert_document(tenant, filename or path.name, embedded)
        times.append(perf_counter())
        if report:
            print(
                " ".join(
                    f"{name}={end - start:.3f}s"
                    for name, start, end in zip(
                        ("extract", "analyze", "embed", "store"), times, times[1:]
                    )
                )
            )
        return stored
