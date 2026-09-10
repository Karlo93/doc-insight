"""Deterministic fusion and heuristic confidence, never cosine-as-probability."""

import re

from doc_insight.contracts.storage import SearchHit

STOP_WORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "do",
        "does",
        "did",
        "what",
        "where",
        "when",
        "why",
        "how",
        "which",
        "who",
        "in",
        "on",
        "at",
        "to",
        "of",
        "for",
        "and",
        "or",
        "it",
        "this",
        "that",
        "through",
        "during",
        "gdje",
        "što",
        "kako",
        "kada",
        "zašto",
        "je",
        "su",
        "se",
        "u",
        "na",
        "i",
        "od",
        "za",
    ]
)


def words(text: str) -> set[str]:
    return set(re.findall(r"[^\W_]+", text.casefold())) - STOP_WORDS


def overlap(text: str, evidence: str) -> float:
    tokens = words(text)
    return len(tokens & words(evidence)) / len(tokens) if tokens else 0.0


def fuse(rankings: list[list[SearchHit]], k: int = 60) -> list[SearchHit]:
    """Sum reciprocal ranks by document/chunk, deduplicating within each ranking.

    Returned fusion scores replace cosine/full-text scores. Ties sort by document
    ID and ordinal to keep candidate ordering reproducible.
    """
    if k < 1:
        raise ValueError("RRF k must be positive")
    scores: dict[tuple[str, int], float] = {}
    hits: dict[tuple[str, int], SearchHit] = {}
    for ranking in rankings:
        seen = set()
        for rank, hit in enumerate(ranking, 1):
            key = (str(hit.document_id), hit.chunk.ord)
            if key in seen:
                continue
            seen.add(key)
            hits.setdefault(key, hit)
            scores[key] = scores.get(key, 0.0) + 1 / (k + rank)
    return [
        hits[key].model_copy(update={"score": scores[key]})
        for key in sorted(hits, key=lambda key: (-scores[key], key))
    ]


def confidence(
    scores: list[float], supported: bool, answer: str, cited_passages: list[str]
) -> float:
    """Score lexical grounding and rank separation, not correctness probability."""
    if not supported or not scores or not answer.strip() or not cited_passages:
        return 0.0
    # A singleton has no competing observation; never invent a perfect margin.
    margin = (
        (scores[0] - scores[-1]) / scores[0] if len(scores) > 1 and scores[0] > 0 else 0
    )
    margin = min(1.0, max(0.0, margin))
    grounding = overlap(answer, " ".join(cited_passages))
    return min(1.0, max(0.0, (0.7 + 0.3 * margin) * grounding))


def should_abstain(value: float, threshold: float, supported: bool) -> bool:
    return not supported or value <= 0 or value < threshold
