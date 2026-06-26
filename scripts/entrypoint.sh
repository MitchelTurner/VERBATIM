#!/bin/sh
set -eu

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

echo "Starting ytdb API on ${HOST}:${PORT}"

if [ -z "${DATABASE_URL:-}" ]; then
  echo "ERROR: DATABASE_URL is required. Set it to your PostgreSQL connection string." >&2
  exit 1
fi

if [ "${DB_WAIT:-auto}" != "false" ]; then
  python /app/scripts/wait_for_db.py || true
fi

exec uvicorn ytdb.api.app:app \
  --host "$HOST" \
  --port "$PORT" \
  --proxy-headers \
  --forwarded-allow-ips "*"
