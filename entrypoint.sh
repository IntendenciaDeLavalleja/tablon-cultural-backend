#!/bin/sh
set -eu
if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
    flask db upgrade
    flask init-bucket
fi
exec "$@"
