"""FastAPI application factory and lifecycle.

Startup is split into two phases so cloud health checks pass quickly:
  1. Uvicorn binds and serves /health immediately
  2. A background task initializes the DB and starts APScheduler

In production the built React app (frontend/dist) is mounted at /.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Event

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from ytdb.api.routes import router
from ytdb.config import get_settings
from ytdb.db.repository import TranscriptRepository
from ytdb.jobs.runner import poll_due_jobs

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_db_ready = Event()  # Set once DB init + scheduler succeed; exposed via /health
_init_task: asyncio.Task | None = None


def start_scheduler() -> BackgroundScheduler:
    """Poll for due sync jobs once per minute."""
    scheduler = BackgroundScheduler()
    scheduler.add_job(poll_due_jobs, "interval", minutes=1, id="poll_sync_jobs")
    scheduler.start()
    return scheduler


async def _initialize() -> None:
    """Retry DB connection until Postgres is reachable (common on Railway)."""
    global _scheduler

    settings = get_settings()
    max_attempts = settings.db_init_retries
    delay_seconds = settings.db_init_retry_delay

    for attempt in range(1, max_attempts + 1):
        try:
            TranscriptRepository(settings.database_url).init_db()
            _scheduler = start_scheduler()
            _db_ready.set()
            logger.info("Database initialized and scheduler started")
            return
        except Exception:
            logger.exception("Startup attempt %s/%s failed", attempt, max_attempts)
            if attempt == max_attempts:
                logger.error(
                    "Could not initialize database after %s attempts", max_attempts
                )
                return
            await asyncio.sleep(delay_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _init_task
    _init_task = asyncio.create_task(_initialize())
    logger.info("Application process started; database init running in background")
    yield
    if _init_task:
        _init_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _init_task
    if _scheduler:
        _scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    app = FastAPI(title="VERBATIM", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "ready": _db_ready.is_set()})

    @app.get("/health/ready")
    def ready() -> JSONResponse:
        if _db_ready.is_set():
            return JSONResponse({"status": "ready"})
        return JSONResponse({"status": "starting"}, status_code=503)

    app.include_router(router, prefix="/api")

    frontend_dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app


app = create_app()
