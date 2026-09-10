# Local infrastructure

Docker Compose v2 and Bash run the infrastructure without building any application
image. Use Git Bash on native Windows, or WSL/Linux. Run `python scripts/configure_local.py`;
Compose reads it automatically. Export the matching `DI_` values separately before
running Python commands. See [pipeline setup](pipeline.md) for Python and OCR.

```sh
make infra-up
bash scripts/smoke_infra.sh
make telemetry-up
bash scripts/smoke_infra.sh telemetry
```

`infra` contains Postgres, Redis, MinIO and a bucket initialization job.
`telemetry` contains the collector, Prometheus, Tempo, Grafana and a probe setup job.
`docker compose --profile infra up -d` also works directly; run the smoke script
afterward to wait for health and successful bucket initialization. Its deadline
is 120 seconds; a missing service, failed initialization or timeout exits nonzero.
The script prints the pinned images and running binary versions.

`make infra-up` runs both commands. `make db-up` and `make db-down` are aliases
for `infra-up` and `infra-down`. `make telemetry-down` stops only telemetry;
`make infra-down` stops only infrastructure. Named volumes survive both commands.
No application image, migration or model download is part of these profiles.

## Ports and settings

Every published port binds to `127.0.0.1`. Internal container URLs use Compose
service names and the container ports, regardless of host overrides.

| Service / endpoint | Host variable | Default host / container port |
| --- | --- | --- |
| Postgres | `POSTGRES_PORT` | 5432 / 5432 |
| Redis | `REDIS_PORT` | 6379 / 6379 |
| MinIO S3 | `MINIO_PORT` | 9000 / 9000 |
| MinIO console | `MINIO_CONSOLE_PORT` | 9001 / 9001 |
| Collector OTLP/HTTP | `OTEL_HTTP_PORT` | 4318 / 4318 |
| Collector health | `OTEL_HEALTH_PORT` | 13133 / 13133 |
| Collector Prometheus exporter | `OTEL_PROMETHEUS_PORT` | 8889 / 8889 |
| Prometheus | `PROMETHEUS_PORT` | 9090 / 9090 |
| Tempo API | `TEMPO_PORT` | 3200 / 3200 |
| Grafana | `GRAFANA_PORT` | 3000 / 3000 |

For concurrent checkouts, change `COMPOSE_PROJECT_NAME` (default
`doc-insight-core`) and every occupied host port. Each project gets separate
networks and volumes. Change the corresponding Python endpoint URLs too.
If another database already owns 5432, choose a free `POSTGRES_PORT` before startup.

| Variable | Default | Purpose |
| --- | --- | --- |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `di` each | Local database initialization |
| `DI_DATABASE_URL` | `DI_DATABASE_URL` from generated `.env` | Host Python restricted runtime connection |
| `DI_MIGRATION_DATABASE_URL` | `DI_MIGRATION_DATABASE_URL` from generated `.env` | Migration and disposable integration database connection |
| `DI_REDIS_URL` | `redis://127.0.0.1:6379/0` | Host queue connection |
| `DI_S3_ENDPOINT` | `http://127.0.0.1:9000` | Host S3 endpoint |
| `DI_S3_REGION` | `us-east-1` | S3 signing region |
| `DI_S3_BUCKET` | `documents` | Bucket created by initialization |
| `DI_S3_ACCESS_KEY`, `DI_S3_SECRET_KEY` | Generated in `.env` | Required credentials; also initialize MinIO root access |
| `DI_S3_USE_SSL` | `false` | HTTP on the local development network |
| `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD` | `admin`; generated password in `.env` | Initial Grafana login |
| `DI_OTEL_ENDPOINT` | unset | Set to `http://127.0.0.1:4318` for host export |
| `DI_OTEL_SERVICE_NAME` | configure argument | Optional service identity override |
| `DI_OTEL_TIMEOUT_SECONDS` | `3` | Export timeout in seconds |
| `DI_ENV` | `development` | Telemetry environment attribute |

Inside containers use `redis://redis:6379/0`, `http://minio:9000`,
`http://otel-collector:4318` and database host `db`. Grafana provisioning uses
`http://prometheus:9090` and `http://tempo:3200` on the internal network.
The `DI_REDIS_URL` and S3 variables are connection conventions for service
adapters; the current CLI only consumes its database and telemetry settings.

## Storage and encryption

Redis uses append-only persistence. MinIO retains objects in `minio-data` and
a generated 256-bit development encryption key in `minio-keys`. The startup
script creates the key once with private file permissions. It supplies its
fixed container path through `MINIO_KMS_SECRET_KEY_FILE=/keys/sse-key`.
The pinned MinIO release supports SSE-S3 with this key. `minio-init` creates
the bucket idempotently, sets default SSE-S3 and fails if encryption cannot be
enabled. There is no silent downgrade to unencrypted storage.

Preserve both MinIO volumes together: deleting the key makes existing objects
unreadable. A key stored beside the server is a development convenience, not
production key isolation. Local endpoints use HTTP on loopback and the Docker
network; SSE protects objects at rest, not traffic. Production must use TLS,
separate credentials and provider-managed encryption/KMS. The console in this
MinIO release is limited; bucket administration uses `mc`.

## Telemetry

The collector accepts OTLP/HTTP traces and metrics. It exports traces to Tempo
and exposes metrics for Prometheus to scrape every five seconds. Prometheus
retains seven days; Tempo retains 24 hours in its local volume. Grafana retains
its settings and provisions the Prometheus and Tempo datasources plus the
**Doc Insight** dashboard (stage p95 by service/stage and request p95 by route/status).
Open [Grafana](http://localhost:3000/d/doc-insight) and log in with the configured
local credentials. Use Explore with the Tempo datasource to inspect traces.

The dashboard is empty until a configured application emits measurements.
Rate-based panels need at least two scrapes. A short-lived CLI may export only
one sample; run multiple document operations for a useful latency chart.
See [observability](observability.md) for the helper API and attribute policy.

Collector and Tempo images do not provide an HTTP probe command. A pinned
BusyBox one-shot copies a static binary into a volume mounted read-only in
both containers. Their health checks execute its `wget` against the actual
readiness endpoint. One-shot jobs are checked by successful exit, while all
long-running containers have periodic health checks.
