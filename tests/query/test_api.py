from unittest.mock import Mock

import pytest
from doc_insight.contracts.extraction import Page
from doc_insight.contracts.query import Generation, QueryRequest
from doc_insight.contracts.structure import Chunk, Document, Entity
from doc_insight.query.generation import FallbackGenerator
from doc_insight.query.main import create_app
from doc_insight.query.service import QueryService
from doc_insight.query.settings import Settings
from doc_insight.testing.embedding import KeywordEmbedder
from doc_insight.testing.storage import InMemoryRepository
from fastapi.testclient import TestClient


@pytest.fixture
def service():
    text = "The pharmacy stores vaccines in monitored refrigerators."
    embedder = KeywordEmbedder(384)
    document = Document(
        sha256="a" * 64,
        media_type="application/pdf",
        pages=[Page(number=1, text=text, source="text_layer", language="en")],
        chunks=[
            Chunk(
                text=text,
                page=1,
                ord=0,
                language="en",
                char_start=0,
                char_end=len(text),
                token_count=8,
                embedding=embedder.embed_query(text),
            )
        ],
        entities=[
            Entity(
                text="pharmacy", label="ORG", page=1, char_start=4, char_end=12, count=2
            ),
            Entity(text="absent", label="ORG", page=1, char_start=0, char_end=6),
        ],
        embed_model=embedder.model_id,
        embed_dimension=384,
    )
    repository = InMemoryRepository(384)
    repository.upsert_document("demo", "fixture.pdf", document)
    return QueryService(
        repository, embedder, FallbackGenerator(), Settings(openai_api_key="")
    )


@pytest.fixture
def client(service):
    with TestClient(create_app(service)) as client:
        yield client


def test_response_and_tenant_isolation(client):
    # An API result must retain both the answer contract and the authenticated tenant boundary.
    body = {"question": "Where does the pharmacy store vaccines?", "top_k": 3}
    data = client.post("/query", headers={"X-Tenant-Id": "demo"}, json=body).json()
    assert not data["abstained"] and data["confidence"] == 0.7
    assert "monitored refrigerators" in data["answer"]
    assert data["sources"][0]["page"] == 1
    assert data["sources"][0]["char_end"] == len(data["sources"][0]["text"])
    assert [e["text"] for e in data["entities"]] == ["pharmacy"]
    assert data["entities"][0]["count"] == 2
    assert data["generation"]["provider"] == "extractive"
    assert data["retrieval"] == {"top_k": 3, "hits": 1, "hybrid": True}
    other = client.post("/query", headers={"X-Tenant-Id": "other"}, json=body).json()
    assert other["abstained"] and other["sources"] == [] and other["entities"] == []


@pytest.mark.parametrize(
    "body",
    [
        {"question": ""},
        {"question": "   "},
        {"question": 42},
        {"question": "x", "top_k": 0},
        {"question": "x", "top_k": 21},
        {"question": "x", "top_k": True},
        {"question": "x", "filter": {"language": "de"}},
        {"question": "x", "filter": {"document_ids": ["bad"]}},
        {"question": "x", "filter": {"tenant_id": "other"}},
    ],
)
def test_schema_errors_sanitized(client, body):
    response = client.post("/query", headers={"X-Tenant-Id": "demo"}, json=body)
    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "validation_error", "message": "Invalid query request"}
    }


@pytest.mark.parametrize(
    "headers", [{}, {"X-Tenant-Id": "bad tenant"}, {"X-Tenant-Id": "x" * 65}]
)
def test_missing_or_invalid_tenant(client, headers):
    assert (
        client.post("/query", headers=headers, json={"question": "x"}).status_code
        == 400
    )


def test_overlong_question_mapped_without_echo(client, service):
    service.embedder = Mock(
        embed_query=Mock(side_effect=ValueError("private question"))
    )
    response = client.post(
        "/query", headers={"X-Tenant-Id": "demo"}, json={"question": "private " * 127}
    )
    assert response.status_code == 400
    assert "126 content token" in response.text and "private" not in response.text


def test_abstention_keeps_hits_and_threshold(client, service):
    response = client.post(
        "/query",
        headers={"X-Tenant-Id": "demo"},
        json={"question": "quantum mathematics"},
    ).json()
    assert response["abstained"] and response["answer"] == "" and response["sources"]
    service.settings.abstain_threshold = 0.9
    data = client.post(
        "/query", headers={"X-Tenant-Id": "demo"}, json={"question": "vaccines"}
    ).json()
    assert data["abstained"] and data["confidence"] == 0.7 and data["entities"] == []


def test_filters_and_configured_cap(client, service):
    for filter in ({"document_ids": []}, {"language": "hr"}):
        data = client.post(
            "/query",
            headers={"X-Tenant-Id": "demo"},
            json={"question": "vaccines", "filter": filter},
        ).json()
        assert data["sources"] == []
    service.settings.query_top_k_max = 2
    assert (
        client.post(
            "/query", headers={"X-Tenant-Id": "demo"}, json={"question": "vaccines"}
        ).status_code
        == 422
    )


