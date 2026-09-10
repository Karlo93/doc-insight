from unittest.mock import Mock

import pytest
from doc_insight.contracts.embedding import Embedder
from doc_insight.contracts.extraction import PIPELINE_VERSION
from doc_insight.contracts.structure import Chunk, Document
from doc_insight.testing.embedding import FakeEmbedder
from doc_insight.worker.embedding import cosine, embed_document
from doc_insight.worker.settings import Settings


def document() -> Document:
    return Document(
        sha256="a" * 64,
        media_type="application/pdf",
        pages=[],
        entities=[],
        chunks=[
            Chunk(text="Saturn", page=1, ord=0, char_start=0, char_end=6, token_count=1)
        ],
    )


def test_embedding_attaches_vectors_and_metadata_without_mutation() -> None:
    source = document()
    embedder = FakeEmbedder()
    result = embed_document(source, embedder)
    assert source.chunks[0].embedding is None
    assert source.embed_model is None
    assert result.chunks[0].embedding == embedder.embed_query("Saturn")
    assert (result.embed_model, result.embed_dimension) == (embedder.model_id, 384)
    assert result.pipeline_version == PIPELINE_VERSION
    assert result.chunks[0].text == source.chunks[0].text


@pytest.mark.parametrize(
    "vectors",
    [[], [[1]], [[0.0] * 384], [[float("nan")] * 384], [[float("inf")] * 384]],
)
def test_bad_provider_results_fail_before_attaching_vectors(
    vectors: list[list[float]],
) -> None:
    embedder = Mock(spec=Embedder, dimension=384)
    embedder.embed_passages.return_value = vectors
    with pytest.raises(ValueError, match="invalid vector"):
        embed_document(document(), embedder)


def test_empty_document_keeps_valid_embedding_metadata() -> None:
    source = document().model_copy(update={"chunks": []})
    result = embed_document(source, FakeEmbedder())
    assert result.chunks == []
    assert result.embed_dimension == 384


@pytest.mark.parametrize(
    "a,b,expected", [([1, 0], [1, 0], 1), ([1, 0], [0, 1], 0), ([2, 0], [-3, 0], -1)]
)
def test_cosine_known_angles(a: list[float], b: list[float], expected: float) -> None:
    assert cosine(a, b) == pytest.approx(expected)


@pytest.mark.parametrize(
    "a,b",
    [([], []), ([1], [1, 2]), ([0], [1]), ([float("nan")], [1]), ([1], [float("inf")])],
)
def test_cosine_rejects_undefined_inputs(a: list[float], b: list[float]) -> None:
    with pytest.raises(ValueError):
        cosine(a, b)


@pytest.mark.parametrize(
    "overrides",
    [
        {"embed_batch": 0},
        {"embed_dim": 1024},
        {"embed_model": "unknown"},
        {"embed_onnx_repo": "unmatched/weights"},
    ],
)
def test_embedding_settings_reject_incompatible_configuration(overrides: dict) -> None:
    with pytest.raises(ValueError):
        Settings(**overrides)
