# Deployment

## Local Compose

Install Docker with Compose v2.24+ and Buildx, GNU Make, Bash and curl. Docker
Desktop must use Linux containers. Python, uv and Tesseract on the host are not
required for `local-run`; Docker installs the locked runtime and OCR tools.

```sh
git clone https://github.com/Karlo93/doc-insight.git
cd doc-insight
# Optional: copy .env.example to .env and choose free host ports.
make local-run
make local-stop
```

`local-run` builds all four application images, starts `infra`, `telemetry` and
`app`, and waits up to 180 seconds for health. The `migrate` service runs
`alembic upgrade head` once per startup, using privileged migration credentials.
It exits successfully before dependent applications start. Repeated upgrades are
idempotent. Build failures, failed migrations and unhealthy services fail the
command. `local-stop` retains data volumes, including MinIO keys and the Caddy CA.

**Current availability:** gateway, ingest, relay, query and the worker consumer
are not merged. They and Caddy use `pending`, which `local-run` does not enable.
Their images build from the current packages; the worker's existing processing
CLI and the migration run today. The command reports that the public API is
pending, rather than reporting a successful HTTPS application check.

When each runtime lands, give that service `profiles: [app]`, verify its settings
and health check, and remove its pending note. Activate Caddy with the gateway
after ingest and query are active. Generate the development JWKS with the gateway
key script and set `DI_DEV_JWKS_FILE` to its JSON file before starting gateway.
The bind mount is read-only and refuses a missing file. Private keys stay outside
images and are never mounted into gateway. The HTTP services must bind to
`0.0.0.0` on their contracted internal ports (8000, 8001, 8002).

## Images and runtime checks

| Image | Default command | Health |
| --- | --- | --- |
| `ghcr.io/karlo93/doc-insight-gateway` | `di-gateway serve` | HTTP `/healthz` on 8000 |
| `ghcr.io/karlo93/doc-insight-ingest` | `di-ingest serve` | HTTP `/healthz` on 8001 |
| same ingest image, relay service | `di-ingest relay` | Process liveness only; no relay heartbeat contract |
| `ghcr.io/karlo93/doc-insight-query` | `di-query serve` | HTTP `/healthz` on 8002 |
| `ghcr.io/karlo93/doc-insight-worker` | `di worker run` | Redis `di:worker:{hostname}` has a positive TTL |
| same worker image, migrate service | `alembic upgrade head` | Successful exit |

Build individually with `docker build --build-arg APP=worker -t doc-insight-worker .`.
Local Compose uses `:local`. Main pushes publish `:<full-commit-sha>` and `:main`
for Linux amd64, with Buildx caches per application and attached SBOM/provenance.
Use immutable commit tags for deployment. Relay and migration reuse published
images; Caddy uses the pinned upstream image. See [CI](ci.md).

The single multi-stage Dockerfile installs from `uv.lock` with `--locked --no-dev`
and `--no-editable`. Runtime contains no uv or build cache. Worker includes
Tesseract English/Croatian data and a model cache at
`/home/di/.cache/doc-insight/models`. `HF_HUB_OFFLINE=1` is set before startup.
Query gains a warmed cache when its worker dependency is merged. Do not mount an
empty volume over the image cache. Updating model revisions requires a rebuild.
Applications run as UID/GID 10001, with dropped capabilities and a read-only root;
`/tmp` is a 256 MiB tmpfs for OCR/upload scratch data. Caddy needs writable
`/data` and `/config`; storage/telemetry retain their upstream runtime users.

## Environment

Compose reads `.env` automatically; it is optional. Only the explicitly mapped
variables below enter application containers, keeping migration credentials out
of their environment. Container URLs are separate from host CLI URLs.
Do not put production credentials in image build arguments. Existing pipeline
settings are in [pipeline](pipeline.md); infrastructure ports and credentials are
in [local stack](local-stack.md). Internal application ports are not published.

