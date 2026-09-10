"""Compare PostgreSQL kNN, full-text and RRF at the shipped 120/24 windows."""

import argparse
from pathlib import Path
from uuid import uuid4

from doc_insight.contracts.embedding import Embedder
from doc_insight.contracts.query import QueryRequest
from doc_insight.contracts.structure import Document, Tokenizer
from doc_insight.query.generation import FallbackGenerator
from doc_insight.query.ranking import fuse
from doc_insight.query.service import QueryService
from doc_insight.query.settings import Settings as QuerySettings
from doc_insight.testing.embedding import KeywordEmbedder
from doc_insight.testing.structure import FakeTokenizer
from doc_insight.worker.embedder import FastEmbedEmbedder
from doc_insight.worker.embedding import embed_document
from doc_insight.worker.evaluation import EvaluationCase
from doc_insight.worker.extraction import extract
from doc_insight.worker.providers import HfTokenizer
from doc_insight.worker.repository import PostgresRepository
from doc_insight.worker.settings import Settings
from doc_insight.worker.structure import chunk_page
from sqlalchemy import create_engine, text


def fixture(
    settings: Settings, provider: str
) -> tuple[Document, Embedder, list[EvaluationCase]]:
    embedder: Embedder = KeywordEmbedder(settings.embed_dim)
    tokenizer: Tokenizer = FakeTokenizer()
    if provider == "fastembed":
        embedder, tokenizer = FastEmbedEmbedder(settings), HfTokenizer(settings)
    root = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
    extracted = extract(root / "text_long.pdf")
    chunks = []
    for page in extracted.pages:
        page.language = "en"
        chunks.extend(chunk_page(page, tokenizer, settings, len(chunks)))
    document = Document(
        **extracted.model_dump(exclude={"page_count"}), chunks=chunks, entities=[]
    )
    cases = [
        EvaluationCase.model_validate_json(line)
        for line in (root / "eval.jsonl").read_text().splitlines()
    ]
    return embed_document(document, embedder), embedder, cases


def measure(
    repository: PostgresRepository,
    tenant: str,
    embedder: Embedder,
    cases: list[EvaluationCase],
    count: int,
) -> dict[str, tuple[float, float]]:
    ranks: dict[str, list[int]] = {"knn": [], "text": [], "fused": []}
    for case in cases:
        vector = embedder.embed_query(case.question)
        with repository.snapshot(tenant) as reader:
            knn = reader.nearest_chunks(tenant, vector, count)
            lexical = reader.search_text(tenant, case.question, count)
        for name, hits in (
            ("knn", knn),
            ("text", lexical),
            ("fused", fuse([knn, lexical])),
        ):
            rank = next(
                (
                    i
                    for i, hit in enumerate(hits, 1)
                    if case.expected_substring in hit.chunk.text
                ),
                0,
            )
            ranks[name].append(rank)
    return {
        name: (
            sum(0 < r <= 5 for r in values) / len(values),
            sum(1 / r if r else 0 for r in values) / len(values),
        )
        for name, values in ranks.items()
    }


def answer_metrics(
    repository: PostgresRepository,
    tenant: str,
    embedder: Embedder,
    cases: list[EvaluationCase],
) -> None:
    service = QueryService(
        repository, embedder, FallbackGenerator(), QuerySettings(openai_api_key="")
    )
    results = [
        service.query(tenant, QueryRequest(question=case.question)) for case in cases
    ]
    exact = sum(
        case.expected_substring in result.answer
        for case, result in zip(cases, results, strict=True)
    )
    print(
        f"extractive: exact-answer={exact}/{len(cases)} "
        f"abstained={sum(result.abstained for result in results)}/{len(cases)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider", choices=["keyword", "fastembed"], default="keyword"
    )
    args = parser.parse_args()
    settings = Settings(chunk_tokens=120, chunk_overlap=24)
    document, embedder, cases = fixture(settings, args.provider)
    engine = create_engine(settings.database_url, hide_parameters=True)
    tenant = "eval-" + uuid4().hex
    try:
        repository = PostgresRepository(engine)
        repository.upsert_document(tenant, "text_long.pdf", document)
        metrics = measure(repository, tenant, embedder, cases, len(document.chunks))
        print(
            f"model={embedder.model_id} chunks={len(document.chunks)} questions={len(cases)} windows=120/24"
        )
        for name, (recall, mrr) in metrics.items():
            print(f"{name}: recall@5={recall:.3f} MRR={mrr:.3f}")
        answer_metrics(repository, tenant, embedder, cases)
        if (
            metrics["fused"][0] < metrics["knn"][0]
            or metrics["fused"][1] < metrics["knn"][1]
        ):
            raise SystemExit(
                "Fused regression: inspect the fixture; do not tune RRF to pass"
            )
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("SELECT set_config('app.tenant_id', :tenant, true)"),
                {"tenant": tenant},
            )
            connection.execute(
                text("DELETE FROM documents WHERE tenant_id = :tenant"),
                {"tenant": tenant},
            )
        engine.dispose()


if __name__ == "__main__":
    main()
