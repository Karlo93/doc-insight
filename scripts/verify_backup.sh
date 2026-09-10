#!/usr/bin/env bash
# Restore only into new, disposable containers and volumes; never touch the live DB.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ $# != 3 ]]; then
  echo "Usage: bash scripts/verify_backup.sh ARCHIVE PASSPHRASE_FILE QUERY_IMAGE" >&2
  exit 2
fi
umask 077
archive=$(realpath "$1")
passphrase=$(realpath "$2")
query_image=$3
temporary=$(mktemp -d /tmp/doc-insight-restore.XXXXXXXX)
prefix="di-restore-$(date +%s)-$$"
cleanup() {
  docker rm -f "$prefix-db" "$prefix-minio" "$prefix-redis" "$prefix-issuer" >/dev/null 2>&1 || true
  docker volume rm "$prefix-db" "$prefix-data" "$prefix-keys" "$prefix-redis" "$prefix-issuer" "$prefix-jwks" >/dev/null 2>&1 || true
  docker network rm "$prefix" >/dev/null 2>&1 || true
  case "$temporary" in /tmp/doc-insight-restore.*) rm -rf -- "$temporary" ;; esac
}
trap cleanup EXIT
gpg --batch --pinentry-mode loopback --passphrase-file "$passphrase" \
  --decrypt "$archive" | tar -xf - -C "$temporary"
password=$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')
printf 'POSTGRES_PASSWORD=%s\nPOSTGRES_DB=restored\n' "$password" > "$temporary/db.env"
docker network create "$prefix" >/dev/null
docker run -d --name "$prefix-db" --network "$prefix" --network-alias restore-db \
  --env-file "$temporary/db.env" -v "$prefix-db:/var/lib/postgresql/data" \
  pgvector/pgvector:0.8.6-pg16 >/dev/null
for _ in $(seq 1 60); do
  # The image's temporary init server listens only on a Unix socket.
  docker exec "$prefix-db" pg_isready -h 127.0.0.1 -U postgres -d restored >/dev/null 2>&1 && break
  sleep 1
done
docker exec -i "$prefix-db" pg_restore -U postgres -d restored \
  --no-owner --no-privileges --exit-on-error < "$temporary/database.dump"
awk -F= '/^DI_S3_ACCESS_KEY=/{print "MINIO_ROOT_USER=" $2} /^DI_S3_SECRET_KEY=/{print "MINIO_ROOT_PASSWORD=" $2}' \
  "$temporary/deployment.env" > "$temporary/minio.env"
echo 'MINIO_KMS_SECRET_KEY_FILE=/keys/sse-key' >> "$temporary/minio.env"
docker create --name "$prefix-minio" --network "$prefix" --network-alias restore-minio \
  --env-file "$temporary/minio.env" -v "$prefix-data:/data" -v "$prefix-keys:/keys" \
  -v "$PWD/scripts/minio-start.sh:/scripts/minio-start.sh:ro" --entrypoint /bin/sh \
  minio/minio:RELEASE.2025-09-07T16-13-09Z /scripts/minio-start.sh >/dev/null
docker run --rm --volumes-from "$prefix-minio" -v "$temporary:/backup:ro" \
  busybox:1.37.0-musl tar -xzf /backup/minio.tgz -C /
docker start "$prefix-minio" >/dev/null
for _ in $(seq 1 60); do
  docker exec "$prefix-minio" curl -fsS http://localhost:9000/minio/health/ready >/dev/null 2>&1 && break
  sleep 1
done
printf 'RESTORE_DB=postgresql+psycopg://postgres:%s@restore-db:5432/restored\n' "$password" >> "$temporary/minio.env"
awk -F= '/^DI_S3_BUCKET=/{print "RESTORE_BUCKET=" $2}' "$temporary/deployment.env" >> "$temporary/minio.env"
docker run --rm -i --network "$prefix" --env-file "$temporary/minio.env" \
  --entrypoint python "$query_image" - <<'PY'
import hashlib, json, os
import boto3
from sqlalchemy import create_engine, text
engine = create_engine(os.environ['RESTORE_DB'], hide_parameters=True)
s3 = boto3.client('s3', endpoint_url='http://restore-minio:9000',
    aws_access_key_id=os.environ['MINIO_ROOT_USER'], aws_secret_access_key=os.environ['MINIO_ROOT_PASSWORD'])
with engine.connect() as connection:
    rows = connection.execute(text('SELECT object_key, sha256 FROM documents WHERE object_key IS NOT NULL')).all()
    counts = {table: connection.execute(text(f'SELECT count(*) FROM {table}')).scalar_one()
              for table in ('documents','chunks','entities','outbox','llm_usage','llm_budgets')}
for key, expected in rows:
    response = s3.get_object(Bucket=os.environ.get('RESTORE_BUCKET','documents'), Key=key)
    digest = hashlib.sha256()
    body = response['Body']
    try:
        for chunk in body.iter_chunks(1024 * 1024): digest.update(chunk)
    finally:
        body.close()
    if digest.hexdigest() != expected: raise RuntimeError('Restored original hash mismatch')
print(json.dumps({'restored_counts': counts, 'original_hashes_verified': len(rows)}))
PY
docker create --name "$prefix-redis" --network "$prefix" -v "$prefix-redis:/data" \
  redis:7.4.9-alpine redis-server --appendonly yes >/dev/null
docker run --rm --volumes-from "$prefix-redis" -v "$temporary:/backup:ro" \
  busybox:1.37.0-musl tar -xzf /backup/redis.tgz -C /
docker start "$prefix-redis" >/dev/null
for _ in $(seq 1 30); do
  [[ $(docker exec "$prefix-redis" redis-cli ping 2>/dev/null) == PONG ]] && break
  sleep 1
done
stream_length=$(docker exec "$prefix-redis" redis-cli XLEN di:documents)
[[ $stream_length =~ ^[0-9]+$ ]] || { echo 'Restored Redis is not ready' >&2; exit 1; }
printf 'Restored stream length: %s\n' "$stream_length"
docker create --name "$prefix-issuer" -v "$prefix-issuer:/issuer" -v "$prefix-jwks:/jwks" \
  busybox:1.37.0-musl true >/dev/null
docker run --rm --volumes-from "$prefix-issuer" -v "$temporary:/backup:ro" \
  busybox:1.37.0-musl tar -xzf /backup/dev-issuer.tgz -C /
gateway_image=${query_image/-query:/-gateway:}
docker run --rm -i --volumes-from "$prefix-issuer:ro" --entrypoint python "$gateway_image" - <<'PY'
import json
from pathlib import Path
import jwt
from doc_insight.contracts.gateway import Identity
from doc_insight.gateway.dev_identity import mint_token
from doc_insight.gateway.settings import Settings
token = mint_token(Path('/issuer/keys'), Identity('demo','restore-check'), 60, Settings())
key = jwt.PyJWK(json.loads(Path('/jwks/jwks.json').read_text())['keys'][0])
claims = jwt.decode(token, key.key, algorithms=['RS256'], audience='doc-insight', issuer='doc-insight-dev')
if claims['tenant'] != 'demo': raise RuntimeError('Restored identity mismatch')
print('Restored signing key and public JWKS verified.')
PY
echo 'Isolated database and encrypted-object restore verified.'
