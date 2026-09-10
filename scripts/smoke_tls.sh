#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1
name="di-tls-check-$$"
cleanup() {
    docker rm -f "$name-proxy" "$name-upstream" >/dev/null 2>&1 || true
    docker network rm "$name" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker network create "$name" >/dev/null
docker run -d --name "$name-upstream" --network "$name" --network-alias gateway \
    --read-only --cap-drop ALL --security-opt no-new-privileges \
    --mount "type=bind,source=$(pwd)/tests/platform/health_server.py,target=/health_server.py,readonly" \
    "ghcr.io/karlo93/doc-insight-gateway:${IMAGE_TAG:-local}" python /health_server.py >/dev/null
docker run -d --name "$name-proxy" --network "$name" --read-only \
    --tmpfs /data --tmpfs /config -p 127.0.0.1::443 \
    --mount "type=bind,source=$(pwd)/deploy/Caddyfile,target=/etc/caddy/Caddyfile,readonly" \
    caddy:2.10.2-alpine >/dev/null
binding=$(docker port "$name-proxy" 443)
port=${binding##*:}
body=$(curl -fkSs --retry 15 --retry-delay 1 --retry-all-errors \
    --connect-timeout 2 --max-time 5 "https://localhost:$port/healthz")
[[ "$body" == upstream-health-fixture ]]
status=$(curl -kSs -o /dev/null -w '%{http_code}' "https://localhost:$port/missing")
[[ "$status" == 404 ]]
echo 'Caddy internal TLS forwarded fixture health and upstream 404 correctly.'
