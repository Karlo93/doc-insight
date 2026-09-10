# Scaling strategy

This is a proposed operating strategy; autoscaling and vector sharding are not
implemented. The [benchmark](../benchmark/README.md) is the capacity baseline:
100 document-list requests/s passed, 25 extractive queries/s passed, and the
four-CPU query service saturated at 100 offered queries/s. The generated corpus
was small and hosted generation was disabled. Repeat the test with realistic
tenant sizes and current code before setting a production SLO.

## Capacity and autoscaling rules

| Service | Candidate signal and action | Guardrail |
| --- | --- | --- |
| Query | Add a replica when CPU exceeds 70% for five minutes and p95 latency exceeds the chosen SLO; scale down after ten quiet minutes | Pre-warm models, configure a real load balancer and cap replicas by RAM and total database connections. Verify that extra replicas improve throughput. |
| Worker | Add consumers when the oldest queued document exceeds 60 seconds or backlog exceeds a measured per-worker batch for five minutes | Size by OCR CPU and model RAM. Keep Redis pending-message reclaim, idempotent writes and shutdown drain behavior. Scale down only after ten idle minutes. |
| Gateway/ingest | Scale on measured request latency and inflight work | Shared Redis quotas must remain consistent. Upload buffering, object-store bandwidth and the outbox may become bottlenecks. |

These thresholds are starting hypotheses, not deployed alerts or an achieved SLO.
Use stage traces to separate embedding CPU, database retrieval and provider latency.
Bound the sum of replica pool sizes below the database connection budget, retaining
headroom for migrations, relay and operations. Add admission control before allowing
queues to grow without bound. Test worker crashes, dependency outages and recovery
under load as well as steady-state throughput.

Hosted generation needs a shared provider concurrency/rate limiter before broad
horizontal scaling: the current semaphore is per process, while tenant token
reservations are database-backed. More replicas cannot bypass provider RPM/TPM
limits. Load tests must report completed requests, client-side drops, HTTP errors,
latency and token spend separately.

## Vector-store sharding

First measure query plans and index behavior with a larger corpus. Keep metadata,
chunks and vectors together in PostgreSQL while it meets the target; premature
sharding adds routing and recovery failure modes.

If one database becomes the measured limit, route each tenant to a stable virtual
shard in a server-owned mapping. Never accept a shard identifier from the browser.
Keep all of a tenant's documents on one shard and preserve forced row-level
security and tenant-scoped keys on every shard. A hot tenant can receive a dedicated
database without changing its external identity.

A move requires an explicit write pause or a verified change-capture protocol,
backfill with counts/checksums, query-parity checks, a routing cutover and a retained
rollback source. Include outbox events and token-usage state in the consistency
plan. Cross-shard operations, shard provisioning and this migration protocol do
not exist in the current application.

Multi-host deployment also requires authenticated encrypted service connections,
durable shared object storage, database/queue recovery, and tested failover. See
[security boundaries](security-boundaries.md). Scaling Compose replicas alone
does not provide high availability.
