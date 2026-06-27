#!/bin/sh
# Production entrypoint for Docker and Railway.
#
# Required env:
#   DATABASE_URL  PostgreSQL connection string
#
# Optional env:
#   PORT          Listen port (default 8000; Railway sets this automatically)
#   HOST          Bind address (default 0.0.0.0)
#   DB_WAIT       Set to "false" to skip waiting for Postgres on startup
set -eu

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

echo "Starting ytdb API on ${HOST}:${PORT}"

if [ -z "${DATABASE_URL:-}" ]; then
  echo "ERROR: DATABASE_URL is required. Set it to your PostgreSQL connection string." >&2
  exit 1
fi

# On Railway, Postgres may still be provisioning when the web service starts.
if [ "${DB_WAIT:-auto}" != "false" ]; then
  python /app/scripts/wait_for_db.py || true
fi

exec uvicorn ytdb.api.app:app \
  --host "$HOST" \
  --port "$PORT" \
  --proxy-headers \
  --forwarded-allow-ips "*"
