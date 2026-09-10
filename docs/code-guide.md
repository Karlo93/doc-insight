# Code walkthrough

The application is a Python 3.12 uv workspace. Four service packages share typed
contracts, a processing pipeline and PostgreSQL adapters. A static browser frontend
is served by Caddy and calls the authenticated API.
Read [architecture](architecture.md) for the data flow and [assignment review](assignment-review.md)
for the historical gap analysis. This guide describes the private release.

## Read the code in this order

Paths below are relative to the repository. Within an application,
`src/doc_insight/<application>/` contains the modules named in the table.

| Boundary | Files to read | Responsibility |
| --- | --- | --- |
| Browser | `frontend/app.js`, `upload.js`, `views.js`, `style.css` | In-memory workspace authentication, upload progress, library polling, filtered questions and cited evidence |
| Public API | `apps/gateway`: `main.py`, `proxy.py`, `auth.py`, `rate_limit.py` | FastAPI lifespan and routes; JWT/JWKS verification; per-user Redis quotas; bounded streaming to internal services |
| Upload | `apps/ingest`: `main.py`, `upload.py`, `service.py`, `adapters.py` | Validate multipart bytes, spool to temporary storage, hash and sniff content, store originals, register upload |
| Durable publication | `apps/worker`: `uploads.py`; `apps/ingest`: `relay.py` | Commit document and outbox together; publish unpublished rows to Redis for every configured tenant |
| Background processing | `apps/worker`: `worker_cli.py`, `service.py`, `streams.py`, `processing.py` | Own runtime clients; consume/reclaim deliveries; validate event against stored metadata; download and verify original; acknowledge or dead-letter |
| Shared pipeline | `apps/worker`: `pipeline.py`, `extraction.py`, `structure.py`, `embedding.py` | Extract, detect language, find entities, chunk, embed and persist; same implementation used by CLI and consumer |
| Model adapters | `apps/worker`: `providers.py`, `embedder.py` | Lazy cached Lingua, spaCy, tokenizer and CPU ONNX models; enforce input limits |
| Persistence | `apps/worker`: `repository.py`, `query_repository.py`, `uploads.py`; `migrations/versions/` | Atomic replacement, tenant-bound transactions, consistent query snapshots and SQL schema |
| Question answering | `apps/query`: `main.py`, `runtime.py`, `service.py`, `ranking.py` | Validate request, own clients, combine vector/text rankings, select citations, score confidence and abstain |
| Document selection | `apps/query`: `retrieval.py` | Recognize document names with small spelling errors, preserve explicit filters, and retrieve content terms within one tenant snapshot |
| Token accounting | `apps/query`: `usage.py`; `packages/contracts`: `usage.py`; migration 0004 | Atomic tenant/day reservations, idempotent settlement and conservative ambiguous-failure charging |
| Answer providers | `apps/query`: `generation.py`, `openai_provider.py`, `extractive.py` | Optional OpenAI call with citation parsing and breaker; local sentence-window fallback |
| Shared interfaces | `packages/contracts/src/doc_insight/contracts/` | Pydantic data shapes and Protocols for storage, embeddings, generation, streams, identity and telemetry |
| Observability | `packages/observability/src/doc_insight/observability/` | HTTP spans, stage timers, metrics, W3C context helpers and export configuration |
| Test doubles | `packages/testing/src/doc_insight/testing/` | Deterministic in-memory providers for shared contracts and failure-path tests |
| Deployment | `Dockerfile`, `docker-compose.yml`, `deploy/`, `scripts/local_run.sh` | Image build, model cache, startup ordering, migrations, local identity and HTTPS |

`packages/domain` is still a reserved namespace. Storage and shared model adapters
currently live in the worker package, so ingest and query depend on worker; the
directory names do not imply fully independent deployable libraries.

Function docstrings describe the service and adapter contracts. Inline comments
explain decisions at the point they matter: transaction ownership and duplicate
deliveries in persistence/worker code, token settlement and citation checks in query,
and session lifetime and text-only rendering in the browser. Start with these
boundaries when tracing a failure; the sections below connect them into full flows.

