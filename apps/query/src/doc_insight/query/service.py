"""Query orchestration with tenant-scoped reads and exact stored source slices."""

from time import perf_counter
from unicodedata import normalize

from doc_insight.contracts.embedding import Embedder
from doc_insight.contracts.query import (
    CitedEntity,
    Generation,
    GenerationInfo,
    QueryRepository,
    QueryRequest,
    QueryResponse,
    RetrievalInfo,
    Source,
)
from doc_insight.contracts.storage import SearchHit, StoredDocument
from doc_insight.observability import stage
from doc_insight.query.generation import FallbackGenerator
from doc_insight.query.ranking import confidence, fuse, should_abstain
from doc_insight.query.settings import Settings


def normalized(text: str) -> str:
    return " ".join(normalize("NFKC", text).casefold().split())


def cited_entities(
    hits: list[SearchHit], documents: list[StoredDocument]
) -> list[CitedEntity]:
    result: dict[tuple[str, str, str], CitedEntity] = {}
    for document in documents:
        passages = [
            normalized(hit.chunk.text) for hit in hits if hit.document_id == document.id
        ]
        for entity in document.entities:
            key = (str(document.id), normalized(entity.text), entity.label)
            if (
                key[1]
                and any(key[1] in passage for passage in passages)
                and key not in result
            ):
                result[key] = CitedEntity(
                    text=entity.text,
                    label=entity.label,
                    count=entity.count,
                    document_id=document.id,
                )
    return list(result.values())


def source(hit: SearchHit) -> Source:
    return Source(
        document_id=hit.document_id,
        page=hit.chunk.page,
        chunk_ord=hit.chunk.ord,
        char_start=hit.chunk.char_start,
        char_end=hit.chunk.char_end,
        text=hit.chunk.text,
        score=hit.score,
    )


class QuestionTooLong(ValueError):
    """The embedding adapter refused the question budget."""


class QueryService:
    def __init__(
        self,
        repository: QueryRepository,
        embedder: Embedder,
        generator: FallbackGenerator,
        settings: Settings,
    ) -> None:
        self.repository, self.embedder = repository, embedder
        self.generator, self.settings = generator, settings

    def query(self, tenant: str, request: QueryRequest) -> QueryResponse:
        started = perf_counter()
        try:
            with stage("query.embed"):
                vector = self.embedder.embed_query(request.question)
        except ValueError as exc:
            raise QuestionTooLong("Question exceeds 126 content tokens") from exc
        # Rank up to the service cap before cutting to top_k, even for top_k=1.
        with stage("query.retrieve"), self.repository.snapshot(tenant) as reader:
            k = self.settings.query_top_k_max
            rankings = [
                reader.nearest_chunks(tenant, vector, k, request.filter),
                reader.search_text(tenant, request.question, k, request.filter),
            ]
            hits = fuse(rankings, self.settings.rrf_k)[: request.top_k]
            documents = [
                document
                for doc_id in dict.fromkeys(hit.document_id for hit in hits)
                if (document := reader.get_document(tenant, doc_id)) is not None
            ]
        with stage("query.generate"):
            generation, provider = self.generator.generate(
                request.question, [h.chunk.text for h in hits]
            )
        return self._response(request, hits, documents, generation, provider, started)

    def _response(
        self,
        request: QueryRequest,
        hits: list[SearchHit],
        documents: list[StoredDocument],
        generation: Generation,
        provider: GenerationInfo,
        started: float,
    ) -> QueryResponse:
        indexes = list(dict.fromkeys(generation.cited_passage_indexes))
        valid = bool(indexes) and all(0 <= i < len(hits) for i in indexes)
        cited = [hits[i] for i in indexes] if valid else []
        value = confidence(
            [h.score for h in hits],
            generation.supported and valid,
            generation.answer,
            [h.chunk.text for h in cited],
        )
        abstained = should_abstain(
            value, self.settings.abstain_threshold, generation.supported and valid
        )
        # Abstention preserves retrieved evidence for inspection, without asserting a citation.
        returned = hits if abstained else cited
        return QueryResponse(
            answer="" if abstained else generation.answer,
            confidence=value,
            abstained=abstained,
            sources=[source(hit) for hit in returned],
            entities=[] if abstained else cited_entities(cited, documents),
            retrieval=RetrievalInfo(top_k=request.top_k, hits=len(hits)),
            generation=provider,
            latency_ms=int((perf_counter() - started) * 1000),
        )
