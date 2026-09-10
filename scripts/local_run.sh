#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1
compose=(docker compose --profile infra --profile telemetry --profile app)
# Build pending images too: missing service entrypoints must not hide packaging failures.
docker compose --profile '*' build gateway ingest query worker
"${compose[@]}" up -d
bash scripts/wait_local.sh
"${compose[@]}" ps -a
if "${compose[@]}" config --services | grep -qx caddy; then
    binding=$(docker compose port caddy 443)
    port=${binding##*:}
    url="https://localhost:${port}"
    curl -fkSs "$url/healthz"
    printf '\nPublic URL: %s\ncurl -fkSs %s/healthz\n' "$url" "$url"
else
    printf '\nInfrastructure and migrations ready. Public API is pending service merges.\n'
    printf 'After activation: https://localhost; curl -fkSs https://localhost/healthz\n'
fi
