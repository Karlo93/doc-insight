"""Deterministic fusion and heuristic confidence, never cosine-as-probability."""

import re

from doc_insight.contracts.query import Generation, GenerationInfo
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
        "with",
        "about",
        "can",
        "could",
        "please",
        "explain",
        "tell",
        "me",
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
OPERATORS = frozenset(["and", "or"])


def words(text: str) -> set[str]:
    """Casefold content words; an all-caps token such as CAN is a term, not a stop word."""
    found = set()
    for token in re.findall(r"[^\W_]+", text):
        folded = token.casefold()
        # Search operators typed in capitals are not acronyms.
        acronym = len(token) > 1 and token.isupper() and folded not in OPERATORS
        if folded not in STOP_WORDS or acronym:
            found.add(folded)
    return found


def overlap(text: str, evidence: str) -> float:
    tokens = words(text)
    return len(tokens & words(evidence)) / len(tokens) if tokens else 0.0


def lexical_query(question: str) -> str:
    """Search content terms without requiring every word of a natural-language question."""
    # Only tokenizer-produced words enter the grammar; user operators stay inert.
    return " OR ".join(f'"{term}"' for term in sorted(words(question)))


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


def should_abstain(
    value: float, threshold: float, supported: bool, *, generated: bool = False
) -> bool:
    """Use lexical thresholds for extraction, not for a hosted model's paraphrase."""
    # Citation validation and explicit lack of support still reject hosted output.
    return not supported or (not generated and (value <= 0 or value < threshold))


def assess_generation(
    generation: Generation,
    provider: GenerationInfo,
    hits: list[SearchHit],
    threshold: float,
) -> tuple[float, bool, list[SearchHit]]:
    """Validate citation structure, then apply the provider-appropriate support rule."""
    indexes = list(dict.fromkeys(generation.cited_passage_indexes))
    # One invalid citation invalidates the whole answer, including hosted output.
    valid = bool(indexes and generation.answer.strip()) and all(
        0 <= i < len(hits) for i in indexes
    )
    cited = [hits[i] for i in indexes] if valid else []
    value = confidence(
        [h.score for h in hits],
        generation.supported and valid,
        generation.answer,
        [h.chunk.text for h in cited],
    )
    abstained = should_abstain(
        value,
        threshold,
        generation.supported and valid,
        generated=provider.provider == "openai",
    )
    return value, abstained, cited
