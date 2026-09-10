"""Resolve explicit document names before ranking passages within the tenant snapshot."""

import re
from difflib import SequenceMatcher
from uuid import UUID

from doc_insight.contracts.query import QueryFilter, QueryReader, QueryRequest
from doc_insight.contracts.storage import SearchHit
from doc_insight.query.ranking import fuse, lexical_query, words


def named_scope(
    question: str, names: list[tuple[UUID, str]], requested: QueryFilter
) -> QueryFilter:
    """Recognize distinctive filename words, allowing a small spelling error."""
    terms = {term for term in words(question) if len(term) >= 5}
    matches = []
    for identifier, filename in names:
        title = {
            word
            for word in re.findall(r"[^\W_]+", filename.casefold())
            if len(word) >= 5
        }
        if any(
            SequenceMatcher(None, term, word).ratio() >= 0.86
            for term in terms
            for word in title
        ):
            matches.append(identifier)
    # Explicit UI filters always win; an inferred name can only narrow an all-docs query.
    if requested.document_ids is not None or not matches:
        return requested
    return requested.model_copy(update={"document_ids": matches})


def retrieve(
    reader: QueryReader,
    tenant: str,
    request: QueryRequest,
    vector: list[float],
    cap: int,
    rrf_k: int,
) -> list[SearchHit]:
    """Use document-name context for passage selection without sending filenames to a model."""
    scope = named_scope(request.question, reader.document_names(tenant), request.filter)
    rankings = [
        reader.nearest_chunks(tenant, vector, cap, scope),
        reader.search_text(tenant, lexical_query(request.question), cap, scope),
    ]
    return fuse(rankings, rrf_k)[: min(request.top_k, cap)]
