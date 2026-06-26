from __future__ import annotations

import logging
import threading

from ytdb.config import get_settings
from ytdb.db.job_repository import SyncJobRepository
from ytdb.db.models import SyncRun
from ytdb.db.repository import TranscriptRepository
from ytdb.sync import SyncService

logger = logging.getLogger(__name__)
_run_lock = threading.Lock()


def run_sync_job(job_id: int) -> None:
    settings = get_settings()
    transcript_repo = TranscriptRepository(settings.database_url)
    job_repo = SyncJobRepository()

    with _run_lock:
        with transcript_repo.session() as session:
            job = job_repo.get_job(session, job_id)
            if job is None:
                raise ValueError(f"Sync job {job_id} not found")
            if job.last_status == "running":
                logger.info("Job %s already running, skipping", job_id)
                return

            run = job_repo.mark_running(session, job)
            run_id = run.id
            languages = list(job.languages or ["en"])
            account = job.channel_account
            max_videos = job.max_videos
            force_refresh = job.force_refresh
            session.commit()

    try:
        service = SyncService(
            repository=transcript_repo,
            preferred_languages=languages,
        )
        result = service.sync_channel(
            account,
            max_videos=max_videos,
            skip_existing=not force_refresh,
        )
        message = (
            f"Processed {result.videos_processed} videos; "
            f"saved {result.transcripts_saved} transcripts"
        )
        status = "success" if result.errors == 0 else "partial"
        with transcript_repo.session() as session:
            job = job_repo.get_job(session, job_id)
            run = session.get(SyncRun, run_id)
            if job and run:
                job_repo.complete_run(
                    session,
                    job,
                    run,
                    status=status,
                    videos_processed=result.videos_processed,
                    transcripts_saved=result.transcripts_saved,
                    transcripts_skipped=result.transcripts_skipped,
                    errors=result.errors,
                    message=message,
                )
                session.commit()
    except Exception as exc:
        logger.exception("Sync job %s failed", job_id)
        with transcript_repo.session() as session:
            job = job_repo.get_job(session, job_id)
            run = session.get(SyncRun, run_id)
            if job and run:
                job_repo.complete_run(
                    session,
                    job,
                    run,
                    status="failed",
                    videos_processed=0,
                    transcripts_saved=0,
                    transcripts_skipped=0,
                    errors=1,
                    message=str(exc),
                    error=str(exc),
                )
                session.commit()
        raise


def poll_due_jobs() -> None:
    settings = get_settings()
    repo = TranscriptRepository(settings.database_url)
    job_repo = SyncJobRepository()

    with repo.session() as session:
        due_jobs = job_repo.list_due_jobs(session)

    for job in due_jobs:
        try:
            run_sync_job(job.id)
        except Exception:
            logger.exception("Scheduled sync failed for job %s", job.id)
