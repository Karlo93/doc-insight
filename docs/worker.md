# Worker service

`di worker run` consumes `di:documents` through the `worker` group. It extends the
existing CLI so indexing and the service use the same settings, providers and
extract → analyze → embed → store implementation. No second executable is needed.
Apply the ingest migration before starting. The worker adds no migration.

## Loop and document states

The process creates its group with `MKSTREAM` and `0-0`, accepting `BUSYGROUP` on
restart. This includes events published before the first worker starts. It calls
`XREADGROUP GROUP worker <hostname>-<pid> COUNT n BLOCK ms STREAMS di:documents >`.
Each fetched entry is processed sequentially. PDFium and pytesseract never run
concurrently within the process. Provider instances and clients live for the process.

Pydantic validates required event fields, supported media types, tenant syntax,
digest, timezone-aware occurrence time and the exact `{tenant_id}/{sha256}` key.
The tenant-scoped repository must contain the referenced document with matching
digest, object key, media type and size. An invalid reference cannot change another
document's status or read an object. Malformed events go directly to the DLQ.

An eligible row moves from `uploaded` (or a previous `failed`/`processing` state)
to `processing`. The original streams into a temporary file, with digest and size
checked before extraction. Media type is verified from bytes. Temporary files and
object response bodies close on success or failure. Heavy processing runs outside
database transactions. The existing upsert replaces chunks, vectors and entities
with metadata and `processed` status in one transaction, preserving the document ID.
The worker confirms `processed`, then acknowledges the message with `XACK`.

Completed rows with the same digest and current `PIPELINE_VERSION` are acknowledged
without reading the object or invoking a provider. A different version reprocesses
and replaces the derived output. Pipeline version remains 6.

## Reclaim and dead letters

On startup and every reclaim interval, `XAUTOCLAIM` takes pending entries whose
idle time exceeds the configured minimum. Scan cursors continue on subsequent
iterations, including when a scan returns no entries. New entries are still read
when a reclaim page is empty. `XPENDING` supplies each entry's delivery count.

The maximum attempts setting allows that many deliveries to execute the pipeline.
The next reclaimed delivery is marked `failed` and dead-lettered with
`DeliveryLimit: retry budget exhausted`. Already committed current-version results
are acknowledged even when the delivery budget has been exhausted.

An ordinary pipeline exception marks the document `failed`, storing the exception
class and fixed summary `processing failed`. Raw exception messages are never
stored or logged. The worker appends the original event fields plus `error` and
`attempts` to `di:documents:dlq`, then acknowledges. Malformed/reference failures
use fixed validation summaries and leave the document untouched. A missing object
is a permanent failure. Storage I/O/service errors and database operational,
interface or pool timeout errors leave the entry pending. Redis outages cause a
bounded, interruptible retry. Failed status/DLQ writes cannot acknowledge an event.

"Effectively once" describes the stored result: one complete output for each
tenant/digest, with atomic replacement. It does not promise exactly one execution.
A crash during processing leaves `processing` and a pending entry. Reclaim reruns
the work. A crash after the transaction commits but before acknowledgement skips
the completed output on replay. The DLQ append and acknowledgement are separate:
a crash between them may duplicate a dead letter. Deduplicate by `event_id`.

Redis uses idle time as a lease; it does not detect process death. Set the claim
minimum above the longest expected processing time plus the time a prefetched
batch waits. Otherwise another worker can reclaim active work. A batch of one is
the default. Concurrent replacements remain atomic, but may repeat computation.
Do not trim stream entries while they are pending. Keep Redis persistence enabled.

## Shutdown and telemetry

The first SIGTERM or SIGINT finishes the in-flight message and exits successfully.
Remaining entries in a fetched batch stay pending for reclaim. A second signal
exits immediately. Signal handlers are restored and clients close on normal exit.

Each loop and message boundary refreshes `di:worker:{hostname}-{pid}` with a 30 s
TTL ([ADR-0009](adr/0009-worker-heartbeat-identity.md)). The key contains `ready`.
Blocking reads are capped at 10 s. This heartbeat
reports recent progress; a stage taking longer than 30 s can expire it until the
next boundary. Do not use it alone to kill a process performing a long OCR job.

The worker attaches the event's `traceparent`, creates a `process` span and four
stage spans, then restores the previous context. Existing telemetry settings apply.
The CLI keeps its stage-duration output. The service logs IDs, statuses, counts
and error classes; it never logs document text, filenames, vectors or event bodies.

## Settings

