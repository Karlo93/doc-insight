# doc-insight
[![CI](https://github.com/Karlo93/doc-insight/actions/workflows/ci.yml/badge.svg)](https://github.com/Karlo93/doc-insight/actions/workflows/ci.yml)

doc-insight extracts text from PDFs and images, detects language and entities, and builds searchable passages.
The worker CLI stores documents and 384-dimensional embeddings in tenant-scoped Postgres tables.
The internal ingest and query services accept uploads and return cited answers or abstain. The authenticating gateway is the next service layer; the [architecture](docs/architecture.md) distinguishes implemented behavior from planned contracts.

## Prerequisites

- Git, uv, Python 3.12 (selected by uv), GNU Make and Go 1.24.11+ for the security gate.
- Docker with Compose v2 for Postgres/pgvector, Redis, MinIO and the optional telemetry stack; Bash (Git Bash on Windows) for the smoke script.
- Tesseract with English (`eng`) and Croatian (`hrv`) data; verify with `tesseract --list-langs`.
- Network access for dependency installation and the first tokenizer/embedding download (about 0.22 GB for weights).

See [Windows and WSL/Linux setup](docs/pipeline.md#run-it-wsl2linux) for OCR installation.

## Local setup

`make local-run` and the application images are not available yet (they land with lane 5's
final PR). The working entry point is the CLI plus the Compose `infra` profile (Postgres/pgvector,
Redis, MinIO); the `telemetry` profile is optional. See [local stack](docs/local-stack.md) for
ports, profiles and encryption. Run from a clone:

```sh
git clone https://github.com/Karlo93/doc-insight.git
cd doc-insight
make setup
```

Choose a free database port and export it for both Compose and Python. The runtime URL uses
the restricted `di_app` login; migrations use the privileged `di` login. For Bash:

```sh
export POSTGRES_PORT=55432
export DI_DATABASE_URL=postgresql+psycopg://di_app:di_app@127.0.0.1:55432/di
export DI_MIGRATION_DATABASE_URL=postgresql+psycopg://di:di@127.0.0.1:55432/di
```

For PowerShell:

```powershell
$env:POSTGRES_PORT = '55432'
$env:DI_DATABASE_URL = 'postgresql+psycopg://di_app:di_app@127.0.0.1:55432/di'
$env:DI_MIGRATION_DATABASE_URL = 'postgresql+psycopg://di:di@127.0.0.1:55432/di'
```

Alternatively copy `.env.example` to `.env` for Compose and export the matching `DI_` values.

Then, in either shell:

```sh
make db-up
make migrate
uv run --locked --all-packages di index tests/fixtures/text_hr.pdf --tenant demo
uv run --locked --all-packages di search "Gdje se nalazi Zagreb?" --tenant demo -k 5
```

`db-up` starts the `infra` profile and runs the smoke script, which waits for health; on a
fresh volume the database creates the restricted `di_app` login automatically. `make migrate`
applies `0001_core_tables` and `0002_row_level_security` using the migration URL.
One recorded indexing run printed the following; UUID and durations vary by run:

```text
extract=0.004s analyze=1.919s embed=3.356s store=0.319s
Document: a503d377-53db-4141-85f0-fd2921ecf163 | Chunks: 1 | Tenant: demo
```

Search returned that document on page 1 with cosine score `0.746` and the Croatian passage.
It prints document UUID, page, cosine score and passage text. Copy your returned UUID:

```sh
uv run --locked --all-packages di show <document-id> --tenant demo
```

Replace `<document-id>` before running. Re-indexing the same bytes for `demo` preserves
the UUID and replaces the stored output atomically; it still runs extraction and inference.
`make db-down` stops the `infra` profile and keeps its named volumes.

Compose runs infrastructure only, all bound to loopback: Postgres, Redis and MinIO in `infra`,
and the OpenTelemetry collector, Prometheus, Tempo and Grafana in `telemetry`
(`make telemetry-up`). There are no application images, Caddy configuration or Kubernetes
manifests yet (they land with lane 5).

## API status and examples

The [query service](docs/query.md) implements `POST /query` on port 8002, with offline
extractive answers, citations and abstention. Start it with `di-query serve` after indexing
a fixture. The [ingest service](docs/ingest.md) accepts uploads and serves status on port 8001;
the gateway package remains a workspace shell.
The planned sequence is mint a development token → `POST /ingest` →
`GET /documents/{id}` until processed → `POST /query`.
See the [API contract](docs/api.md) for payloads, status codes and planned curl calls.
Token commands and real HTTP responses will be added after the services merge and run together;
the contract examples are not recorded server responses.

## CLI

Prefix each command with `uv run --locked --all-packages`:

| Command | Result |
| --- | --- |
| `di extract tests/fixtures/mixed.pdf` | Text layer or OCR per page; previews |
| `di extract tests/fixtures/text_hr.pdf --json` | Full extraction JSON |
| `di analyze tests/fixtures/text_hr.pdf` | Languages, entities and chunk statistics |
| `di analyze tests/fixtures/text_hr.pdf --embed --json` | Structured output plus vectors |
| `di index tests/fixtures/text_hr.pdf --tenant demo` | Process and persist atomically |
| `di show <document-id> --tenant demo` | Stored metadata, chunks and entities |
| `di search "Zagreb" --tenant demo -k 5` | Nearest tenant-owned passages |

`extract` and `analyze` are stateless. Storage commands require a nonblank tenant supplied by
the caller; the current CLI does not authenticate it. CLI previews/JSON are document data,
not logs; keep redirected output in ignored `inputs/` or `.cache/`.

## Tests

```sh
make check
make test-models
make test-integration
```

`check` runs Ruff, strict mypy, the default tests with a 70% coverage floor, Bandit,
pip-audit and gitleaks. Default tests block network connections and need installed OCR data.
`test-models` may download pinned tokenizer/embedding snapshots; `test-integration` needs
`make db-up` and creates disposable databases using the exported migration URL. Neither tier replaces
the default coverage gate. See [CI](docs/ci.md) for individual commands and prerequisites.

## Configuration

The cached worker settings read `DI_` environment variables at process startup.
See the [settings index](docs/configuration.md) for defaults and links to every settings table.
Compose reads `.env`; Python currently requires exported variables, including `DI_DATABASE_URL`.
The checked-in `.env.example` contains the database, Redis, S3 and telemetry settings; other
worker options are in the tables.

## Design summary

The worker keeps extraction and model I/O at provider boundaries.
Protocols live in `packages/contracts`; deterministic fakes live in `packages/testing`.
PDFium reads PDF text, with Tesseract OCR below the configured threshold.
Lingua detects language and spaCy extracts English/Croatian entities.
Chunks retain exact page offsets and use 120 tokens with up to 24 overlap.
FastEmbed runs pinned multilingual MiniLM weights on CPU through ONNX.
Queries and passages reject more than 126 content tokens instead of truncating.
Postgres stores metadata, entities, chunks and pgvector embeddings in one transaction.
Tenant filters, composite foreign keys and forced row-level security isolate the storage slice;
the runtime login cannot bypass or disable the policy. Optional OpenTelemetry export gives
stage and request timings without document data.
See [architecture and trade-offs](docs/architecture.md) for the planned service paths and the ADRs.

## Repository layout

| Path | Purpose |
| --- | --- |
| `apps/worker` | Extraction, analysis, embedding, storage and CLI |
| `apps/query` | Internal hybrid retrieval and grounded answers |
| `apps/ingest` | Upload validation, object storage, outbox relay and status reads |
| `apps/gateway` | Reserved service package |
| `packages/{contracts,testing}` | Shared types, Protocols and fakes |
| `packages/observability` | OpenTelemetry setup, stage spans, request metrics and trace propagation |
| `packages/domain` | Reserved shared package |
| `migrations` | Alembic revisions containing raw SQL |
| `infra`, `deploy`, `docker-compose.yml` | Collector, Prometheus, Tempo and Grafana configuration; Postgres init script; Compose profiles |
| `tests`, `scripts` | Contract tests, generated fixtures and retrieval evaluation |
| `docs` | [Documentation index](docs/README.md), architecture and ADRs |

## License

See [Contributing](CONTRIBUTING.md) for contribution standards and [Security](SECURITY.md)
for private vulnerability reporting.

No project license has been selected or committed. The fixture font has its own
[provenance](scripts/fonts/readme.md) and [license](scripts/fonts/ofl.txt).
