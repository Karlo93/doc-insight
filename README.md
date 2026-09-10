# doc-insight
[![CI](https://github.com/Karlo93/doc-insight/actions/workflows/ci.yml/badge.svg)](https://github.com/Karlo93/doc-insight/actions/workflows/ci.yml)

Upload PDFs and images, search their contents, and ask questions with page-level
citations. doc-insight combines local OCR and multilingual embeddings with optional
OpenAI answer generation. A browser workspace provides uploads, processing status,
document filters, source passages and token usage.

The services run with Docker Compose. PostgreSQL row-level security isolates tenant
data; Redis Streams and a transactional outbox provide recoverable processing.
OpenTelemetry connects HTTP requests, background processing and model calls.

## Quick start

Install Docker Compose v2.24.4+, Buildx, GNU Make, Bash, Python 3 and curl, then:

```sh
git clone https://github.com/Karlo93/doc-insight.git
cd doc-insight
make local-run
make -s dev-token
```

Open [the browser](http://localhost) and paste the generated workspace token.
Upload a PDF, PNG or JPEG, wait for **processed**, then ask a question. Tokens stay
in browser memory; refresh or expiry requires reconnecting. Cold startup downloads
and warms the local models and can take several minutes.

`make local-run` generates private credentials in `.env` on first use. To choose
ports before startup, run `python scripts/configure_local.py` and edit `.env`.
Existing credentials are never overwritten. Keep host database URLs consistent
with `POSTGRES_PORT`. The browser uses
`CADDY_HTTP_PORT`; HTTPS uses `CADDY_HTTPS_PORT`.
See [deployment](docs/deploy.md) for startup details and
[private hosting](docs/private-deployment.md) for protected server access.
`make local-stop` stops the stack while preserving data volumes.

## API calls

The same workflow is available over HTTPS through the gateway. With the stack running:

```sh
TOKEN=$(make -s dev-token)
curl -fkSs -H "Authorization: Bearer $TOKEN" -F file=@tests/fixtures/text_hr.pdf https://localhost/ingest
curl -fkSs -H "Authorization: Bearer $TOKEN" https://localhost/documents/REPLACE_WITH_DOCUMENT_ID
curl -fkSs -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"question":"Gdje živi Marko Marić?","top_k":3}' https://localhost/query
```

`-k` accepts the local development certificate. Poll the status until it is
`processed`, then ask. `GET /documents` lists the tenant's library and `GET /usage`
reports the day's token accounting. See the [API contract](docs/api.md) for payloads,
status codes and error envelopes.

## Answer generation

OCR, embeddings, search and extractive answers run without paid API credentials.
For OpenAI answers, configure the query service with a server-side API key using
the [credential instructions](docs/private-deployment.md#api-credentials-and-token-usage).
Never paste the provider key into the browser.

Answers include their actual provider, model and token usage. Daily tenant budgets
bound hosted usage. The app abstains when retrieved passages do not support an
answer. Citations identify evidence; they do not guarantee that every generated
statement follows from it. Image retrieval uses OCR text, so diagram layout and
arrows may need interpretation beyond the extracted text.

## Architecture and operations

```text
Browser → Caddy → Gateway → Ingest → Object storage + PostgreSQL outbox
                    │                         ↓
                    │                   Relay → Redis → Worker
                    │                                     ↓
                    └──────→ Query ← PostgreSQL / pgvector index
                               └──→ OpenAI (optional)
```

- [Architecture](docs/architecture.md) and [code guide](docs/code-guide.md)
- [API](docs/api.md), [configuration](docs/configuration.md) and [runbooks](docs/README.md)
- [Metrics and distributed tracing](docs/observability.md), with [captured examples](docs/evidence/README.md)
- [100 req/s benchmark report and graph](benchmark/README.md)
- [Security boundaries](docs/security-boundaries.md), [scaling strategy](docs/scaling.md) and [cost estimate](docs/costs.md)

The recorded single-server benchmark sustained 100 document-list requests/s and
25 extractive queries/s on a small generated corpus. At 100 offered queries/s the
query service saturated. These are historical measurements, not an OpenAI
throughput guarantee or a benchmark of subsequent query changes.

The app currently uses operator-issued JWTs. Self-service accounts, multi-node
availability and Kubernetes deployment are not implemented.

## Development

Install uv, Python 3.12, GNU Make, Go 1.24.11+ and Tesseract with English/Croatian
language data. See [platform setup](docs/pipeline.md#run-it-wsl2linux).

```sh
make setup
uv run --locked pre-commit install
make check
make db-up
make test-integration
```

Default tests run offline; integration tests use disposable service-backed databases.
Model-download tests are opt-in with `make test-models`.
See [CONTRIBUTING](CONTRIBUTING.md), [CI](docs/ci.md), [security](SECURITY.md)
and [support](SUPPORT.md).

| Directory | Purpose |
| --- | --- |
| `apps/` | Gateway, ingest, query and worker services |
| `packages/` | Shared contracts, telemetry and test fakes |
| `frontend/` | Static browser application |
| `migrations/` | Database schema changes |
| `deploy/`, `infra/` | Compose overlays and telemetry configuration |
| `tests/` | Tests and generated document fixtures |
| `benchmark/` | Reproducible performance results and plotting source |
| `docs/` | Architecture, API, runbooks and design decisions |

## License

Project code is available under [PolyForm Noncommercial 1.0.0](LICENSE.md).
Noncommercial use, modification and sharing are permitted under those terms.
Commercial use requires separate written permission from [Karlo93](https://github.com/Karlo93).
Third-party components retain their respective licenses.
