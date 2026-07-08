from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ytdb.db.models import SyncJob, SyncRun
from ytdb.scheduler import compute_next_run


class SyncJobRepository:
    def list_jobs(self, session: Session) -> list[SyncJob]:
        return list(
            session.scalars(select(SyncJob).order_by(SyncJob.created_at.desc()))
        )

    def get_job(self, session: Session, job_id: int) -> SyncJob | None:
        return session.get(SyncJob, job_id)

    def create_job(
        self,
        session: Session,
        *,
        name: str | None,
        channel_account: str,
        max_videos: int | None,
        languages: list[str],
        frequency: str,
        enabled: bool,
        force_refresh: bool,
        include_videos: bool = True,
        include_streams: bool = True,
        include_live: bool = True,
    ) -> SyncJob:
        job = SyncJob(
            name=name,
            channel_account=channel_account.strip(),
            max_videos=max_videos,
            languages=languages or ["en"],
            frequency=frequency,
            enabled=enabled,
            force_refresh=force_refresh,
            include_videos=include_videos,
            include_streams=include_streams,
            include_live=include_live,
            last_status="idle",
            next_run_at=compute_next_run(frequency) if enabled and frequency != "manual" else None,
        )
        session.add(job)
        session.flush()
        return job

    def update_job(self, session: Session, job: SyncJob, **fields) -> SyncJob:
        for key, value in fields.items():
            if hasattr(job, key):
                setattr(job, key, value)

        if "channel_account" in fields and fields["channel_account"] is not None:
            job.channel_account = fields["channel_account"].strip()

        if any(k in fields for k in ("frequency", "enabled")):
            if job.enabled and job.frequency != "manual":
                job.next_run_at = compute_next_run(job.frequency)
            else:
                job.next_run_at = None

        session.flush()
        return job

    def delete_job(self, session: Session, job: SyncJob) -> None:
        session.delete(job)
        session.flush()

    def list_due_jobs(self, session: Session, now: datetime | None = None) -> list[SyncJob]:
        current = now or datetime.now(timezone.utc)
        return list(
            session.scalars(
                select(SyncJob).where(
                    SyncJob.enabled.is_(True),
                    SyncJob.frequency != "manual",
                    SyncJob.next_run_at.is_not(None),
                    SyncJob.next_run_at <= current,
                    SyncJob.last_status != "running",
                )
            )
        )

    def recover_interrupted_jobs(self, session: Session) -> int:
        """Reset jobs left in ``running`` state by a previous process.

        Sync jobs execute inside the API process, so right after startup no
        job can actually be running. A crash or redeploy mid-run leaves
        ``last_status='running'`` forever, and such jobs are silently skipped
        by both the scheduler poll and manual triggers — the job looks alive
        in the UI but never syncs again. Returns the number of jobs reset.
        """
        now = datetime.now(timezone.utc)

        stuck_jobs = list(
            session.scalars(select(SyncJob).where(SyncJob.last_status == "running"))
        )
        for job in stuck_jobs:
            job.last_status = "interrupted"
            job.last_error = "Sync was interrupted by a server restart"

        stuck_runs = list(
            session.scalars(select(SyncRun).where(SyncRun.status == "running"))
        )
        for run in stuck_runs:
            run.status = "interrupted"
            run.finished_at = now
            run.message = "Interrupted by a server restart"

        session.flush()
        return len(stuck_jobs)

    def mark_running(self, session: Session, job: SyncJob) -> SyncRun:
        job.last_status = "running"
        job.last_error = None
        run = SyncRun(
            job_id=job.id,
            started_at=datetime.now(timezone.utc),
            status="running",
        )
        session.add(run)
        session.flush()
        return run

    def complete_run(
        self,
        session: Session,
        job: SyncJob,
        run: SyncRun,
        *,
        status: str,
        videos_processed: int,
        transcripts_saved: int,
        transcripts_skipped: int,
        errors: int,
        message: str | None = None,
        error: str | None = None,
    ) -> None:
        finished = datetime.now(timezone.utc)
        run.finished_at = finished
        run.status = status
        run.videos_processed = videos_processed
        run.transcripts_saved = transcripts_saved
        run.transcripts_skipped = transcripts_skipped
        run.errors = errors
        run.message = message

        job.last_run_at = finished
        job.last_status = status
        job.last_error = error
        job.next_run_at = (
            compute_next_run(job.frequency, finished)
            if job.enabled and job.frequency != "manual"
            else None
        )
        session.flush()

    def list_runs(self, session: Session, job_id: int, limit: int = 20) -> list[SyncRun]:
        return list(
            session.scalars(
                select(SyncRun)
                .where(SyncRun.job_id == job_id)
                .order_by(SyncRun.started_at.desc())
                .limit(limit)
            )
        )
