# Changelog

Notable changes are recorded here using Keep a Changelog sections. Unreleased entries move
under a version and an ISO date when a release is cut.

## [Unreleased]

### Added

- Ship a private browser workspace for uploads, processing status, filtered questions,
  citations and token usage; add tenant-scoped document listing and usage APIs.
- Replace hosted generation with OpenAI Responses and structured citations, bounded
  concurrency, circuit breaking and durable daily token reservations/accounting.
- Add a private-server Compose overlay, file-mounted provider credentials, encrypted
  backup/isolated restore scripts, HTTP acceptance and reproducible load-test evidence.
- Connect gateway, ingest, relay, worker and OpenAI traces; capture real dashboard evidence.

- Add a code walkthrough, assignment deliverable review and online-readiness guide;
  document service/pipeline boundaries with docstrings and correct stale delivery claims.
- Keep provider credentials scoped to query; an empty key selects local extractive answers.
- Document the current CLI setup, target architecture and planned API contracts.
- Add locked service images, offline worker models and OCR, migration-first local
  startup behind Caddy TLS (`make local-run`, `make dev-token`) and main-only GHCR
  publication with SBOMs.
- Add the gateway with RS256/JWKS authentication, atomic Redis quotas, streaming uploads and verified identity headers.
- Add `di worker run`: sequential Redis consumption, tenant/object validation, version-aware replay, pending recovery, sanitized dead letters and graceful shutdown.
- Add tenant-scoped uploads, encrypted object storage, document status and an atomic outbox with a Redis Streams relay.
- Enforce FORCE row-level security with transaction-local tenant context and separate runtime/migration credentials.
- Add independent infrastructure and telemetry Compose profiles, encrypted local S3,
  provisioned Grafana dashboards, health/version smoke checks and Redis/MinIO in CI.
- Add Croatian retrieval fixtures, bilingual recall gates and English-to-Croatian evaluation reports; pipeline version stays 6.
- Add optional OTLP traces, stage/request duration metrics and document outcome counts.
- Add tenant-scoped `POST /query`, PostgreSQL hybrid retrieval, cited extractive answers, optional Mistral fallback handling and heuristic abstention.
- Persist processed documents, chunks and entities atomically in tenant-scoped Postgres tables.
- Add `di index`, `di show`, `di search`, database lifecycle targets and integration CI.
- Add contribution standards, code ownership, PR/issue templates and a security policy.


### Changed

- Speed up chunking with one page encoding and a Unicode guard that preserves the original
  chunker for unsafe pages; chunk output and pipeline version 6 remain unchanged.
- Treat malformed provider billing as unknown usage and preserve conservative budget
  charging; clear stale browser connection errors after a successful refresh.

- Isolate signing-key HTTP connections from saturated query traffic and retire
  Caddy upstream idle sockets before Uvicorn closes them.

- Run validation on every push; wait for model readiness before admitting queries.
- Provision all configured tenants in the outbox relay and reject unprovisioned identities.
- Add a GIN full-text index and cap native embedding threads; document measured capacity.

- Pipeline version 6 carries each page's language on its chunks.

[Unreleased]: https://github.com/Karlo93/doc-insight/commits/main
