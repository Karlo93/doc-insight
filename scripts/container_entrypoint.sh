#!/bin/sh
set -eu
if [ "$#" -gt 0 ]; then
    exec "$@"
fi
case "$DI_CONTAINER_APP" in
    gateway) exec di-gateway serve ;;
    ingest) exec di-ingest serve ;;
    query) exec di-query serve ;;
    worker) exec di worker run ;;
    *) echo 'Unknown application' >&2; exit 1 ;;
esac
