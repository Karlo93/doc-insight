# ADR-0008: Hybrid retrieval with RRF, extractive fallback and confidence

Status: accepted. Date: 2026-09-10.

## Decision

Use PostgreSQL cosine kNN plus `to_tsvector('simple', chunks.text) @@
websearch_to_tsquery('simple', :q)`, ordered by `ts_rank_cd`. Both rankings and
document metadata share one repeatable-read snapshot and identical tenant, document
and page-language filters. Each ranking retrieves up to the service cap (20).
Bind the tenant once per snapshot with transaction-local `app.tenant_id`; runtime
connections use the restricted role introduced by migration 0002. Pool reuse clears
the context. A reader cannot switch to another tenant within the snapshot.
Close the snapshot before generation. No migration here; after the pending storage
migrations, add `CREATE INDEX chunks_text_gin ON chunks USING gin (to_tsvector('simple', text));`.

Fuse by chunk identity using `sum(1 / (K + rank))`, rank starting at 1, `K=60`.
Missing results contribute zero; UUID/ordinal break ties. Keep the default fixed,
exposing `DI_RRF_K` for explicit configuration. Truncate fused candidates to `top_k`.

Put `Generator` and `Generation` in contracts. Mistral gets question/passage text
only, instructions to cite numbered passages, and an exact `INSUFFICIENT` sentinel.
Reject malformed or out-of-range citations. Reuse one HTTP client with timeouts;
after three consecutive failures, open for 30 seconds, then admit one probe.
Serialize hosted calls; concurrent requests fall back immediately. Missing key,
failure, open circuit or busy generator uses the offline extractive provider.
It selects the highest question-overlap window of up to two sentences from the
top passage; support requires overlap ≥0.30. Defaults are configurable except
the versioned extractive rule. `INSUFFICIENT` abstains without retrying generation.

Share embedding configuration through contracts' `EmbeddingSettings`, inherited
by each app's single cached settings object. Reuse worker adapters and cached
models; do not duplicate indexing or bump pipeline version 6.
Use the shared observability package for request spans and embedding, retrieval and
generation durations. It records no question, passage or user filename.

## Confidence

Let `M = clamp((first - last) / first, 0, 1)` for retained fused scores, zero
for fewer than two results. Let `L` be the fraction of distinct answer content
words found in cited passages (case folded, common English/Croatian words removed).
`confidence = (0.7 + 0.3M)L` only with generator support and valid nonempty citations;
otherwise zero. Abstain below 0.60, on zero, or without support. Return an empty
answer and retrieved evidence on abstention. This is a heuristic, not a probability;
raw cosine cannot distinguish support. Lexical overlap can accept wrong answers
and miss inflections/paraphrases. A singleton's confidence is at most 0.70.

## Offline evaluation

Eight committed questions, shipped 120/24 windows, PostgreSQL 16/pgvector 0.8.6.
`scripts/eval_query.py` reports recall@5 and full-ranking MRR; its generation check
uses the service's 20-candidate cap and extractive fallback. Model files were cached;
`HF_HUB_OFFLINE=1` and no API key were used throughout.

| Embedder / chunks | kNN recall / MRR | Text recall / MRR | Fused recall / MRR |
| --- | --- | --- | --- |
| Keyword / 18 | 1.000 / 0.729 | 0.000 / 0.000 | 1.000 / 0.729 |
| MiniLM / 24 | 1.000 / 0.917 | 0.000 / 0.000 | 1.000 / 0.917 |

Fusion meets the ≥kNN gate but adds nothing on this fixture: `simple` web-search
requires all ordinary question words, yielding no matches. Do not tune K to mask
that limitation. Dedicated phrase/OR/ranking/filter integration tests exercise the
text path. MiniLM plus extraction returns six exact answer substrings, abstains
once and misses once. Retrieval recall does not imply answer correctness.

## Alternatives

- kNN only: simpler and ties this fixture; retain the lexical path for explicit
  terms and phrases, then evaluate natural-question normalization on a holdout.
- Cross-encoder reranking: defer until a representative bilingual holdout falls
  below 0.8 recall@5 or exposes persistent wrong top passages. Adopt only after
  measured quality gains meet an agreed latency/memory budget.
- Hosted RAG services: add data transfer, credentials and service dependence;
  conflict with the required offline operating path.
