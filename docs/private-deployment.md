# Private deployment

Run the application on a private network using the base Compose file plus
`deploy/compose.private.yml` on Linux. The override removes database, Redis, MinIO,
collector, Tempo and Prometheus host ports. Caddy and Grafana bind loopback only.
Query and worker have CPU/memory caps to protect other applications on the host.

## Configure and start

Requirements: Docker Compose 2.24.4+, an encrypted host volume, a Docker-capable SSH
account, and Tailscale Serve permission. Use a unique, stable Compose project name.
Keep the deployment directory, `.env`, signing keys and provider key private.

Copy `.env.example` to `.env` and configure before creating volumes:

| Variable | Deployment setting |
| --- | --- |
| `COMPOSE_PROJECT_NAME` | Unique, stable project name |
| `IMAGE_TAG` | Immutable release identifier |
| `QUERY_IMAGE_TAG` | Optional query-only release override; empty inherits `IMAGE_TAG` |
| `POSTGRES_PASSWORD` | Generated administrator password |
| `DI_DB_RUNTIME_PASSWORD` | Different generated runtime password |
| `DI_CONTAINER_DATABASE_URL` | `postgresql+psycopg://di_app:PASSWORD@db:5432/di` |
| `DI_CONTAINER_MIGRATION_DATABASE_URL` | `postgresql+psycopg://di:PASSWORD@db:5432/di` |
| `DI_S3_ACCESS_KEY`, `DI_S3_SECRET_KEY` | Generated object-store credentials |
| `GRAFANA_ADMIN_PASSWORD` | Generated dashboard password |
| `CADDY_HTTP_PORT`, `GRAFANA_PORT` | Free loopback ports, e.g. 9080 and 9300 |
| `DI_TENANTS` | Comma-separated provisioned tenants, matching issued tokens |
| `OPENAI_SECRET_FILE` | Absolute path to a private UTF-8 file containing only the API key |

Generate independent passwords using `python -c 'import secrets; print(secrets.token_hex(24))'`.
The runtime-role initialization script runs only on a **new database volume**;
changing `.env` does not rotate an existing database password.
On Linux, the mounted provider file must be readable by container UID 10001.
An owner-only mode-0700 directory containing a mode-0644 key file lets Docker mount
it while preventing other host users from traversing the directory. Never put the
key in source, an image, command arguments, screenshots or browser forms.

```sh
docker compose --profile '*' build gateway ingest query worker
docker compose -f docker-compose.yml -f deploy/compose.secret.yml \
  -f deploy/compose.private.yml --profile '*' up -d --no-build --wait --wait-timeout 240
```

Startup migrates the schema, initializes encrypted object storage and signing keys,
and waits for query model readiness before starting the gateway. Cold startup can
take minutes on a constrained development machine. `healthz` means process liveness;
query's container checks `readyz` to protect the first question from cold loading.

## API credentials and token usage

OCR, language detection, named entities and CPU embeddings run locally. Only answer
generation needs an OpenAI platform API key; a chat subscription is not an API
credential. Use `DI_OPENAI_API_KEY`, or a mounted key via `deploy/compose.secret.yml`
and `OPENAI_SECRET_FILE`. The pinned model is `gpt-4.1-mini-2025-04-14`.

```sh
docker compose -f docker-compose.yml -f deploy/compose.secret.yml \
  --profile '*' up -d --no-deps --wait query
```

Add `-f deploy/compose.private.yml` on the private server. Recreate query after
changing configuration; a restart retains its existing environment. Without a key,
the app uses extractive answers. `generation.provider` reports the path actually
used. `generation.usage` includes input, output and cached input tokens;
`fallback_reason` identifies disabled generation, saturation, circuit, budget,
upstream and format failures.