| Variable | Default | Purpose |
| --- | --- | --- |
| `IMAGE_TAG` | `local` | Compose image tag; `local-run` builds this tag |
| `DI_CONTAINER_DATABASE_URL` | `postgresql+psycopg://di_app:di_app@db:5432/di` | Mapped to application `DI_DATABASE_URL`; restricted runtime role |
| `DI_CONTAINER_MIGRATION_DATABASE_URL` | `postgresql+psycopg://di:di@db:5432/di` | Mapped to migration `DI_MIGRATION_DATABASE_URL` only |
| `DI_REDIS_URL` | `redis://redis:6379/0` in containers | Internal Redis; overrides the host CLI value |
| `DI_S3_ENDPOINT` | `http://minio:9000` in containers | Internal MinIO; overrides the host CLI value |
| `DI_S3_USE_SSL` | `false` in containers | Local internal network uses HTTP; MinIO encrypts stored objects |
| `DI_S3_REGION`, `DI_S3_BUCKET` | `us-east-1`, `documents` | Object storage location |
| `DI_S3_ACCESS_KEY`, `DI_S3_SECRET_KEY` | `minioadmin`, `minioadmin` | Public development defaults; replace outside local development |
| `DI_OTEL_ENDPOINT` | `http://otel-collector:4318` in containers | OTLP/HTTP collector |
| `DI_ENV` | `development` | Telemetry environment |
| `DI_MODEL_CACHE`, `HF_HUB_OFFLINE` | `/home/di/.cache/doc-insight/models`, `1` | Image model cache and offline Hub loading |
| `DI_INGEST_URL`, `DI_QUERY_URL` | `http://ingest:8001`, `http://query:8002` | Gateway upstreams |
| `DI_JWKS_URL` | `http://127.0.0.1:8000/.well-known/jwks.json` | Gateway's development public key endpoint |
| `DI_DEV_JWKS_FILE` | `./.cache/dev/jwks.json` | Host public JWKS JSON to mount |
| `DI_DEV_JWKS_PATH` | `/run/dev/jwks.json` | Container public JWKS path |
| `DI_JWT_ISSUER`, `DI_JWT_AUDIENCE` | `doc-insight-dev`, `doc-insight` | Must match development token claims |
| `CADDY_HTTP_PORT`, `CADDY_HTTPS_PORT` | `80`, `443` | Loopback-only public ports |
| `DI_CONTAINER_APP`, `DI_CONTAINER_ROLE` | Build-selected app; `relay` on relay only | Image entrypoint/probe dispatch; do not override |

Changing `POSTGRES_USER`, `POSTGRES_PASSWORD` or `POSTGRES_DB` also requires
matching container database URLs. Initialization of roles/credentials happens
only on a fresh Postgres volume. Runtime and migration accounts stay separate.
Use URL-encoded passwords in database URLs. The development stack is not a
production secret-management configuration.

## TLS and public calls

Caddy's [internal CA](https://caddyserver.com/docs/automatic-https#local-https)
issues a localhost certificate. `-k` skips local certificate verification; use it
only for this development stack. Once Caddy is active, `local-run` checks and
prints the public health URL and its curl command. To trust the local CA instead,
export `/data/caddy/pki/authorities/local/root.crt` from the Caddy container and
install it in your local trust store. Retain the CA volume across restarts.

For production, replace `localhost` with a real domain, remove `tls internal`,
and configure public DNS/reachability for Caddy's ACME certificates, or terminate
TLS at managed ingress. Use HTTPS for external storage and a real identity
provider; remove the development JWKS mount/endpoint. Kubernetes manifests and
ingress are wave B; see [ADR-0008](adr/0008-compose-service-images.md).

After the service activation described above, mint a token using the gateway's
`scripts/mint_token.py --tenant demo --user alice --ttl 3600` and export it as
`TOKEN`. These are the three public API calls (pending until those services merge):

```sh
curl -fkSs https://localhost/healthz
curl -fkSs -H "Authorization: Bearer $TOKEN" \
  -F file=@tests/fixtures/text_hr.pdf https://localhost/ingest
# Copy document_id from the upload response; repeat until status is processed.
curl -fkSs -H "Authorization: Bearer $TOKEN" \
  https://localhost/documents/REPLACE_WITH_DOCUMENT_ID
curl -fkSs -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"question":"Gdje se nalazi Zagreb?","top_k":5}' https://localhost/query
```

Use your configured HTTPS port if it differs from 443. Do not run these examples
against the stub images or interpret a pending stack as an end-to-end success.
