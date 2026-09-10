from pathlib import Path
from uuid import uuid4

import pytest
from doc_insight.contracts.structure import Document
from doc_insight.testing.embedding import KeywordEmbedder
from doc_insight.testing.structure import FakeTokenizer
from doc_insight.worker import store_cli
from doc_insight.worker.embedding import embed_document
from doc_insight.worker.evaluation import EvaluationCase
from doc_insight.worker.extraction import extract
from doc_insight.worker.repository import PostgresRepository
from doc_insight.worker.settings import Settings
from doc_insight.worker.structure import chunk_page

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
pytestmark = pytest.mark.integration


def test_keyword_retrieval_through_postgres(database):
    settings = Settings(chunk_tokens=64, chunk_overlap=8)
    extracted = extract(FIXTURES / "text_long.pdf")
    chunks = []
    for page in extracted.pages:
        chunks.extend(chunk_page(page, FakeTokenizer(), settings, len(chunks)))
    document = Document(
        **extracted.model_dump(exclude={"page_count"}), chunks=chunks, entities=[]
    )
    embedder = KeywordEmbedder()
    repository = PostgresRepository(database)
    tenant = uuid4().hex
    repository.upsert_document(
        tenant, "text_long.pdf", embed_document(document, embedder)
    )
    cases = [
        EvaluationCase.model_validate_json(line)
        for line in (FIXTURES / "eval.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    hits = 0
    for case in cases:
        results = repository.nearest_chunks(
            tenant, embedder.embed_query(case.question), 5
        )
        hits += any(case.expected_substring in hit.chunk.text for hit in results)
    assert len(chunks) == 30 and len(cases) == 8
    assert hits / len(cases) >= 0.75
    print(f"Postgres keyword recall@5={hits / len(cases):.3f}")


def test_index_file_twice_preserves_output(database, monkeypatch, capsys):
    monkeypatch.setattr(store_cli, "HfTokenizer", lambda settings: FakeTokenizer())
    monkeypatch.setattr(
        store_cli, "FastEmbedEmbedder", lambda settings: KeywordEmbedder()
    )
    repository = PostgresRepository(database)
    tenant = uuid4().hex
    first = store_cli.index_file(FIXTURES / "text_hr.pdf", tenant, repository)
    second = store_cli.index_file(FIXTURES / "text_hr.pdf", tenant, repository)
    assert first.id == second.id and len(first.chunks) == len(second.chunks) == 1
    assert second.processed_at > first.processed_at
    loaded = repository.get_document(tenant, first.id)
    assert loaded.language == "hr" and loaded.entities
    assert loaded.chunks[0].text == first.chunks[0].text
    assert repository.get_document(uuid4().hex, first.id) is None
    assert "store=" in capsys.readouterr().out
