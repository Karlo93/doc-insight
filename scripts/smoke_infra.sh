#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

profile=${1:-infra}
case "$profile" in
    infra) services=(db redis minio); init=minio-init ;;
    telemetry) services=(otel-collector prometheus tempo grafana); init=telemetry-tools ;;
    *) echo 'Usage: bash scripts/smoke_infra.sh [infra|telemetry]' >&2; exit 2 ;;
esac

# Inspect the active project rather than assuming default host ports.
deadline=$((SECONDS + 120))
for service in "${services[@]}"; do
    id=$(docker compose --profile "$profile" ps -aq "$service")
    if [[ -z "$id" ]]; then
        echo "$service is missing; start the $profile profile first" >&2
        exit 1
    fi
    while :; do
        state=$(docker inspect --format '{{.State.Status}}/{{.State.Health.Status}}' "$id")
        [[ "$state" == running/healthy ]] && break
        if [[ "$state" == exited/* || "$state" == dead/* || $SECONDS -ge $deadline ]]; then
            echo "$service did not become healthy: $state" >&2
            docker compose --profile "$profile" logs --tail 30 "$service"
            exit 1
        fi
        sleep 1
    done
    docker inspect --format '{{.Config.Image}}: healthy' "$id"
done

id=$(docker compose --profile "$profile" ps -aq "$init")
[[ -n "$id" ]] || { echo "$init is missing" >&2; exit 1; }
while :; do
    state=$(docker inspect --format '{{.State.Status}}/{{.State.ExitCode}}' "$id")
    [[ "$state" == exited/0 ]] && break
    if [[ "$state" == exited/* || "$state" == dead/* || $SECONDS -ge $deadline ]]; then
        echo "$init did not complete successfully: $state" >&2
        docker logs "$id"
        exit 1
    fi
    sleep 1
done
if [[ "$profile" == infra ]]; then
    docker compose exec -T db postgres --version
    docker compose exec -T redis redis-server --version
    docker compose exec -T minio minio --version
    docker compose run --rm --no-deps minio-init
else
    docker compose exec -T otel-collector /otelcol-contrib --version
    docker compose exec -T prometheus /bin/prometheus --version
    docker compose exec -T tempo /tempo -version
    docker compose exec -T grafana grafana server -v
fi
