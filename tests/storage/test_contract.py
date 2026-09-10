from uuid import uuid4

import pytest
from doc_insight.testing.storage import InMemoryRepository


def test_replay_and_version_change_replace_one_document(repository, document):
    # Identical input is a replay, so it must retain one document identity instead of duplicating rows.
    tenant = uuid4().hex
    first = repository.upsert_document(tenant, "first.pdf", document)
    replay = repository.upsert_document(tenant, "first.pdf", document)
    assert replay.id == first.id
    assert replay.created_at == first.created_at
    assert replay.processed_at > first.processed_at
    assert replay.model_dump(exclude={"processed_at"}) == first.model_dump(
        exclude={"processed_at"}
    )
    document.pipeline_version = "next"
    document.embed_model = "fake/next"
    document.chunks = []
    document.entities = []
    changed = repository.upsert_document(tenant, "first.pdf", document)
    assert changed.id == first.id
    loaded = repository.get_document(tenant, first.id)
    assert loaded.pipeline_version == "next"
    assert loaded.embed_model == "fake/next"
    assert loaded.chunks == loaded.entities == []
    assert repository.nearest_chunks(tenant, [1.0] + [0.0] * 383, 5) == []


def test_tenants_filter_reads_search_and_replacements(repository, document):
    tenant, other = uuid4().hex, uuid4().hex
    first = repository.upsert_document(tenant, "a.pdf", document)
    second = repository.upsert_document(other, "b.pdf", document)
    assert first.id != second.id
    assert repository.get_document(other, first.id) is None
    with pytest.raises(LookupError):
        repository.replace_chunks_and_entities(other, first.id, [], [])
    hits = repository.nearest_chunks(tenant, document.chunks[0].embedding, 5)
    assert len(hits) == 1 and hits[0].document_id == first.id
    assert hits[0].score == pytest.approx(1)
    assert hits[0].chunk.language == "en"
    repository.replace_chunks_and_entities(tenant, first.id, [], [])
    assert repository.get_document(tenant, first.id).chunks == []
    assert repository.get_document(other, second.id).chunks


def test_rejected_output_does_not_destroy_previous_state(repository, document):
    tenant = uuid4().hex
    stored = repository.upsert_document(tenant, "a.pdf", document)
    broken = document.model_copy(deep=True)
    broken.chunks[0].embedding = [0.0] * 384
    with pytest.raises(ValueError):
        repository.upsert_document(tenant, "a.pdf", broken)
    with pytest.raises(ValueError):
        repository.replace_chunks_and_entities(tenant, stored.id, broken.chunks, [])
    assert repository.get_document(tenant, stored.id) == stored


@pytest.mark.parametrize(
    "vector,k",
    [([1.0], 5), ([0.0] * 384, 5), ([float("nan")] * 384, 5), ([1.0] * 384, 0)],
)
def test_invalid_search_is_explicit(repository, vector, k):
    with pytest.raises(ValueError):
        repository.nearest_chunks(uuid4().hex, vector, k)


@pytest.mark.parametrize("change", ["tenant", "model", "dimension"])
def test_incomplete_index_input_is_rejected(repository, document, change):
    tenant = "" if change == "tenant" else uuid4().hex
    if change == "model":
        document.embed_model = None
    if change == "dimension":
        document.embed_dimension = None
    with pytest.raises(ValueError):
        repository.upsert_document(tenant, "a.pdf", document)


def test_fake_returns_independent_copies(document):
    repository = InMemoryRepository(384)
    saved = repository.upsert_document("a", "a.pdf", document)
    saved.chunks.clear()
    loaded = repository.get_document("a", saved.id)
    assert loaded.chunks
    loaded.entities.clear()
    assert repository.get_document("a", saved.id).entities


def test_nearest_orders_by_cosine_and_respects_k(repository, document):
    tenant = uuid4().hex
    first = repository.upsert_document(tenant, "first.pdf", document)
    document.sha256 = "b" * 64
    document.chunks[0].embedding = [0.0, 1.0] + [0.0] * 382
    second = repository.upsert_document(tenant, "second.pdf", document)
    vector = document.chunks[0].embedding
    hits = repository.nearest_chunks(tenant, vector, 2)
    assert [hit.document_id for hit in hits] == [second.id, first.id]
    assert [hit.score for hit in hits] == pytest.approx([1, 0])
    assert len(repository.nearest_chunks(tenant, vector, 1)) == 1
