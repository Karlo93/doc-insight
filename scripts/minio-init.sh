#!/bin/sh
set -eu

mc alias set local http://minio:9000 "$DI_S3_ACCESS_KEY" "$DI_S3_SECRET_KEY" >/dev/null
mc mb --ignore-existing "local/$DI_S3_BUCKET"
mc encrypt set sse-s3 "local/$DI_S3_BUCKET"
mc encrypt info "local/$DI_S3_BUCKET"
