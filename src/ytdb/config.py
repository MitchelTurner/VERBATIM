"""Application settings loaded from environment variables.

Copy ``.env.example`` to ``.env`` for local development. Cloud platforms
(Railway, Render) inject ``DATABASE_URL`` and ``PORT`` automatically.

Caption downloads from cloud IPs are often blocked by YouTube. Set either
``WEBSHARE_PROXY_USERNAME`` / ``WEBSHARE_PROXY_PASSWORD`` (recommended
rotating residential proxies) or ``YOUTUBE_HTTP_PROXY`` /
``YOUTUBE_HTTPS_PROXY`` so ``TranscriptClient`` can reach captions.
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
    webshare_proxy_username: str | None = None
    webshare_proxy_password: str | None = None
    youtube_http_proxy: str | None = None
    youtube_https_proxy: str | None = None
    # Pause between caption downloads to avoid YouTube 429s through a proxy.
    youtube_caption_delay: float = 2.5
    # Extra attempts after a 429 / RetryError before failing the video.
    youtube_caption_max_retries: int = 5

    def has_youtube_proxy(self) -> bool:
        if self.webshare_proxy_username and self.webshare_proxy_password:
            return True
        return bool(self.youtube_http_proxy or self.youtube_https_proxy)


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
        webshare_proxy_username=os.getenv("WEBSHARE_PROXY_USERNAME") or None,
        webshare_proxy_password=os.getenv("WEBSHARE_PROXY_PASSWORD") or None,
        youtube_http_proxy=os.getenv("YOUTUBE_HTTP_PROXY") or None,
        youtube_https_proxy=os.getenv("YOUTUBE_HTTPS_PROXY") or None,
        youtube_caption_delay=float(os.getenv("YOUTUBE_CAPTION_DELAY", "2.5")),
        youtube_caption_max_retries=int(os.getenv("YOUTUBE_CAPTION_MAX_RETRIES", "5")),
    )
