#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1
compose=(docker compose --profile infra --profile telemetry --profile app)
docker compose --profile '*' build gateway ingest query worker
"${compose[@]}" up -d
bash scripts/wait_local.sh
"${compose[@]}" ps -a
binding=$("${compose[@]}" port caddy 443)
port=${binding##*:}
url="https://localhost:${port}"
curl -fkSs "$url/healthz"
# Readiness needs Redis and both upstream /readyz answers; fresh services take a few seconds.
for _ in $(seq 1 30); do
    curl -fkSs -o /dev/null "$url/readyz" && break
    sleep 2
done
curl -fkSs "$url/readyz"
printf '\nPublic URL: %s\n' "$url"
printf 'Health:   curl -fkSs %s/healthz\n' "$url"
printf 'Token:    TOKEN=$(make -s dev-token)   # tenant demo, user alice\n'
printf 'Upload:   curl -fkSs -H "Authorization: Bearer $TOKEN" -F file=@tests/fixtures/text_hr.pdf %s/ingest\n' "$url"
printf 'Status:   curl -fkSs -H "Authorization: Bearer $TOKEN" %s/documents/<document_id>\n' "$url"
printf 'Question: see docs/deploy.md for the query call once the status is processed\n'
