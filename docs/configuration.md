# Configuration index

The current worker uses one cached Pydantic-settings object with `env_prefix="DI_"`.
Values are validated at process startup. Export variables before invoking the CLI;
its settings class does not configure `.env` loading. Compose reads `.env` separately.

| Settings | Defaults and purpose |
| --- | --- |
| OCR: `DI_OCR_MIN_CHARS`, `DI_OCR_DPI`, `DI_OCR_LANGS`, `DI_TESSERACT_CMD` | [Extraction table](pipeline.md#pipeline-files-to-searchable-documents) |
| Language, NER, chunking, tokenizer and cache | [Structure table](pipeline.md#structure-m2) |
| Embedding batch and pinned ONNX snapshot | [Embedding table](pipeline.md#embeddings-m3) |
| `DI_DATABASE_URL` | `postgresql+psycopg://di:di@localhost:5432/di`; SQLAlchemy/psycopg URL for CLI, migrations and storage tests |
| `DI_ALLOW_REMOTE_TEST_DB` | Unset; the integration harness refuses nonlocal database hosts unless explicitly enabled |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Each defaults to `di`; Compose development database initialization |
| `POSTGRES_PORT` | `5432`; Compose host port, bound to `127.0.0.1`; export a matching `DI_DATABASE_URL` if changed |
| `COMPOSE_PROJECT_NAME` | Compose override for resource isolation; otherwise this file uses `doc-insight-core` |

The database variables appear in [`.env.example`](../.env.example); the other implemented
worker settings are documented in the linked pipeline tables and
[settings class](../apps/worker/src/doc_insight/worker/settings.py).
`DI_ALLOW_REMOTE_TEST_DB` belongs to the test harness, not the worker settings object.

The planned storage settings are `DI_S3_ENDPOINT`, `DI_S3_REGION`, `DI_S3_BUCKET`,
`DI_S3_ACCESS_KEY`, `DI_S3_SECRET_KEY`, `DI_S3_USE_SSL`, `DI_MAX_UPLOAD_BYTES` and
`DI_REDIS_URL` (lands with lane 1). Telemetry uses `DI_OTEL_ENDPOINT` (lands with lane 5).
These are contracts, not currently accepted worker options. Add default/purpose tables
and `.env.example` entries with each service implementation; do not infer unset defaults.

Keep credentials out of tracked files. The checked-in database values are for local
development. Model-cache paths must be absolute in containers. Warm the pinned snapshots
before enabling `HF_HUB_OFFLINE=1`; see [embedding operation](pipeline.md#embeddings-m3).
