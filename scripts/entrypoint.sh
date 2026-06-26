#!/bin/sh
set -eu

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

if [ -z "${DATABASE_URL:-}" ]; then
  echo "ERROR: DATABASE_URL is required. Set it to your PostgreSQL connection string." >&2
  exit 1
fi

python /app/scripts/wait_for_db.py

exec uvicorn ytdb.api.app:app --host "$HOST" --port "$PORT"
