"""Compare retrieval against the committed questions; the keyword baseline is offline."""

import argparse
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider", choices=["keyword", "fastembed"], default="keyword"
    )
    args = parser.parse_args()
    settings = Settings(chunk_tokens=64, chunk_overlap=8)
    embedder: Embedder = KeywordEmbedder(settings.embed_dim)
    tokenizer: Tokenizer = FakeTokenizer()
    if args.provider == "fastembed":
        embedder, tokenizer = FastEmbedEmbedder(settings), HfTokenizer(settings)
    fixtures = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
    cases = [
        EvaluationCase.model_validate_json(line)
        for line in (fixtures / "eval.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    chunks = []
    for page in extract(fixtures / "text_long.pdf").pages:
        chunks.extend(chunk_page(page, tokenizer, settings, len(chunks)))
    metrics = evaluate(cases, chunks, embedder)
    print(f"model={embedder.model_id} | chunks={len(chunks)} | questions={len(cases)}")
    print(f"recall@5={metrics.recall_at_5:.3f} | MRR={metrics.mrr:.3f}")


if __name__ == "__main__":
    main()
