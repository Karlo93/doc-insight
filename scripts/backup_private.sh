#!/usr/bin/env bash
# Consistent encrypted snapshot. Requires Docker access and GnuPG on the host.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ $# != 2 ]]; then
  echo "Usage: bash scripts/backup_private.sh BACKUP_DIRECTORY PASSPHRASE_FILE" >&2
  exit 2
fi
umask 077
destination=$(realpath -m "$1")
passphrase=$(realpath "$2")
mkdir -p "$destination"
temporary=$(mktemp -d /tmp/doc-insight-backup.XXXXXXXX)
compose=(docker compose -f docker-compose.yml -f deploy/compose.secret.yml -f deploy/compose.private.yml --profile '*')
cleanup() {
  local status=$?
  if ! "${compose[@]}" up -d --no-build --wait --wait-timeout 240 > "$destination/restart.log" 2>&1; then
    echo "Restart failed; inspect $destination/restart.log" >&2
    status=1
  fi
  case "$temporary" in /tmp/doc-insight-backup.*) rm -rf -- "$temporary" ;; esac
  exit "$status"
}
trap cleanup EXIT
"${compose[@]}" stop caddy gateway ingest relay worker query minio redis
"${compose[@]}" exec -T db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$temporary/database.dump"
snapshot() {
  local service=$1
  shift
  local container
  container=$("${compose[@]}" ps -a -q "$service")
  docker run --rm --volumes-from "$container:ro" -v "$temporary:/backup" \
    busybox:1.37.0-musl tar -czf "/backup/$service.tgz" "$@"
}
snapshot minio /data /keys
snapshot redis /data
snapshot dev-issuer /issuer /jwks
cp .env "$temporary/deployment.env"
docker compose --profile '*' images --format json > "$temporary/images.json"
archive="$destination/$(date -u +%Y%m%dT%H%M%SZ).tar.gpg"
tar -C "$temporary" -cf - . | gpg --batch --yes --pinentry-mode loopback \
  --passphrase-file "$passphrase" --symmetric --cipher-algo AES256 --output "$archive"
sha256sum "$archive" > "$archive.sha256"
echo "Encrypted backup: $archive"
