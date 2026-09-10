#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1
prefix=ghcr.io/karlo93/doc-insight
tag=${IMAGE_TAG:-local}
for app in gateway ingest query worker; do
    image="$prefix-$app:$tag"
    docker image inspect --format '{{.RepoTags}} {{.Size}} bytes, user={{.Config.User}}' "$image"
    docker run --rm --network none --read-only --cap-drop ALL \
        --security-opt no-new-privileges --tmpfs /tmp:mode=1777,size=256m \
        "$image" python -c "import doc_insight.$app; import os; assert os.getuid() == 10001"
done
docker run --rm --network none --read-only --tmpfs /tmp:mode=1777,size=256m \
    "$prefix-worker:$tag" tesseract --list-langs
docker run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges --tmpfs /tmp:mode=1777,size=256m \
    --mount "type=bind,source=$(pwd)/tests/fixtures,target=/fixtures,readonly" \
    "$prefix-worker:$tag" di analyze /fixtures/text_hr.pdf --embed >/dev/null
docker run --rm --network none --read-only --tmpfs /tmp:mode=1777,size=256m \
    --mount "type=bind,source=$(pwd)/tests/fixtures,target=/fixtures,readonly" \
    "$prefix-worker:$tag" di extract /fixtures/mixed.pdf >/dev/null
docker compose --profile '*' run --rm --no-deps caddy \
    caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
echo 'Image imports, offline embedding, OCR and Caddy configuration passed.'
