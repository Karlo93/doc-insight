# Engineering journal

## Documentation — current slice and service contracts

Transcribed the reference system diagram into Mermaid and separated implemented worker/storage
behavior from the planned HTTP, queue and deployment contracts. The README starts with the
current database/CLI flow. Token tooling, captured HTTP responses and telemetry screenshots
remain dependent on the service implementations; contract examples are labeled as illustrative.

## Local infrastructure and telemetry

Separated storage and telemetry profiles so neither requires application images.
MinIO generates a persistent development key and the bucket job requires SSE-S3.
Collector and Tempo probes use a static binary from a pinned one-shot image.
CI reuses the MinIO Compose definition because Actions services cannot pass its
server command. Postgres and Redis use declarative services. ADR-0006 records
the alternatives; application code and pipeline output are unchanged.

## Shared observability

Added process-owned OpenTelemetry providers behind the stage observer contract.
No endpoint selects no-op providers and creates no exporter threads. In-memory SDK
tests check timings, propagation, failures and request attribute privacy. Pipeline
stages keep their CLI durations; a process span counts each document attempt.
Request middleware records route templates and status codes. It omits raw URLs,
headers and exception messages before they can enter telemetry.

## Bilingual retrieval evaluation

Added twelve independent Croatian topics and eight paraphrased questions with English
translations. Both languages require unique source answers and MiniLM recall@5 ≥ 0.8 at
64/8. Croatian MiniLM measured 1.000 recall and 0.581 MRR; production 120/24 measured
0.875 and 0.896. The Croatian keyword baseline measured 0.500 recall, so its gate is
explicitly 0.5 because whitespace hashing misses inflected forms. English-to-Croatian
retrieval measured 1.000 recall and 0.875 MRR at both sizes, reported without a gate.
ADR-0003 records the complete results and limits. The committed font covers every Croatian
diacritic; existing fixtures regenerate byte-identically. No stored output or pipeline version changes.
## M4 — persistent core

Kept extraction and inference outside the write transaction; the unique tenant/hash upsert
locks the document while all derived output is replaced. Migration SQL owns the schema;
SQLAlchemy reflects it to avoid duplicating column declarations. Shared fake/Postgres contracts
check replay and tenant boundaries; injected failures and concurrent writers exercise the real
transaction. Database tests use disposable databases, protecting local demo data.

## Tenant isolation in the database

Migration 0002 applies FORCE RLS to documents, chunks and entities. Every repository
transaction binds a local tenant setting. Restricted-login tests cover raw SQL isolation,
missing context, pool reuse, owner enforcement, replay and reversible migrations.
Runtime credentials are separate from the privileged migration connection. ADR-0005
records the shared-table choice and its trust boundary. Pipeline output is unchanged.
