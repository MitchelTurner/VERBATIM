"""Application settings loaded from environment variables.

Copy ``.env.example`` to ``.env`` for local development. Cloud platforms
(Railway, Render) inject ``DATABASE_URL`` and ``PORT`` automatically.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from ytdb.db.engine import normalize_database_url

load_dotenv()


@dataclass(frozen=True)
class Settings:
    database_url: str
    host: str
    port: int
    db_init_retries: int
    db_init_retry_delay: float
    youtube_api_key: str | None = None


def get_settings() -> Settings:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError(
            "DATABASE_URL is not set. Copy .env.example to .env and configure it."
        )

    return Settings(
        database_url=normalize_database_url(database_url),
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        db_init_retries=int(os.getenv("DB_INIT_RETRIES", "30")),
        db_init_retry_delay=float(os.getenv("DB_INIT_RETRY_DELAY", "2")),
        youtube_api_key=os.getenv("YOUTUBE_API_KEY") or None,
    )
