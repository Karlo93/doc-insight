# Engineering journal

## Shared observability

Added process-owned OpenTelemetry providers behind the stage observer contract.
No endpoint selects no-op providers and creates no exporter threads. In-memory SDK
tests check timings, propagation, failures and request attribute privacy. Pipeline
stages keep their CLI durations; a process span counts each document attempt.
Request middleware records route templates and status codes. It omits raw URLs,
headers and exception messages before they can enter telemetry.

## M4 — persistent core

Kept extraction and inference outside the write transaction; the unique tenant/hash upsert
locks the document while all derived output is replaced. Migration SQL owns the schema;
SQLAlchemy reflects it to avoid duplicating column declarations. Shared fake/Postgres contracts
check replay and tenant boundaries; injected failures and concurrent writers exercise the real
transaction. Database tests use disposable databases, protecting local demo data.
