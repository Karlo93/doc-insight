# Engineering journal

This journal records engineering decisions and verification notes by milestone. Each entry
explains the boundary changed, the evidence used and any remaining limitation. Keep entries
short; durable decisions and alternatives belong in ADRs, while release-facing changes belong
in the changelog.

## Contribution standards

Recorded worktree and commit conventions, the eleven review checks, test tiers and migration
discipline. Added ownership, review/issue templates and a private security-reporting path.
Documentation-only changes do not require a new architecture decision.

## Documentation — current slice and service contracts

Transcribed the reference system diagram into Mermaid and separated implemented worker/storage
behavior from the planned HTTP, queue and deployment contracts. The README starts with the
current database/CLI flow. Token tooling, captured HTTP responses and telemetry screenshots
remain dependent on the service implementations; contract examples are labeled as illustrative.
## Worker service

The CLI and consumer share one sequential pipeline. Stream messages validate tenant,
object identity and content digest before extraction. Pipeline failures store a fixed
summary; storage and database outages leave entries pending for reclaim. Tests cover
replay after commit, version replacement, poison messages, and a child process killed
after analysis and restarted against durable Redis/Postgres state. The shared S3
adapter serves both ingestion and processing. No schema or pipeline-version change.
ADR-0009 records per-consumer heartbeat identity and its progress-reporting limits.

## Gateway — public identity boundary

Added RS256 verification against cached JWKS and a generated development issuer.
One Redis Lua script owns refill and consumption for each tenant/user bucket. Chose
fail closed by default; fail open is explicit and leaves readiness unhealthy during
an outage. Request bodies stream to reused HTTP clients with declared and observed
size checks. Fake/real provider contracts cover authentication and forwarding; real
Redis tests prove exactly seven of fifty concurrent requests pass a burst of seven.
Adopted shared request instrumentation and attached only verified identity ids.

## Service images and local delivery

One parameterized multi-stage Dockerfile keeps installation and runtime policy
consistent across applications. Worker warms the existing pinned model loaders;
runtime disables Hub access and uses a read-only root with temporary scratch space.
Compose runs migrations before applications and uses separate database accounts.
Caddy proxies health through TLS; unmerged runtimes and their proxy stay pending.
Main-only publication attaches SBOM and provenance to each application image.
ADR-0008 records the Compose and TLS choices and the deferred Kubernetes path.

## Local infrastructure and telemetry

Separated storage and telemetry profiles so neither requires application images.
MinIO generates a persistent development key and the bucket job requires SSE-S3.
Collector and Tempo probes use a static binary from a pinned one-shot image.
CI reuses the MinIO Compose definition because Actions services cannot pass its
server command. Postgres and Redis use declarative services. ADR-0006 records
the alternatives; application code and pipeline output are unchanged.

## Upload service and outbox

Migration 0003 stores uploads before processing and registers their events atomically.
The receiver bounds multipart bytes before storage writes. Shared fake/real contracts
cover object storage, event publishing and upload repository methods. Restricted-login
tests cover rollback, replay, tenant isolation and competing SKIP LOCKED relays.
MinIO tests verify SSE-S3 on the stored object. Redis tests consume the event through
a temporary consumer group. ADR-0007 records delivery and orphan-object tradeoffs.
The relay requires an explicit tenant and handles shutdown between bounded batches.

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


## Query — retrieval and grounded answers

Added an internal query service and shared embedding settings. Both retrieval paths
read one PostgreSQL snapshot, including citation metadata; generation runs afterward.
Offline tests cover filters, isolation, exact page slices, breaker recovery and HTTP
errors. Windows asyncio's loopback socketpair is allowed only inside its own constructor;
ordinary sockets and libpq remain blocked in unit tests. Cached MiniLM evaluation keeps
recall@5 1.000 and MRR 0.917. Full-text contributes no hits for these natural-language
questions; six of eight extractive answers contain the expected substring, one abstains
and one misses. The confidence heuristic is not calibrated correctness. ADR-0008
records the formula, limitations and deferred GIN index. No hosted calls were needed.
The tokenizer cache-isolation test now seeds its temporary cache from the configured
model cache, so model tests can run disconnected after their artifacts are provisioned.
Rebased on the shared RLS and observability changes. Snapshots bind one tenant and
use restricted runtime credentials; a shared fake/Postgres regression proves that
a reader cannot switch to another populated tenant. Query stages adopt the shared
telemetry API. The ADR moves to 0007 to preserve the published numbering.

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
