from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ytdb.api.routes import router
from ytdb.config import get_settings
from ytdb.db.repository import TranscriptRepository
from ytdb.jobs.runner import poll_due_jobs

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(poll_due_jobs, "interval", minutes=1, id="poll_sync_jobs")
    scheduler.start()
    return scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    settings = get_settings()
    TranscriptRepository(settings.database_url).init_db()
    _scheduler = start_scheduler()
    logger.info("Scheduler started")
    yield
    if _scheduler:
        _scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    app = FastAPI(title="YouTube Transcript Sync", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api")

    frontend_dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app


app = create_app()
