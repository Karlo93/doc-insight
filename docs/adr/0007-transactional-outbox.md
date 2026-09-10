# ADR-0007: Transactional outbox and Redis Streams

Status: accepted. Date: 2026-09-10.

## Decision

Store the original object first, then insert upload metadata and `document.uploaded`
in one Postgres transaction. A separate tenant-scoped relay publishes pending events
to Redis Streams and commits `published_at`. Use the restricted application role,
transaction-local tenant context and FORCE RLS on the outbox. Require `--tenant` on
the relay CLI; operate one loop per tenant, with concurrent instances allowed.

Hold `FOR UPDATE SKIP LOCKED` row locks through XADD and commit. Stable event IDs
make acknowledgement loss detectable downstream. Delivery is at least once:
if Redis succeeds but the database commit fails, the event is published again.
Consumers must be idempotent. Redis persistence and retention are operational
requirements; the outbox cannot undo a later loss of acknowledged Redis data.

Use deterministic tenant/hash object keys and SSE-S3. A failed DB transaction may
leave an orphan object. A retry overwrites identical bytes; unused orphans need a
future janitor with a grace period. No synchronous object deletion follows a DB
error, because another concurrent request may have committed that same key.

## Alternatives and consequences

- Direct publish before commit can send events for rolled-back uploads; direct
  publish after commit can permanently lose events when the process stops between
  commit and publish. The outbox closes both gaps without a distributed transaction.
- Kafka or RabbitMQ would add another broker and operational model. Redis Streams
  already supplies consumer groups, replay and pending-message tracking needed here.
  Neither broker would remove the Postgres-to-broker atomicity gap by itself.
- A privileged relay could scan all tenants, but would bypass the database isolation
  rule. Explicit tenant loops preserve that rule and make tenant provisioning an
  operational responsibility. A scheduler can start additional tenant loops later.
- Network I/O extends transaction duration. Bound batches and client timeouts limit
  lock duration. This design favors simple, testable delivery over maximum throughput.

Uploads keep unknown derived fields null. Processing populates them and preserves
object metadata. Migration downgrade refuses incomplete rows rather than creating
fictional processing results. Pipeline output and its version do not change.
