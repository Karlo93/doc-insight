# doc-insight
[![CI](https://github.com/Karlo93/doc-insight/actions/workflows/ci.yml/badge.svg)](https://github.com/Karlo93/doc-insight/actions/workflows/ci.yml)

doc-insight extracts text from PDFs and images, detects language and entities, and builds searchable passages.
The worker CLI stores documents and 384-dimensional embeddings in tenant-scoped Postgres tables.
Authenticated uploads and cited answers are the next service layer; the [architecture](docs/architecture.md) distinguishes implemented behavior from planned contracts.

## Prerequisites

- Git, uv, Python 3.12 (selected by uv), GNU Make and Go 1.24.11+ for the security gate.
- Docker with Compose v2 for Postgres and pgvector.
- Tesseract with English (`eng`) and Croatian (`hrv`) data; verify with `tesseract --list-langs`.
- Network access for dependency installation and the first tokenizer/embedding download (about 0.22 GB for weights).

See [Windows and WSL/Linux setup](docs/pipeline.md#run-it-wsl2linux) for OCR installation.

## Local setup

`make local-run` is not available yet (lands with lane 5). The working entry point is
the CLI plus the database-only Compose file. Run from a clone:

```sh
git clone https://github.com/Karlo93/doc-insight.git
cd doc-insight
make setup
```

Choose a free database port and export it for both Compose and Python. For Bash:

```sh
export POSTGRES_PORT=55432
export DI_DATABASE_URL=postgresql+psycopg://di:di@127.0.0.1:55432/di
```

For PowerShell:

```powershell
$env:POSTGRES_PORT = '55432'
$env:DI_DATABASE_URL = 'postgresql+psycopg://di:di@127.0.0.1:55432/di'
```

Then, in either shell:

```sh
make db-up
make migrate
uv run --locked --all-packages di index tests/fixtures/text_hr.pdf --tenant demo
uv run --locked --all-packages di search "Gdje se nalazi Zagreb?" --tenant demo -k 5
```

`db-up` waits for a healthy database; migration applies `0001_core_tables` on a new database.
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
`make db-down` stops Compose and keeps the named database volume.

Compose currently runs only Postgres, bound to loopback. There are no application images,
Caddy configuration or Kubernetes manifests yet (lands with lane 5).

## API status and examples

The gateway, ingest and query packages are currently workspace shells (land with lanes 4, 1 and 3).
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
`make db-up` and creates disposable databases using the exported URL. Neither tier replaces
the default coverage gate. See [CI](docs/ci.md) for individual commands and prerequisites.

## Configuration

The cached worker settings read `DI_` environment variables at process startup.
See the [settings index](docs/configuration.md) for defaults and links to every settings table.
Compose reads `.env`; Python currently requires exported variables, including `DI_DATABASE_URL`.
The checked-in `.env.example` contains the database settings; other worker options are in the tables.

## Design summary

The worker keeps extraction and model I/O at provider boundaries.
Protocols live in `packages/contracts`; deterministic fakes live in `packages/testing`.
PDFium reads PDF text, with Tesseract OCR below the configured threshold.
Lingua detects language and spaCy extracts English/Croatian entities.
Chunks retain exact page offsets and use 120 tokens with up to 24 overlap.
FastEmbed runs pinned multilingual MiniLM weights on CPU through ONNX.
Queries and passages reject more than 126 content tokens instead of truncating.
Postgres stores metadata, entities, chunks and pgvector embeddings in one transaction.
Tenant filters and composite foreign keys isolate the current storage slice.
See [architecture and trade-offs](docs/architecture.md) for the planned service paths and three ADRs.

## Repository layout

| Path | Purpose |
| --- | --- |
| `apps/worker` | Extraction, analysis, embedding, storage and CLI |
| `apps/{gateway,ingest,query}` | Reserved service packages |
| `packages/{contracts,testing}` | Shared types, Protocols and fakes |
| `packages/{domain,observability}` | Reserved shared packages |
| `migrations` | Alembic revisions containing raw SQL |
| `tests`, `scripts` | Contract tests, generated fixtures and retrieval evaluation |
| `docs` | [Documentation index](docs/README.md), architecture and ADRs |

## License

No project license has been selected or committed. The fixture font has its own
[provenance](scripts/fonts/readme.md) and [license](scripts/fonts/ofl.txt).
