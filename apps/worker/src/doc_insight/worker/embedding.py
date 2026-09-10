"""Attach validated vectors without mutating the structured document."""

from math import isfinite, sqrt

from doc_insight.contracts.embedding import Embedder
from doc_insight.contracts.extraction import PIPELINE_VERSION
from doc_insight.contracts.structure import Document


def cosine(a: list[float], b: list[float]) -> float:
    if not a or len(a) != len(b) or not all(isfinite(x) for x in [*a, *b]):
        raise ValueError("Cosine requires finite vectors of the same nonzero dimension")
    denominator = sqrt(sum(x * x for x in a)) * sqrt(sum(x * x for x in b))
    if denominator == 0:
        raise ValueError("Cosine is undefined for zero vectors")
    return sum(x * y for x, y in zip(a, b, strict=True)) / denominator


def embed_document(document: Document, embedder: Embedder) -> Document:
    """Copy output with one finite, nonzero vector per chunk and provider metadata.

    Reject count/dimension violations before anything can be persisted. The input
    document stays unchanged; stored output uses the current pipeline version.
    """
    vectors = embedder.embed_passages([chunk.text for chunk in document.chunks])
    if len(vectors) != len(document.chunks) or any(
        len(vector) != embedder.dimension
        or not any(vector)
        or not all(isfinite(x) for x in vector)
        for vector in vectors
    ):
        raise ValueError("Embedder returned invalid vector count, dimension or values")
    chunks = [
        chunk.model_copy(update={"embedding": vector})
        for chunk, vector in zip(document.chunks, vectors, strict=True)
    ]
    return document.model_copy(
        update={
            "chunks": chunks,
            "embed_model": embedder.model_id,
            "embed_dimension": embedder.dimension,
            "pipeline_version": PIPELINE_VERSION,
        }
    )
