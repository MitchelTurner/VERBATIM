from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    database_url: str
    host: str
    port: int
    youtube_api_key: str | None = None


def get_settings() -> Settings:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError(
            "DATABASE_URL is not set. Copy .env.example to .env and configure it."
        )

    return Settings(
        database_url=database_url,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        youtube_api_key=os.getenv("YOUTUBE_API_KEY") or None,
    )
