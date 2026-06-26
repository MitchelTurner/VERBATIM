from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException

from ytdb.jobs.runner import run_sync_job
from ytdb.api.schemas import (
    FREQUENCY_CHOICES,
    ChannelSummary,
    FrequencyOption,
    SyncJobCreate,
    SyncJobResponse,
    SyncJobUpdate,
    SyncRunResponse,
)
from ytdb.config import get_settings
from ytdb.db.job_repository import SyncJobRepository
from ytdb.db.repository import TranscriptRepository
from ytdb.scheduler import frequency_label

router = APIRouter()
job_repo = SyncJobRepository()


def _validate_frequency(frequency: str) -> None:
    if frequency not in FREQUENCY_CHOICES:
        raise HTTPException(status_code=400, detail=f"Invalid frequency: {frequency}")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/frequencies", response_model=list[FrequencyOption])
def list_frequencies() -> list[FrequencyOption]:
    return [FrequencyOption(value=value, label=frequency_label(value)) for value in FREQUENCY_CHOICES]


@router.get("/channels", response_model=list[ChannelSummary])
def list_channels() -> list[ChannelSummary]:
    settings = get_settings()
    repo = TranscriptRepository(settings.database_url)
    with repo.session() as session:
        channels = repo.list_channels(session)
        return [
            ChannelSummary(
                id=channel.id,
                youtube_channel_id=channel.youtube_channel_id,
                name=channel.name,
                url=channel.url,
                transcript_count=repo.count_transcripts_for_channel(session, channel.id),
            )
            for channel in channels
        ]


@router.get("/jobs", response_model=list[SyncJobResponse])
def list_jobs() -> list[SyncJobResponse]:
    settings = get_settings()
    repo = TranscriptRepository(settings.database_url)
    with repo.session() as session:
        jobs = job_repo.list_jobs(session)
        return [SyncJobResponse.model_validate(job) for job in jobs]


@router.post("/jobs", response_model=SyncJobResponse, status_code=201)
def create_job(payload: SyncJobCreate) -> SyncJobResponse:
    _validate_frequency(payload.frequency)
    settings = get_settings()
    repo = TranscriptRepository(settings.database_url)
    with repo.session() as session:
        job = job_repo.create_job(
            session,
            name=payload.name,
            channel_account=payload.channel_account,
            max_videos=payload.max_videos,
            languages=payload.languages,
            frequency=payload.frequency,
            enabled=payload.enabled,
            force_refresh=payload.force_refresh,
        )
        session.commit()
        session.refresh(job)
        return SyncJobResponse.model_validate(job)


@router.get("/jobs/{job_id}", response_model=SyncJobResponse)
def get_job(job_id: int) -> SyncJobResponse:
    settings = get_settings()
    repo = TranscriptRepository(settings.database_url)
    with repo.session() as session:
        job = job_repo.get_job(session, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return SyncJobResponse.model_validate(job)


@router.patch("/jobs/{job_id}", response_model=SyncJobResponse)
def update_job(job_id: int, payload: SyncJobUpdate) -> SyncJobResponse:
    if payload.frequency is not None:
        _validate_frequency(payload.frequency)

    settings = get_settings()
    repo = TranscriptRepository(settings.database_url)
    with repo.session() as session:
        job = job_repo.get_job(session, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        fields = payload.model_dump(exclude_unset=True)
        job_repo.update_job(session, job, **fields)
        session.commit()
        session.refresh(job)
        return SyncJobResponse.model_validate(job)


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(job_id: int) -> None:
    settings = get_settings()
    repo = TranscriptRepository(settings.database_url)
    with repo.session() as session:
        job = job_repo.get_job(session, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        job_repo.delete_job(session, job)
        session.commit()


@router.post("/jobs/{job_id}/run", status_code=202)
def trigger_job(job_id: int, background_tasks: BackgroundTasks) -> dict[str, str]:
    settings = get_settings()
    repo = TranscriptRepository(settings.database_url)
    with repo.session() as session:
        job = job_repo.get_job(session, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.last_status == "running":
            raise HTTPException(status_code=409, detail="Job is already running")

    def _run() -> None:
        try:
            run_sync_job(job_id)
        except Exception:
            pass

    background_tasks.add_task(_run)
    return {"status": "started"}


@router.get("/jobs/{job_id}/runs", response_model=list[SyncRunResponse])
def list_job_runs(job_id: int) -> list[SyncRunResponse]:
    settings = get_settings()
    repo = TranscriptRepository(settings.database_url)
    with repo.session() as session:
        job = job_repo.get_job(session, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        runs = job_repo.list_runs(session, job_id)
        return [SyncRunResponse.model_validate(run) for run in runs]
