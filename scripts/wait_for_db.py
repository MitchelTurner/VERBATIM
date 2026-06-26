#!/usr/bin/env python3
"""Wait for PostgreSQL to accept connections before starting the API."""

from __future__ import annotations

import os
import sys
import time

import psycopg2


def main() -> int:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL is not set.", file=sys.stderr)
        return 1

    if not _should_wait(database_url):
        return 0

    timeout = int(os.getenv("DB_WAIT_TIMEOUT", "60"))
    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            conn = psycopg2.connect(database_url)
            conn.close()
            print("PostgreSQL is ready.")
            return 0
        except psycopg2.OperationalError as exc:
            print(f"Waiting for PostgreSQL: {exc}")
            time.sleep(2)

    print("ERROR: Timed out waiting for PostgreSQL.", file=sys.stderr)
    return 1


def _should_wait(database_url: str) -> bool:
    if os.getenv("DB_WAIT", "auto").lower() == "false":
        return False
    if os.getenv("DB_WAIT", "auto").lower() == "true":
        return True
    return "@postgres:" in database_url or "@localhost:" in database_url


if __name__ == "__main__":
    raise SystemExit(main())
