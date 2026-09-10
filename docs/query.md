# Query service

`di-query serve` starts `doc_insight.query.main:app` on port 8002. This is an
internal service: the gateway supplies the trusted `X-Tenant-Id` header.
Tenant IDs contain 1–64 letters, digits, dots, underscores or hyphens.
`GET /healthz` checks process health. `GET /readyz` checks PostgreSQL, the schema
and local embedding inference; unavailable dependencies return 503. The optional
hosted generator is not required for readiness.
For Docker credential injection, provider checks and token-usage limitations, see
[private deployment](private-deployment.md#api-credentials-and-token-usage).

## Request and response

```json
{"question":"Where does the pharmacy store vaccines?","top_k":5,"filter":{"document_ids":null,"language":"en"}}
```

`question` must be nonblank. `top_k` is an integer from 1 to 20, default 5, further
bounded by `DI_QUERY_TOP_K_MAX`. The optional filter restricts both rankings:
`document_ids` accepts UUIDs (`null` means all, `[]` means none); `language` accepts
`en` or `hr` and refers to the chunk's page language. Filters never widen the tenant.
Unknown fields and invalid values return 422. Missing/invalid tenant headers return
400. Questions over 126 content tokens return 400; the embedder refuses truncation.
Errors use `{"error":{"code":"...","message":"..."}}` without echoing the request.

The response contains `answer`, `confidence`, `abstained`, `sources`, `entities`,
`retrieval`, `generation` and integer `latency_ms`. Sources have document UUID,
one-based page, zero-based chunk ordinal, half-open character offsets, exact stored
text and fused score. Successful answers return cited chunks only. Abstention
returns retrieved chunks for inspection, an empty answer and no entities.
`retrieval.hits` counts the fused passages retained before generation, so it can
exceed the number of citations. Entities come only from cited documents, appear
in cited text, and deduplicate by document, normalized spelling and label.
Their counts are document-wide counts, not counts within the citation.

## Retrieval, confidence and fallback

Each ranking retrieves up to `DI_QUERY_TOP_K_MAX` candidates. Cosine kNN and
PostgreSQL full-text search run with the same tenant and filters in one repeatable-read
snapshot, including source-document metadata. Generation starts after the transaction
closes. Full-text uses `to_tsvector('simple', text)` with `websearch_to_tsquery` and
descending `ts_rank_cd`; no index migration is included. The query service removes
common question words and joins content terms with OR, so a natural-language question
does not require every word to occur in a passage. Repository/CLI websearch syntax
is unchanged. Before retrieval, distinctive filename words can narrow an all-library
question to a named document; a similarity ratio of at least 0.86 tolerates small
spelling errors. Explicit document filters take precedence and language filters remain.
Only tenant-owned IDs/names are read, in the same snapshot. Name resolution currently
scans the tenant's filename metadata; benchmark large catalogs before scaling this path.
The snapshot binds `app.tenant_id` once for FORCE row-level security. Use restricted
runtime credentials; reserve `DI_MIGRATION_DATABASE_URL` for schema changes and the
temporary-database test harness. Never run the service as the migration superuser.

Reciprocal rank fusion adds `1 / (60 + rank)` for each ranking containing a chunk.
Ranks start at 1; missing chunks contribute zero. Ties use document UUID, then chunk
ordinal. The configurable default 60 is fixed independently of the evaluation.

Confidence is a heuristic, not a calibrated probability. Let `M` be the relative
gap between the first and last retained fused score: `(first - last) / first`.
Clamp it to 0–1; a singleton gets zero margin. Let `L` be the fraction of distinct
answer words present in cited passages, after case folding and removal of common
English/Croatian function words. If the generator reports support and valid citations,
confidence is `(0.7 + 0.3 * M) * L`; otherwise it is zero. This lexical score gates
extractive answers only: abstain below `DI_ABSTAIN_THRESHOLD`, on zero confidence,
or without support. Hosted paraphrases use the model's support decision, a nonempty
answer and validated citations; word overlap is informational and does not veto them.
The browser displays passage counts instead of presenting lexical overlap as evidence
quality. Model support and valid indexes do not prove factual entailment; inspect the
cited passages for important answers. Cosine similarity does not enter the formula.

With an API key, OpenAI receives only the question and numbered passage text, never
tenant/document metadata. The Responses API uses `store: false`, an output token cap,
and a strict JSON schema for answer, support and zero-based citation indexes. Each
request restricts citation values to an enum of its actual passage indexes; parser
validation remains a second check. Filenames and tenant metadata stay local.
Refusals, incomplete output and invalid citations trigger extractive fallback.
An explicitly unsupported answer is a successful generation and causes abstention.
The circuit admits one recovery probe after cooldown; epoch tickets prevent older
in-flight requests from settling a newer probe. Up to four calls run concurrently;
additional calls use the local fallback immediately. No hidden retries occur.

Every hosted attempt first reserves an upper bound in PostgreSQL under tenant RLS.
Known input/output/cache usage settles that reservation once, including billed
invalid output. A timeout with unknown usage charges its full reservation. An
interrupted process leaves its reservation held until UTC day rollover; this
conservatively reduces availability rather than allowing overspend. See
[ADR-0012](adr/0012-openai-private-delivery.md) for the accounting trade-off.

Without a key, on timeout/HTTP/parse failure, or while the circuit is open/busy,
the response reports provider `extractive`, model `sentence-window-v1`. It returns
the best contiguous window of up to two sentences from the first passage. Support
requires at least 30% of the question's distinct content words in that window.
Ties choose the earliest window. This lexical rule can miss paraphrases and Croatian
inflections and can accept a passage sharing words without answering the question.
The eight-question cached-model run returned six exact answer substrings, abstained
once and missed once; see [ADR-0008](adr/0008-hybrid-query.md).

## Settings

Worker and query inherit one `EmbeddingSettings` profile from contracts. Each app
still has one cached `DI_` settings object. Existing model loaders and repository
adapters are reused from the worker package. Pipeline version remains 6.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DI_DATABASE_URL` | `DI_DATABASE_URL` from generated `.env` | PostgreSQL connection |
| `DI_MIGRATION_DATABASE_URL` | `DI_MIGRATION_DATABASE_URL` from generated `.env` | Migration/test harness only; not read by query |
| `DI_OPENAI_MODEL` | `gpt-4.1-mini-2025-04-14` | Hosted generation model |
| `DI_OPENAI_API_KEY` | empty | Enables hosted generation; empty selects extractive |
| `DI_OPENAI_API_KEY_FILE` | unset | Optional mounted UTF-8 secret; nonempty file takes precedence |
| `DI_LLM_DAILY_TOKENS` | `250000` | Per-tenant UTC-day charged plus reserved token ceiling |
| `DI_LLM_MAX_OUTPUT_TOKENS` | `700` | Maximum output tokens, 64–4096 |
| `DI_LLM_CONCURRENCY` | `4` | Concurrent hosted calls per query process, 1–32 |
| `DI_EMBED_THREADS` | `2` | ONNX threads; avoids oversubscribing a shared CPU host |
| `DI_LLM_TIMEOUT_SECONDS` | `10` | Positive HTTP timeout |
| `DI_LLM_BREAKER_FAILURES` | `3` | Consecutive failures before opening |
| `DI_LLM_BREAKER_SECONDS` | `30` | Positive cooldown before one probe |
| `DI_ABSTAIN_THRESHOLD` | `0.6` | Minimum positive lexical confidence for extractive answers |
| `DI_RRF_K` | `60` | Positive fusion rank constant |
| `DI_QUERY_TOP_K_MAX` | `20` | Candidate depth and request limit, 1–20 |
| `DI_EMBED_MODEL` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Fixed embedding profile |
| `DI_EMBED_ONNX_REPO` | `Qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q` | Fixed ONNX repository |
| `DI_EMBED_REVISION` | `faf4aa4225822f3bc6376869cb1164e8e3feedd0` | Pinned ONNX snapshot |
| `DI_TOKENIZER_REVISION` | `e8f8c211226b894fcb81acc59f3b34ba3efd5f42` | Pinned tokenizer |
| `DI_EMBED_BATCH` | `32` | Positive inference batch size |
| `DI_MODEL_CACHE` | `~/.cache/doc-insight/models` | Shared model cache |
| `HF_HUB_OFFLINE` | unset upstream | Set `1` to forbid model downloads |

The shared [observability settings](observability.md) control optional OTLP export.
Query records request spans and `query.embed`, `query.retrieve`, `query.generate`
durations without question or passage text. Unset `DI_OTEL_ENDPOINT` keeps it local.

## Run locally, fully offline

First run `python scripts/configure_local.py`. The examples use default host ports.
For alternate ports, update the host URLs and CLI arguments to match; preserve passwords.
Commands load `.env` explicitly.

Use an already populated uv/model cache and the local image
`pgvector/pgvector:0.8.6-pg16`. No Redis or other service is needed. For a clean
clone on a disconnected machine, provision those caches and the image beforehand.
The worker's installed OCR/NER dependencies are described in [pipeline.md](pipeline.md).
From the repository root in PowerShell:

```powershell
$env:UV_OFFLINE='1'
$env:HF_HUB_OFFLINE='1'
$env:DI_OPENAI_API_KEY=''
$env:COMPOSE_PROJECT_NAME='doc-insight-query'
uv sync --locked --all-packages
docker compose --profile infra up -d --wait --pull never db
uv run --env-file .env --locked --all-packages alembic upgrade head
docker compose exec db psql -U di -d di -c 'GRANT USAGE ON SCHEMA public TO di_app; GRANT SELECT, INSERT, UPDATE, DELETE ON documents, chunks, entities TO di_app;'
uv run --env-file .env --locked --all-packages di index tests/fixtures/text_hr.pdf --tenant demo
uv run --env-file .env --locked --all-packages di-query serve
```

Fresh volumes create `di_app` through the committed init script. For an older
volume, follow the [runtime-role setup](pipeline.md#storage-and-search) first.

In another terminal (use `curl.exe` in Windows PowerShell):

```sh
curl -X POST http://127.0.0.1:8002/query -H 'X-Tenant-Id: demo' -H 'Content-Type: application/json' -d '{"question":"Gdje se nalazi Zagreb?","top_k":3}'
```

Expected JSON follows; the document UUID and latency vary. The fixture mentions
people living in Zagreb but does not state where Zagreb is. Abstention is expected.

```json
{"answer":"","confidence":0.0,"abstained":true,"sources":[{"document_id":"ce2d5d6e-070f-4019-b1b3-1b83c4ea8326","page":1,"chunk_ord":0,"char_start":0,"char_end":219,"text":"Marko Marić živi u Zagrebu i radi na Sveučilištu u Zagrebu. Ana Kovačević posjetila je Split i\nDubrovnik. Ivan Horvat razgovarao je s Petrom Đurićem o Hrvatskoj. Škola čuva knjige o\nhrvatskoj povijesti i životu uz more.","score":0.01639344262295082}],"entities":[],"retrieval":{"top_k":3,"hits":1,"hybrid":true},"generation":{"provider":"extractive","model":"sentence-window-v1"},"latency_ms":3949}
```

Ask `Gdje živi Marko Marić?` for a supported extractive example. Validate and benchmark
in the same offline environment:

```sh
uv run --env-file .env --locked --all-packages pytest
uv run --env-file .env --locked --all-packages pytest -m integration --no-cov
uv run --env-file .env --locked --all-packages python scripts/eval_query.py
uv run --env-file .env --locked --all-packages python scripts/eval_query.py --provider fastembed
```

Evaluation creates a unique tenant and deletes only that tenant's fixture rows afterward.
It reports full-ranking MRR and recall@5 over the same eight questions at 120/24,
then exercises the service with extractive generation. The `external` generator
contract is excluded by default, skipped without a key, and always skipped in CI;
only an explicit `pytest -m external --no-cov` run may call the hosted model.
