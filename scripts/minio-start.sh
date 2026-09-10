#!/bin/sh
set -eu

# Keep a generated development key across restarts without committing a secret.
if [ ! -s "$MINIO_KMS_SECRET_KEY_FILE" ]; then
    umask 077
    key=$(head -c 32 /dev/urandom | base64)
    printf 'local-dev:%s\n' "$key" > "$MINIO_KMS_SECRET_KEY_FILE"
fi
exec minio server /data --console-address ':9001'
