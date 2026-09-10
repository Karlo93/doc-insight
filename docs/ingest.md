# Uploads and outbox delivery

`di-ingest serve` exposes the internal ingest API on port 8001. The gateway supplies
`X-Tenant-Id`; direct local requests must supply it too. Tenants are 1–64 characters
from `[A-Za-z0-9._-]`. Missing or invalid tenants receive 400. This trusted header is
not authentication; keep this service on the internal network.

```text
client -> ingest -> temporary file (bounded, SHA-256, magic bytes)
                -> S3 object (SSE-S3)
                -> Postgres transaction: document + outbox
                <- 202 {document_id, sha256, status}
outbox -> tenant-scoped relay -> XADD di:documents -> mark published -> commit
```

`POST /ingest` accepts one multipart field named `file`. The receiver hashes bytes
while writing a temporary file, without holding the full upload in memory. It limits
file data to `DI_MAX_UPLOAD_BYTES` and multipart overhead to 16 KiB. Unsupported magic
bytes receive 415; an excessive upload receives 413. Temporary files close on success,
rejection, disconnect and failure. No object or database write precedes validation.

For an existing `(tenant_id, sha256)`, the endpoint returns its ID with
`status: duplicate` and does not write storage or enqueue another event. Otherwise it
writes `{tenant_id}/{sha256}` before registering the document and event atomically.
The unique constraint serializes concurrent registrations: only one row and one event
survive. Concurrent requests that both passed the lookup may overwrite the same object
with identical bytes; the resulting document ID remains the same.

`GET /documents/{id}` returns `document_id`, `status`, `filename`, `page_count`,
`language`, `pipeline_version`, `created_at`, `processed_at`, and `error`. A different
tenant or missing document receives 404. Uploads have null derived metadata until
processing completes. Worker upserts preserve the original object key, size, ID and
creation time while replacing derived output and clearing a previous error.
`mark_status` accepts the four statuses and stores an error only for `failed`.
Its caller must supply a safe error class and short generic summary, never document
content or an unfiltered exception message. The stored pipeline version stays at 6.

`GET /healthz` checks only the process. `GET /readyz` checks Postgres, the S3 bucket and
Redis, returning 503 on failure. Errors use `{"error":{"code":"...","message":"..."}}`.
The CLI disables HTTP access logs and exception tracebacks. Shared telemetry records
route templates, static stage names, IDs/statuses and timing, without document text,
filenames, vectors or credentials. Active trace context is copied into the outbox event.

## Delivery and failure recovery

Run `di-ingest relay --tenant demo` for each tenant to publish. Each pass binds the same
transaction-local RLS setting as the repository, orders pending events by creation time
and ID, and locks up to `DI_RELAY_BATCH` rows with `FOR UPDATE SKIP LOCKED`. Two relays
for the same tenant can progress without publishing the same locked row. Neither uses
the migration role or bypasses RLS. Each event is a string-valued message in
`di:documents`, including its stable `event_id`. Consumer group `worker` belongs to the
consumer service; ingestion does not create or consume that group.

| Failure | Result and recovery |
| --- | --- |
| Storage rejects or times out | No document/outbox transaction; return 503; retry the upload |
| DB fails after storage | No partial document/outbox commit; an orphan object can remain |
| Concurrent registration | One document and event; repeated object writes contain identical bytes |
| Redis write fails | Roll back published flags; restart the relay to retry pending events |
| Redis accepted a write but acknowledgement or DB commit fails | The same event may be delivered again; consumers must deduplicate by event ID and process idempotently |
| SIGTERM/SIGINT | Finish the current bounded batch, interrupt the poll wait, close clients and exit |

Orphan recovery uses idempotent overwrite on a later upload of the same tenant/hash.
Unretried orphan bytes remain stored; a future janitor can remove old keys without a
matching document after a grace period. This PR does not implement a janitor. It must
not delete keys while an upload transaction may still be in flight. Redis persistence
and backups remain an infrastructure concern; an acknowledged message lost from Redis
after the DB commit cannot be reconstructed by the normal pending-event scan.

Migration `0003_ingest_outbox` adds FORCE RLS to the outbox and a composite tenant FK.
The runtime role needs SELECT/INSERT/UPDATE/DELETE on it; the existing development
default privileges grant these automatically. Production must apply equivalent grants.
Existing development volumes created before those default privileges were installed
need `GRANT SELECT, INSERT, UPDATE, DELETE ON outbox TO di_app;` after migration,
executed through the migration connection. Readiness connectivity alone does not prove
that every table privilege was provisioned.
Run migrations with `DI_MIGRATION_DATABASE_URL`, never runtime credentials.
Downgrade restores the old NOT NULL constraints. It deliberately fails atomically while
unprocessed rows exist, rather than inventing metadata or deleting uploads. Process or
explicitly archive those rows and drain the outbox before downgrading.

## Settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `DI_DATABASE_URL` | `DI_DATABASE_URL` from generated `.env` | Restricted runtime connection |
| `DI_S3_ENDPOINT` | `http://localhost:9000` | S3-compatible API endpoint |
| `DI_S3_REGION` | `us-east-1` | Signing region |
| `DI_S3_BUCKET` | `documents` | Existing bucket; provision with SSE-S3 support |
| `DI_S3_ACCESS_KEY` | required | S3 access credential |
| `DI_S3_SECRET_KEY` | required | S3 secret credential |
| `DI_S3_USE_SSL` | `false` | SDK SSL option; use an HTTPS endpoint for TLS |
| `DI_REDIS_URL` | `redis://localhost:6379/0` | Stream connection |
| `DI_MAX_UPLOAD_BYTES` | `52428800` (50 MiB) | Positive file byte limit |
| `DI_RELAY_POLL_SECONDS` | `1` | Positive pause between relay passes |
| `DI_RELAY_BATCH` | `100` | Maximum events locked per pass, 1–10000 |
| `DI_HTTP_HOST` | `127.0.0.1` | Bind address for `di-ingest serve`; containers set `0.0.0.0` |
| `DI_HTTP_PORT` | `8001` | Listen port for `di-ingest serve` |

Settings and clients are created once per process. S3 operations use bounded network
timeouts and retries; Redis uses five-second connection and operation timeouts.

## Run locally

First run `python scripts/configure_local.py`. The examples use default host ports.
For alternate ports, update the host URLs and CLI arguments to match; preserve passwords.
Commands load `.env` explicitly.

Start Postgres, Redis and MinIO using the generated `.env`. The initializer
requires SSE-S3 bucket encryption before uploads. These examples use default
host ports; see [configuration](configuration.md) for alternate ports.

```sh
docker compose --profile infra up -d --wait db redis minio
docker compose --profile infra run --rm minio-init
uv sync --locked --all-packages
uv run --env-file .env --locked --all-packages alembic upgrade head
uv run --env-file .env --locked --all-packages di-ingest serve
```

From another shell with the same environment:

```sh
curl -F file=@tests/fixtures/text_hr.pdf -H 'X-Tenant-Id: demo' http://127.0.0.1:8001/ingest
uv run --env-file .env --locked --all-packages di-ingest relay --tenant demo
```

Inspect from a third shell; repeat the upload to see `duplicate`:

```sh
redis-cli -p 6379 XRANGE di:documents - +
curl -H 'X-Tenant-Id: demo' http://127.0.0.1:8001/documents/DOCUMENT_ID
uv run --env-file .env --locked --all-packages pytest -m integration --no-cov
```

On Windows use `curl.exe` to avoid a shell alias. The integration suite creates its
own disposable databases, random object keys and Redis consumer groups. It removes
its own objects/messages/groups without flushing shared storage or streams.
