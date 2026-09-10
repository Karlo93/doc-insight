# ADR-0006: Independent infrastructure and telemetry profiles

Status: accepted. Date: 2026-09-10.

## Decision

Separate Compose infrastructure and telemetry profiles so storage tests can run
before application images exist. Keep exact upstream image tags and bind host
ports to loopback with overrides. Retain data in project-scoped named volumes.
Use Prometheus for metrics and single-process Tempo with local storage for traces;
provision both into Grafana. This implements the collector boundary in ADR-0004.

Use a generated, persisted development MinIO key and fail bucket initialization
unless SSE-S3 is enabled. Production uses TLS and provider-managed KMS. No key
material is committed. Copy a static probe binary from pinned BusyBox for the
collector and Tempo health checks, avoiding custom infrastructure builds.

## Alternatives and consequences

- A single full-stack profile would require application builds for storage work.
- Hosted telemetry or distributed Tempo adds credentials and operational services
  before local development needs them. Local volumes are not a production HA design.
- Custom probe images add build steps; process-version checks do not prove readiness.
- Disabling MinIO encryption hides integration errors. A separate KMS would improve
  key isolation but adds a service to the local stack; the development key volume
  must be preserved alongside data.
- GitHub Actions service declarations cannot supply a command. Start the official
  MinIO image through the same Compose definition in the test job, with health and
  bucket checks before tests and unconditional cleanup. Postgres and Redis use
  declarative service containers. This avoids a CI-only wrapper image.
