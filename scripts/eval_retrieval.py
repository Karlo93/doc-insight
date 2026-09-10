"""Compare retrieval against the committed questions; the keyword baseline is offline."""

import argparse
import json
from pathlib import Path

from doc_insight.contracts.embedding import Embedder
from doc_insight.contracts.structure import Tokenizer
from doc_insight.testing.embedding import KeywordEmbedder
from doc_insight.testing.structure import FakeTokenizer
from doc_insight.worker.embedder import FastEmbedEmbedder
from doc_insight.worker.evaluation import EvaluationCase, evaluate
from doc_insight.worker.extraction import extract
from doc_insight.worker.providers import HfTokenizer
from doc_insight.worker.settings import Settings
from doc_insight.worker.structure import chunk_page

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def load_cases(language: str, translated: bool = False) -> list[EvaluationCase]:
    suffix = "_hr" if language == "hr" else ""
    rows = [
        json.loads(line)
        for line in (FIXTURES / f"eval{suffix}.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    return [
        EvaluationCase(
            question=row["question_en" if translated else "question"],
            expected_substring=row["expected_substring"],
        )
        for row in rows
    ]


def report(language: str, provider: str, settings: Settings) -> None:
    embedder: Embedder = KeywordEmbedder(settings.embed_dim)
    tokenizer: Tokenizer = FakeTokenizer()
    if provider == "fastembed":
        embedder, tokenizer = FastEmbedEmbedder(settings), HfTokenizer(settings)
    suffix = "_hr" if language == "hr" else ""
    chunks = []
    for page in extract(FIXTURES / f"text_long{suffix}.pdf").pages:
        chunks.extend(chunk_page(page, tokenizer, settings, len(chunks)))
    translations = (
        [False, True] if language == "hr" and provider == "fastembed" else [False]
    )
    for translated in translations:
        cases = load_cases(language, translated)
        metrics = evaluate(cases, chunks, embedder)
        direction = "en->hr (report only)" if translated else f"{language}->{language}"
        print(
            f"language={direction} | model={embedder.model_id} | "
            f"window={settings.chunk_tokens}/{settings.chunk_overlap} | "
            f"chunks={len(chunks)} | questions={len(cases)} | "
            f"recall@5={metrics.recall_at_5:.3f} | MRR={metrics.mrr:.3f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=["en", "hr"], default="en")
    parser.add_argument(
        "--provider", choices=["keyword", "fastembed", "all"], default="keyword"
    )
    parser.add_argument(
        "--production",
        action="store_true",
        help="Use configured chunk sizes instead of 64/8",
    )
    args = parser.parse_args()
    settings = (
        Settings() if args.production else Settings(chunk_tokens=64, chunk_overlap=8)
    )
    providers = ["keyword", "fastembed"] if args.provider == "all" else [args.provider]
    for provider in providers:
        report(args.language, provider, settings)


if __name__ == "__main__":
    main()