def test_invalid_generator_indexes_abstain(client, service):
    primary = Mock(
        generate=Mock(
            return_value=Generation(
                answer="vaccines", supported=True, cited_passage_indexes=[-1]
            )
        )
    )
    service.generator = FallbackGenerator(primary)
    data = client.post(
        "/query", headers={"X-Tenant-Id": "demo"}, json={"question": "vaccines"}
    ).json()
    assert data["abstained"] and data["confidence"] == 0


def test_health_independent_from_readiness_and_sanitized_failure():
    app = create_app()
    app.state.runtime = Mock(
        ready=Mock(side_effect=OSError("private host")),
        get_service=Mock(side_effect=OSError("private host")),
    )
    client = TestClient(app)
    assert client.get("/healthz").status_code == 200
    response = client.get("/readyz")
    assert response.status_code == 503 and "private" not in response.text
    response = client.post(
        "/query", headers={"X-Tenant-Id": "demo"}, json={"question": "x"}
    )
    assert response.status_code == 503 and "private" not in response.text


@pytest.mark.parametrize(
    "setting,value",
    [
        ("rrf_k", 0),
        ("abstain_threshold", 2),
        ("llm_timeout_seconds", 0),
        ("llm_timeout_seconds", float("inf")),
        ("llm_breaker_failures", 0),
        ("llm_breaker_seconds", 0),
        ("query_top_k_max", 21),
    ],
)
def test_settings_validate(setting, value):
    with pytest.raises(ValueError):
        Settings(**{setting: value})


def test_service_reports_effective_top_k(service):
    service.settings.query_top_k_max = 1
    question = "Where does the pharmacy store vaccines?"
    response = service.query("demo", QueryRequest(question=question, top_k=3))
    assert response.retrieval.top_k == 1 and response.retrieval.hits == 1


def test_unexpected_errors_keep_error_envelope(service, caplog):
    service.query = Mock(side_effect=TypeError("private document text"))
    client = TestClient(create_app(service), raise_server_exceptions=False)
    with caplog.at_level("WARNING", logger="doc_insight.query.main"):
        response = client.post(
            "/query", headers={"X-Tenant-Id": "demo"}, json={"question": "x"}
        )
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "Query operation failed"}
    }
    assert "route=/query" in caplog.text and "error=TypeError" in caplog.text
    assert "private" not in caplog.text


def test_entities_deduplicate_normalized_spelling_per_document(service):
    from doc_insight.query.service import cited_entities

    repository = service.repository
    stored = next(iter(repository.documents.values()))
    duplicate = stored.entities[0].model_copy(update={"text": "PHARMACY"})
    stored.entities.append(duplicate)
    hits = repository.nearest_chunks(
        "demo", service.embedder.embed_query("pharmacy"), 5
    )
    entities = cited_entities(hits, [stored])
    assert (
        len(entities) == 1 and entities[0].text == "pharmacy" and entities[0].count == 2
    )


def test_hosted_paraphrase_is_not_rejected_by_word_overlap(service):
    # Same meaning as the fixture, with deliberately different vocabulary.
    answer = "A clinical dispensary keeps immunizations chilled."
    service.generator = FallbackGenerator(
        Mock(
            generate=Mock(
                return_value=Generation(
                    answer=answer,
                    supported=True,
                    cited_passage_indexes=[0],
                )
            )
        )
    )
    response = service.query(
        "demo", QueryRequest(question="How are vaccines kept cold?")
    )
    assert response.confidence < service.settings.abstain_threshold
    assert not response.abstained and response.answer == answer
    assert (
        response.sources[0].text
        == "The pharmacy stores vaccines in monitored refrigerators."
    )
    assert response.generation.provider == "openai"


@pytest.mark.parametrize(
    "answer,supported,indexes",
    [
        ("", True, [0]),
        ("   ", True, [0]),
        ("answer", False, [0]),
        ("answer", True, []),
        ("answer", True, [0, 999]),
    ],
)
def test_hosted_support_still_requires_nonempty_answer_and_valid_citations(
    service, answer, supported, indexes
):
    service.generator = FallbackGenerator(
        Mock(
            generate=Mock(
                return_value=Generation(
                    answer=answer,
                    supported=supported,
                    cited_passage_indexes=indexes,
                )
            )
        )
    )
    response = service.query("demo", QueryRequest(question="vaccines"))
    assert response.abstained and response.answer == "" and response.entities == []


def test_question_words_do_not_disable_exact_label_retrieval(service):
    from doc_insight.query.ranking import lexical_query

    query = lexical_query("What does the pharmacy do?")
    assert service.repository.search_text("demo", query, 5)
    assert service.repository.search_text("other", query, 5) == []
