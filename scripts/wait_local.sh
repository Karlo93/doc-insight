#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose --profile infra --profile telemetry --profile app)
deadline=$((SECONDS + 180))
mapfile -t services < <("${compose[@]}" config --services)
for service in "${services[@]}"; do
    id=$("${compose[@]}" ps -aq "$service")
    [[ -n "$id" ]] || { echo "$service is missing" >&2; exit 1; }
    while :; do
        state=$(docker inspect --format '{{.State.Status}}/{{.State.ExitCode}}/{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$id")
        case "$service:$state" in
            migrate:exited/0/|minio-init:exited/0/|telemetry-tools:exited/0/) break ;;
            migrate:*|minio-init:*|telemetry-tools:*) ;;
            *:running/0/healthy) break ;;
        esac
        if [[ "$state" == exited/* || "$state" == dead/* || "$state" == */unhealthy || $SECONDS -ge $deadline ]]; then
            echo "$service failed startup: $state" >&2
            "${compose[@]}" logs --tail 30 "$service"
            exit 1
        fi
        sleep 1
    done
    echo "$service: $state"
done
