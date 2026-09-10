from math import isfinite

import pytest
from doc_insight.contracts.embedding import Embedder
from doc_insight.testing.embedding import FakeEmbedder, KeywordEmbedder
from doc_insight.worker.embedder import FastEmbedEmbedder
from doc_insight.worker.embedding import cosine
from doc_insight.worker.settings import Settings


@pytest.fixture(
    params=["fake", "keyword", pytest.param("fastembed", marks=pytest.mark.models)]
)
def embedder(request: pytest.FixtureRequest) -> Embedder:
    if request.param == "fastembed":
        return FastEmbedEmbedder(Settings())
    return FakeEmbedder() if request.param == "fake" else KeywordEmbedder()


def test_embedder_contract(embedder: Embedder) -> None:
    # Dimensions and finite vector values are adapter obligations, independent of semantic quality.
    texts = [
        "Saturn telescope rings",
        "Sourdough bread bakery",
        "Saturn telescope rings",
    ]
    vectors = embedder.embed_passages(texts)
    assert embedder.model_id
    assert embedder.dimension == 384
    assert len(vectors) == len(texts)
    for vector in vectors:
        assert len(vector) == embedder.dimension
        assert all(isfinite(value) for value in vector)
        assert sum(value * value for value in vector) == pytest.approx(1, abs=1e-5)
        assert cosine(vector, vector) == pytest.approx(1)
    assert vectors[0] == pytest.approx(vectors[2])
    for first, repeated in zip(vectors, embedder.embed_passages(texts), strict=True):
        assert first == pytest.approx(repeated)
    query = embedder.embed_query(texts[0])
    assert cosine(query, vectors[0]) > cosine(query, vectors[1])


def test_embedder_empty_inputs(embedder: Embedder) -> None:
    assert embedder.embed_passages([]) == []
    vector = embedder.embed_query("")
    assert len(vector) == embedder.dimension
    assert cosine(vector, vector) == pytest.approx(1)


@pytest.mark.parametrize("provider", [FakeEmbedder, KeywordEmbedder])
def test_fakes_support_the_upgrade_dimension(provider) -> None:
    embedder = provider(dimension=1024)
    assert len(embedder.embed_query("čćđšž")) == 1024
    assert embedder.embed_query("čćđšž") == embedder.embed_query("čćđšž")
    with pytest.raises(ValueError):
        provider(dimension=0)
