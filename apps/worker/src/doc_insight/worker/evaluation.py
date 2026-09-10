"""In-memory retrieval metrics over exact expected substrings."""

from doc_insight.contracts.embedding import Embedder
from doc_insight.contracts.structure import Chunk
from doc_insight.worker.embedding import cosine
from pydantic import BaseModel


class EvaluationCase(BaseModel):
    question: str
    expected_substring: str


class RetrievalMetrics(BaseModel):
    recall_at_5: float
    mrr: float


def evaluate(
    cases: list[EvaluationCase], chunks: list[Chunk], embedder: Embedder
) -> RetrievalMetrics:
    if not cases:
        raise ValueError("Evaluation requires at least one question")
    vectors = embedder.embed_passages([chunk.text for chunk in chunks])
    if len(vectors) != len(chunks):
        raise ValueError("Embedder must return one vector per chunk")
    hits, reciprocal_ranks = 0, 0.0
    for case in cases:
        query = embedder.embed_query(case.question)
        ranking = sorted(
            range(len(chunks)), key=lambda index: -cosine(query, vectors[index])
        )
        rank = next(
            (
                rank
                for rank, index in enumerate(ranking, 1)
                if case.expected_substring in chunks[index].text
            ),
            0,
        )
        hits += 0 < rank <= 5
        reciprocal_ranks += 1 / rank if rank else 0
    return RetrievalMetrics(
        recall_at_5=hits / len(cases), mrr=reciprocal_ranks / len(cases)
    )