One cached worker settings object reads the `DI_` environment at startup. Export
variables before launching; `.env` is used by Compose and is not loaded by the CLI.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DI_REDIS_URL` | `redis://127.0.0.1:6379/0` | Stream and heartbeat connection |
| `DI_WORKER_GROUP` | `worker` | Nonempty consumer group, without whitespace |
| `DI_WORKER_BLOCK_MS` | `1000` | Blocking read timeout, 1–10000 ms |
| `DI_WORKER_BATCH` | `1` | Entries fetched per read/reclaim, 1–100 |
| `DI_WORKER_RECLAIM_SECONDS` | `30` | Positive interval between full pending scans |
| `DI_WORKER_CLAIM_MIN_IDLE_MS` | `300000` | Positive idle lease before reclaim |
| `DI_WORKER_MAX_ATTEMPTS` | `5` | Positive number of permitted processing deliveries |
| `DI_DATABASE_URL` | `postgresql+psycopg://di_app:di_app@localhost:5432/di` | Restricted runtime DB login |
| `DI_MIGRATION_DATABASE_URL` | `postgresql+psycopg://di:di@localhost:5432/di` | Migration/test administrator login |
| `DI_S3_ENDPOINT` | `http://127.0.0.1:9000` | Object store endpoint |
| `DI_S3_REGION` | `us-east-1` | S3 signing region |
| `DI_S3_BUCKET` | `documents` | Original document bucket |
| `DI_S3_ACCESS_KEY` | empty | S3 credential; supply through environment |
| `DI_S3_SECRET_KEY` | empty | S3 credential; supply through environment |
| `DI_S3_USE_SSL` | `false` | TLS when the endpoint does not specify a scheme |

Extraction/model settings are listed in [pipeline.md](pipeline.md). New worker
variables are also in `.env.example`. In production, use a bucket that requires
SSE-S3 encryption; the local MinIO initializer configures it.

## Try it locally

The following Bash commands use isolated nondefault ports. Install `uv`, Docker,
`redis-cli`, MinIO `mc`, and Tesseract with English and Croatian data first.
Run them from a clean checkout containing the ingest migration. The model-backed
worker may download its pinned tokenizer and embedding snapshot on first use.

```bash
uv sync --locked --all-packages
export COMPOSE_PROJECT_NAME=di-lane2
export POSTGRES_PORT=55433 REDIS_PORT=56380 MINIO_PORT=59002 MINIO_CONSOLE_PORT=59003
export DI_DATABASE_URL=postgresql+psycopg://di_app:di_app@127.0.0.1:55433/di
export DI_MIGRATION_DATABASE_URL=postgresql+psycopg://di:di@127.0.0.1:55433/di
export DI_REDIS_URL=redis://127.0.0.1:56380/0
export DI_S3_ENDPOINT=http://127.0.0.1:59002 DI_S3_REGION=us-east-1 DI_S3_BUCKET=documents
export DI_S3_ACCESS_KEY=minioadmin DI_S3_SECRET_KEY=minioadmin DI_S3_USE_SSL=false
docker compose up -d --wait db redis minio
docker compose run --rm minio-init
uv run --locked --all-packages alembic upgrade head
mc alias set worker-local "$DI_S3_ENDPOINT" "$DI_S3_ACCESS_KEY" "$DI_S3_SECRET_KEY"
export SHA=$(sha256sum tests/fixtures/text_hr.pdf | cut -d ' ' -f 1)
export SIZE=$(wc -c < tests/fixtures/text_hr.pdf | tr -d ' ')
mc cp --enc-s3 worker-local/documents tests/fixtures/text_hr.pdf "worker-local/documents/demo/$SHA"
export DOCUMENT_ID=$(uv run --locked --all-packages python - <<'PY'
import os
from sqlalchemy import create_engine
from doc_insight.worker.repository import PostgresRepository
engine = create_engine(os.environ['DI_DATABASE_URL'], hide_parameters=True)
try:
    row = PostgresRepository(engine).register_upload(
        'demo', 'text_hr.pdf', os.environ['SHA'], 'application/pdf',
        int(os.environ['SIZE']), 'demo/' + os.environ['SHA'])
    print(row.id)
finally:
    engine.dispose()
PY
)
export EVENT_ID=$(uv run --locked python -c 'from uuid import uuid4; print(uuid4())')
redis-cli -p 56380 XADD di:documents '*' event_id "$EVENT_ID" type document.uploaded \
  tenant_id demo document_id "$DOCUMENT_ID" sha256 "$SHA" object_key "demo/$SHA" \
  media_type application/pdf size_bytes "$SIZE" occurred_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
uv run --locked --all-packages di worker run
```

The registration creates an outbox entry as well; this example publishes by hand
and does not run the relay. Later relaying that entry is a harmless duplicate.
In another terminal, with the same environment, inspect the result:

```bash
uv run --locked --all-packages di show "$DOCUMENT_ID" --tenant demo
redis-cli -p 56380 XPENDING di:documents worker
redis-cli -p 56380 XPENDING di:documents worker - + 20
redis-cli -p 56380 XRANGE di:documents:dlq - + COUNT 20
redis-cli -p 56380 --scan --pattern 'di:worker:*'
```

Replay the XADD command to exercise the completed-result shortcut. A deliberately
malformed event exercises the DLQ: `redis-cli -p 56380 XADD di:documents '*' type invalid`.
For deterministic recovery, the integration test kills a child process at the
analyze/embed boundary and starts a new consumer against the same durable state:

```bash
uv run --locked --all-packages pytest tests/storage/test_worker_integration.py -m integration --no-cov
uv run --locked --all-packages pytest tests/storage/test_worker_streams.py -m integration --no-cov
```
