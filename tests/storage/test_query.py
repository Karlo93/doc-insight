from uuid import uuid4

import pytest
from doc_insight.contracts.query import QueryFilter
from doc_insight.query.generation import FallbackGenerator
from doc_insight.query.main import create_app
from doc_insight.query.service import QueryService
from doc_insight.query.settings import Settings as QuerySettings
from doc_insight.worker.repository import PostgresRepository
from doc_insight.worker.settings import Settings
from fastapi.testclient import TestClient

from scripts.eval_query import fixture, measure


@pytest.mark.integration
def test_question_search_finds_diagram_label_without_function_words(database, document):
    # The full question must not turn lexical search into a conjunction of every function word.
    from doc_insight.query.ranking import lexical_query

    repository = PostgresRepository(database)
    tenant = "diagram-" + uuid4().hex
    copy = document.model_copy(deep=True)
    copy.chunks[
        0
    ].text = "Worker: PDF parsing, Tesseract OCR, language detection, NER, embeddings."
    stored = repository.upsert_document(tenant, "architecture.png", copy)
    query = lexical_query("What does the worker do?")
    hits = repository.search_text(tenant, query, 5)
    assert hits and hits[0].document_id == stored.id and "Worker" in hits[0].chunk.text
    assert repository.search_text(tenant + "-other", query, 5) == []
    assert repository.search_text(tenant, query, 5, QueryFilter(document_ids=[])) == []


@pytest.mark.integration
def test_query_end_to_end_and_evaluation(database):
    document, embedder, cases = fixture(Settings(), "keyword")
    tenant = "query-" + uuid4().hex
    repository = PostgresRepository(database)
    stored = repository.upsert_document(tenant, "text_long.pdf", document)
    service = QueryService(
        repository, embedder, FallbackGenerator(), QuerySettings(openai_api_key="")
    )
    with TestClient(create_app(service)) as client:
        for case in (cases[0], cases[3], cases[6]):
            response = client.post(
                "/query",
                headers={"X-Tenant-Id": tenant},
                json={"question": case.question, "top_k": 5},
            )
            assert response.status_code == 200
            result = response.json()
            assert not result["abstained"]
            assert case.expected_substring in result["answer"]
            assert result["generation"]["provider"] == "extractive"
            assert any(
                case.expected_substring in source["text"]
                for source in result["sources"]
            )
            for source in result["sources"]:
                page = document.pages[source["page"] - 1]
                assert (
                    source["text"]
                    == page.text[source["char_start"] : source["char_end"]]
                )
                assert source["document_id"] == str(stored.id)
        other = client.post(
            "/query",
            headers={"X-Tenant-Id": tenant + "-other"},
            json={"question": cases[0].question},
        ).json()
        assert other["sources"] == [] and other["entities"] == [] and other["abstained"]
    metrics = measure(repository, tenant, embedder, cases, len(document.chunks))
    assert metrics["fused"][0] >= metrics["knn"][0]
    assert metrics["fused"][1] >= metrics["knn"][1]


def test_search_contract_tenant_and_filters(repository, document):
    tenant = "filter-" + uuid4().hex
    stored = repository.upsert_document(tenant, "fixture.pdf", document)
    vector = document.chunks[0].embedding
    for method, value in (
        (repository.nearest_chunks, vector),
        (repository.search_text, "astronomy"),
    ):
        assert method(tenant, value, 5)[0].document_id == stored.id
        assert method(tenant + "-other", value, 5) == []
        assert method(tenant, value, 5, QueryFilter(document_ids=[])) == []
        assert method(tenant, value, 5, QueryFilter(document_ids=[uuid4()])) == []
        assert method(tenant, value, 5, QueryFilter(language="hr")) == []
        assert method(
            tenant, value, 5, QueryFilter(document_ids=[stored.id], language="en")
        )
        with pytest.raises(ValueError):
            method(tenant, value, 0)


def test_query_snapshot_contract(repository, document):
    tenant = "reader-" + uuid4().hex
    stored = repository.upsert_document(tenant, "fixture.pdf", document)
    with repository.snapshot(tenant) as reader:
        assert reader.document_names(tenant) == [(stored.id, "fixture.pdf")]
        assert reader.document_names(tenant + "-other") == []
        assert reader.nearest_chunks(tenant, document.chunks[0].embedding, 5)
        assert reader.search_text(tenant, "astronomy", 5)
        assert reader.get_document(tenant, stored.id).id == stored.id
        assert reader.get_document(tenant + "-other", stored.id) is None


def test_snapshot_cannot_switch_to_another_populated_tenant(repository, document):
    first, second = uuid4().hex, uuid4().hex
    repository.upsert_document(first, "first.pdf", document)
    other = repository.upsert_document(second, "second.pdf", document)
    with repository.snapshot(first) as reader:
        assert reader.document_names(second) == []
        assert reader.nearest_chunks(first, document.chunks[0].embedding, 5)
        assert reader.nearest_chunks(second, document.chunks[0].embedding, 5) == []
        assert reader.search_text(second, "astronomy", 5) == []
        assert reader.get_document(second, other.id) is None
    with repository.snapshot(second) as reader:
        assert reader.search_text(second, "astronomy", 5)
        assert reader.get_document(second, other.id).id == other.id


@pytest.mark.integration
def test_full_text_rank_websearch_and_snapshot(database, document):
    repository = PostgresRepository(database)
    tenant = "snapshot-" + uuid4().hex
    stored = repository.upsert_document(tenant, "before.pdf", document)
    with repository.snapshot(tenant) as reader:
        nearest = reader.nearest_chunks(tenant, document.chunks[0].embedding, 5)
        replacement = document.model_copy(deep=True)
        replacement.chunks[0].text = "Alice studies biology."
        repository.upsert_document(tenant, "after.pdf", replacement)
        assert reader.search_text(tenant, '"studies astronomy" OR nonexistent', 5)
        assert reader.get_document(tenant, stored.id).filename == "before.pdf"
        assert (
            reader.search_text(tenant, "astronomy", 5)[0].chunk.text
            == nearest[0].chunk.text
        )
    assert repository.search_text(tenant, "astronomy", 5) == []
    assert repository.search_text(tenant, "biology -astronomy", 5)
    assert repository.search_text(tenant, "", 5) == []
    assert repository.search_text(tenant, "' OR 1=1 --", 5) == []


@pytest.mark.integration
def test_text_rank_is_ordered_and_tenant_documents_cannot_leak(database, document):
    repository = PostgresRepository(database)
    tenant = "rank-" + uuid4().hex
    for ordinal, passage in enumerate(
        ["Alice studies astronomy.", "astronomy astronomy astronomy"]
    ):
        copy = document.model_copy(deep=True)
        copy.sha256 = str(ordinal) * 64
        copy.chunks[0].text = passage
        repository.upsert_document(tenant, "fixture.pdf", copy)
    other = repository.upsert_document(tenant + "-other", "fixture.pdf", document)
    hits = repository.search_text(tenant, "astronomy", 5)
    assert len(hits) == 2 and hits[0].score > hits[1].score
    assert (
        repository.search_text(
            tenant, "astronomy", 5, QueryFilter(document_ids=[other.id])
        )
        == []
    )
    assert (
        repository.nearest_chunks(
            tenant,
            document.chunks[0].embedding,
            5,
            QueryFilter(document_ids=[other.id]),
        )
        == []
    )
