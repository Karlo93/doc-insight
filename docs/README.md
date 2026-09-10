# Documentation index

- [Project README](../README.md): local setup, CLI commands, test tiers and repository layout.
- [Architecture](architecture.md): system and sequence diagrams, responsibilities, boundaries and trade-offs.
- [Query service](query.md): implemented retrieval, cited answers, offline operation and settings.
- [Ingest service](ingest.md): upload validation, object storage, outbox relay and status reads.
- [API contract](api.md): upload, status, question and stream payloads; delivery status is explicit.
- [Configuration](configuration.md): current settings tables, defaults and Compose versus Python environment handling.
- [Pipeline](pipeline.md): implemented extraction, OCR, structure, embeddings, storage and retrieval.
- [Worker](worker.md): sequential consumption, recovery, dead letters and manual object/event examples.
- [Local stack](local-stack.md): Compose `infra` and `telemetry` profiles, ports, encryption and Grafana.
- [Deployment](deploy.md): service images, local startup, pending activation, environment and Caddy TLS.
- [Observability](observability.md): the shared OpenTelemetry helper, emitted signals and attribute policy.
- [Gateway](gateway.md): JWT/JWKS authentication, rate limits, proxy behavior and development token setup.
- [CI](ci.md): lint, types, tests, security checks and repository protection setup.
- [Engineering journal](journal.md): implementation notes by milestone.
- [Lessons](lessons.md): concise observations from implementation and failure cases.
- [ADR-0001](adr/0001-text-extraction.md): PDFium/Tesseract extraction and alternatives.
- [ADR-0002](adr/0002-structured-representation.md): language, entities, chunk budgets and exact offsets.
- [ADR-0003](adr/0003-embeddings-and-vector-storage.md): MiniLM, ONNX, pgvector and upgrade criteria.
- [ADR-0004](adr/0004-opentelemetry.md): OpenTelemetry with OTLP export to a collector.
- [ADR-0005](adr/0005-tenant-row-level-security.md): forced row-level security and separate runtime/migration roles.
- [ADR-0006](adr/0006-local-infrastructure.md): independent infrastructure and telemetry Compose profiles.
- [ADR-0007](adr/0007-transactional-outbox.md): transactional outbox and Redis Streams delivery.
- [ADR-0008](adr/0008-hybrid-query.md): hybrid retrieval with RRF, extractive fallback and confidence.
- [ADR-0009](adr/0009-worker-heartbeat-identity.md): one progress heartbeat per consumer process.
- [ADR-0010](adr/0010-gateway-identity-and-rate-limits.md): RS256/JWKS identity and fail-closed Redis quotas.
- [ADR-0008](adr/0008-compose-service-images.md): Compose delivery, service images and Caddy TLS.
- [Changelog](../CHANGELOG.md): changes awaiting release.
- [Contributing](../CONTRIBUTING.md): branch/commit conventions, test tiers, budgets and review checklist.
- [Security policy](../SECURITY.md): private reporting, supported versions and secrets handling.
- [PR template](../.github/pull_request_template.md): required review sections and eleven checks.
- [Bug report](../.github/ISSUE_TEMPLATE/bug_report.md): minimal reproduction and sanitized evidence.
- [Task template](../.github/ISSUE_TEMPLATE/task.md): scope, acceptance criteria and validation.
- [Fixture font provenance](../scripts/fonts/readme.md): generated fixture font and its license.

The current application runbooks are [Pipeline](pipeline.md) and [Worker](worker.md).
Additional service runbooks and the final demo walkthrough will be linked as they land.