`GET /usage` and the browser display the current tenant's UTC-day accounting.
Default limits are 250,000 daily tokens, 700 output tokens per call and four
concurrent hosted calls. PostgreSQL reservations protect the allowance across
concurrency and restarts. Unknown usage is charged conservatively. This is a token
allowance, not a provider invoice or exact dollar limit. Cached input is already
included in input tokens. See [query settings](query.md#settings).

Questions and retrieved text are sent to OpenAI with `store: false`. This option
is not a promise of zero provider retention; consult
[OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data).
`HF_HUB_OFFLINE=1` only disables model downloads. Use an empty key/load profile to
also disable hosted answer calls.

## Private HTTPS and browser access

Add a **new, unused** Serve port; preserve existing routes:

```sh
tailscale serve --bg --https=8445 http://127.0.0.1:9080
tailscale serve status
```

Use the returned HTTPS URL from a connected tailnet device. Do not enable Funnel
or publish router ports. On the local network, Tailscale can use a direct LAN
connection. Plain LAN HTTP is deliberately not exposed. For administrative Grafana
access use `ssh -N -L 127.0.0.1:9300:127.0.0.1:9300 YOUR_SERVER`.

Mint a workspace token and paste it into the browser:

```sh
docker compose --profile '*' run --rm --no-deps -T dev-issuer \
  python /usr/local/lib/dev_issuer.py mint --tenant demo --user operator --ttl 3600
```

Only the issuer job mounts the private signing key; the gateway receives public
JWKS. Tokens stay in browser memory and disappear on refresh/disconnect. Expiry
requires a fresh token. This private operator deployment has no self-registration,
password recovery or external identity provider. Never paste the OpenAI key.

## Validation, upgrades and recovery

Run `scripts/acceptance.py` with an ignored JSON file containing tokens for two
different provisioned tenants. It covers PDF/image processing, a 10 MiB upload,
OpenAI EN/HR answers, abstention, citations, usage and cross-tenant denial.

For load tests, recreate query with `deploy/compose.load.yml` **last** and omit the
secret overlay. The benchmark refuses to proceed if preflight sees hosted output.
Restore the secret overlay and check a real answer afterwards. Read the measured
report before inferring capacity from the 100-RPS target.

Back up PostgreSQL, Redis, MinIO data **and its encryption key**, and the issuer
key. Stop write-facing services during a consistent snapshot. Encrypt backups with
a separate key; restore to an isolated project and verify counts, derived chunks,
usage and readable originals. Keep prior image IDs/configuration for rollback.
Never run `down -v` on the deployed project. Downgrading revision 0004 deletes usage
history and its search index; a pre-upgrade snapshot preserves rollback data.

Compose gives the worker a 600-second heartbeat TTL and a 900-second reclaim delay.
This tolerates long model/OCR stages at the cost of delayed failure detection.
Processing has no hard wall-clock deadline; inspect jobs exceeding this window.

Caddy removes request objects from runtime logs while retaining error/status
metadata through its [filter encoder](https://caddyserver.com/docs/caddyfile/directives/log).
Application traces use route templates, IDs, counts and durations, never raw
questions, filenames, passages, tokens or authorization headers.

### Backup and isolated restore commands

Create a high-entropy passphrase file outside the backup directory and protect it
with mode 0600. Keep a separate recovery copy. The backup command pauses write-facing
services and restarts the stack even if snapshotting fails; inspect `restart.log`.
Run from the release directory with its private `.env`:

```sh
bash scripts/backup_private.sh /PRIVATE/BACKUPS /PRIVATE/backup-passphrase
bash scripts/verify_backup.sh /PRIVATE/BACKUPS/TIMESTAMP.tar.gpg \
  /PRIVATE/backup-passphrase ghcr.io/YOUR_ORG/doc-insight-query:RELEASE
```

Restore verification creates fresh containers, networks and volumes with a unique
prefix, checks SQL counts, hashes decrypted original bytes, checks Redis readiness
and verifies a JWT against the restored JWKS. It removes only its disposable
resources. It does not overwrite the live project. Copy the encrypted archive to a
second machine, verify its adjacent SHA-256, and keep its passphrase separately.
A complete replacement-host recovery also needs the OpenAI secret from the secret
store; that provider key is deliberately outside this snapshot.

For an application rollback, retain the prior image IDs under a separate immutable
tag, set `IMAGE_TAG` to that compatible release and run the same Compose overlays
with `up -d --no-build --wait`. Check readiness and a cited answer. Return to the new
tag with the same command. Never downgrade a database merely to roll back an image;
restore a pre-migration snapshot if the old code cannot read the current schema.

The Caddy upstream idle timeout is four seconds, shorter than Uvicorn's five-second
close window. This avoids reusing stale sockets for POST requests after an idle
period; the measured initial failure and correction are in the [load report](../benchmark/README.md).