## Upload to searchable content

1. The gateway verifies a JWT, derives tenant/user identity, consumes a rate-limit
   token and replaces identity headers before forwarding. Internal APIs trust those
   headers and must remain inaccessible to untrusted callers.
2. Ingest validates and hashes the upload. A duplicate hash within a tenant returns
   its existing ID. Otherwise it stores `{tenant}/{sha256}` in object storage and
   registers the document and outbox event in one SQL transaction.
3. The relay locks unpublished rows for its configured tenant, publishes to
   `di:documents`, then marks them published. A crash after publish can duplicate
   delivery. The object write is also outside the SQL transaction: failed registration
   can leave an orphan object.
4. The worker checks the event against the stored document, verifies downloaded
   byte count/hash/media type and runs `Pipeline.index`. A completed document at the
   current pipeline version can be acknowledged without reprocessing.
5. Pipeline output is replaced atomically. Transient storage errors leave deliveries
   pending; terminal processing errors and exhausted attempts go through the failed
   status/dead-letter path. Acknowledgement follows durable completion.

The consumer is deliberately sequential: PDFium is not thread-safe and Tesseract's
command setting is process-global. Use separate processes for concurrency, and
measure the interaction between processing time, heartbeat TTL and reclaim timing.

## Question to cited answer

`QueryService.query` embeds the question, opens a tenant-bound repeatable-read
snapshot, obtains vector and full-text candidates, fuses ranks and reads document
metadata. It closes the database transaction before calling the answer provider.
Generation precedes the final confidence/abstention decision, so an eventual
abstention can still consume hosted tokens when OpenAI is enabled.

The generator returns cited passage indexes. `_response` validates those indexes,
computes a lexical grounding/rank-margin heuristic and either returns the answer
with cited sources/entities or abstains with the retrieved passages available for
inspection. Confidence is not a probability of correctness. Hosted citation-format
validation is not a semantic proof that each statement follows from its source.

## Data invariants worth preserving

- Page numbers are one-based; chunk ordinals and character offsets are zero-based.
  End offsets are exclusive Python character positions in normalized page text.
- Chunks stay within a page and contain at most 120 content tokens by default,
  with up to 24 overlap. Embeddings reject more than 126 content tokens, including
  questions; the model has a 128-token input including special tokens.
- Vectors are 384-dimensional, finite and nonzero. Tokenizer, model revision,
  chunking and stored pipeline version form one compatibility boundary.
- Entity deduplication preserves the first occurrence and a document-wide count.
  NER is limited to a configured prefix budget; chunking still covers all pages.
- Runtime SQL uses the restricted role and binds tenant context per transaction.
  Forced RLS, explicit filters and composite foreign keys work together. Migration
  credentials are separate and must not be used by service runtimes.
- Re-indexing the same tenant/hash replaces derived rows atomically. It does not
  create an independently versioned copy of every prior analysis.

## Extending the implementation

For a new provider, begin with its Protocol and shared contract tests, implement a
deterministic fake, then add the real adapter and lifespan/configuration wiring.
Keep network/model I/O outside SQL transactions unless the lock is intentional,
as in outbox publication. See [contribution standards](../CONTRIBUTING.md).

Changing embeddings also affects chunk limits, vector dimensions/indexes and
re-indexing; see [ADR-0003](adr/0003-embeddings-and-vector-storage.md). A new endpoint
needs a request/response contract, tenant enforcement, gateway route, service tests,
configuration mapping and API documentation. Adding a Pydantic setting alone does
not make a value from `.env` appear inside a container.

Run `uv run --locked --all-packages pytest` for offline unit/contract tests.
`-m integration --no-cov` selects real storage/service adapter tests;
`-m models --no-cov` selects actual model tests. The [CI guide](ci.md) lists all gates.
Those tiers do not currently replace a complete gateway-to-worker-to-query E2E test.
