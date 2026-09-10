# Changelog

Notable changes are recorded here using Keep a Changelog sections. Unreleased entries move
under a version and an ISO date when a release is cut.

## [Unreleased]

### Added

- Document the current CLI setup, target architecture and planned API contracts.
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

- Pipeline version 6 carries each page's language on its chunks.

[Unreleased]: https://github.com/Karlo93/doc-insight/commits/main
