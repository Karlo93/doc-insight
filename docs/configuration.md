# Configuration index

The current worker uses one cached Pydantic-settings object with `env_prefix="DI_"`.
Values are validated at process startup. Export variables before invoking the CLI;
its settings class does not configure `.env` loading. Compose reads `.env` separately.

| Settings | Defaults and purpose |
| --- | --- |
| OCR: `DI_OCR_MIN_CHARS`, `DI_OCR_DPI`, `DI_OCR_LANGS`, `DI_TESSERACT_CMD` | [Extraction table](pipeline.md#pipeline-files-to-searchable-documents) |
| Language, NER, chunking, tokenizer and cache | [Structure table](pipeline.md#structure-m2) |
| Query: `DI_LLM_*`, `DI_ABSTAIN_THRESHOLD`, `DI_RRF_K`, `DI_QUERY_TOP_K_MAX` | [Query settings](query.md#settings); shares the embedding profile with worker |
| Embedding batch and pinned ONNX snapshot | [Embedding table](pipeline.md#embeddings-m3) |
| `DI_DATABASE_URL` | `postgresql+psycopg://di_app:di_app@localhost:5432/di`; restricted runtime login for the CLI and storage code; cannot bypass row-level security |
| `DI_MIGRATION_DATABASE_URL` | `postgresql+psycopg://di:di@localhost:5432/di`; privileged login for `make migrate` and the disposable integration databases |
| `DI_ALLOW_REMOTE_TEST_DB` | Unset; the integration harness refuses nonlocal database hosts unless explicitly enabled |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Each defaults to `di`; Compose development database initialization; a fresh volume also creates `di_app` |
| `POSTGRES_PORT` | `5432`; Compose host port, bound to `127.0.0.1`; export matching `DI_DATABASE_URL` and `DI_MIGRATION_DATABASE_URL` values if changed |
| `DI_OTEL_ENDPOINT`, `DI_OTEL_SERVICE_NAME`, `DI_OTEL_TIMEOUT_SECONDS`, `DI_ENV` | [Observability](observability.md); unset or empty endpoint disables export |
| `COMPOSE_PROJECT_NAME` | Compose override for resource isolation; otherwise this file uses `doc-insight-core` |

The database variables appear in [`.env.example`](../.env.example); the other implemented
worker settings are documented in the linked pipeline tables and
[settings class](../apps/worker/src/doc_insight/worker/settings.py).
`DI_ALLOW_REMOTE_TEST_DB` belongs to the test harness, not the worker settings object.

`DI_REDIS_URL` and the six `DI_S3_*` variables appear in `.env.example` and CI as connection
conventions for the [local stack](local-stack.md); the adapters that read them, and
`DI_MAX_UPLOAD_BYTES`, land with lane 1. Until then no worker option consumes them. The
observability package validates its own `DI_OTEL_*` settings once at `configure()`. Add
default/purpose tables with each service implementation; do not infer unset defaults.

Keep credentials out of tracked files. The checked-in database values are for local
development. Model-cache paths must be absolute in containers. Warm the pinned snapshots
before enabling `HF_HUB_OFFLINE=1`; see [embedding operation](pipeline.md#embeddings-m3).
