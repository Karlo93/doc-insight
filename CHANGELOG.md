# Changelog

## Unreleased

- Enforce FORCE row-level security with transaction-local tenant context and separate runtime/migration credentials.
- Add optional OTLP traces, stage/request duration metrics and document outcome counts.
- Persist processed documents, chunks and entities atomically in tenant-scoped Postgres tables.
- Add `di index`, `di show`, `di search`, database lifecycle targets and integration CI.
- Pipeline version 6 carries each page's language on its chunks.
