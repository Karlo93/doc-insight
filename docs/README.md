# Documentation

## Use and operate

- [Quick start](../README.md)
- [API reference](api.md) and [configuration](configuration.md)
- [Docker deployment](deploy.md), [private hosting and credentials](private-deployment.md)
- [Metrics and tracing](observability.md), [captured examples](evidence/README.md)
- [Performance report](../benchmark/README.md) and reproducible measurements

## Develop

- [Architecture](architecture.md) and [code guide](code-guide.md)
- [Gateway](gateway.md), [ingest](ingest.md), [worker](worker.md), [query](query.md)
- [Processing pipeline](pipeline.md) and [local infrastructure](local-stack.md)
- [Contributing](../CONTRIBUTING.md), [CI](ci.md), [security](../SECURITY.md)
- [Changelog](../CHANGELOG.md)

## Design decisions

| ADR | Decision |
| --- | --- |
| [0001](adr/0001-text-extraction.md) | PDF text extraction and OCR fallback |
| [0002](adr/0002-structured-representation.md) | Language, entities, chunking and page offsets |
| [0003](adr/0003-embeddings-and-vector-storage.md) | CPU embeddings and vector storage |
| [0004](adr/0004-opentelemetry.md) | OpenTelemetry export |
| [0005](adr/0005-tenant-row-level-security.md) | Tenant row-level security |
| [0006](adr/0006-local-infrastructure.md) | Compose infrastructure profiles |
| [0007](adr/0007-transactional-outbox.md) | Transactional outbox and Redis delivery |
| [0008](adr/0008-hybrid-query.md) | Hybrid retrieval and extractive fallback |
| [0009](adr/0009-worker-heartbeat-identity.md) | Worker heartbeat identity |
| [0010](adr/0010-gateway-identity-and-rate-limits.md) | Authentication and quotas |
| [0011](adr/0011-compose-service-images.md) | Service images and TLS |
| [0012](adr/0012-openai-private-delivery.md) | Hosted generation and private browser access |
| [0013](adr/0013-query-grounding-and-document-context.md) | Hosted answer support and document context |
