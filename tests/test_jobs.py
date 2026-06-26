from datetime import datetime, timezone

import pytest

from ytdb.db.job_repository import SyncJobRepository
from ytdb.db.repository import TranscriptRepository
from ytdb.scheduler import compute_next_run, frequency_label


@pytest.fixture
def repository():
    repo = TranscriptRepository("sqlite+pysqlite:///:memory:")
    repo.init_db()
    return repo


@pytest.fixture
def job_repo():
    return SyncJobRepository()


def test_compute_next_run_for_manual_is_none():
    assert compute_next_run("manual") is None


def test_compute_next_run_adds_minutes():
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    result = compute_next_run("1h", start)
    assert result == datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc)


def test_frequency_label():
    assert frequency_label("24h") == "Daily"


def test_create_and_list_jobs(repository, job_repo):
    with repository.session() as session:
        job = job_repo.create_job(
            session,
            name="Test",
            channel_account="@example",
            max_videos=10,
            languages=["en"],
            frequency="24h",
            enabled=True,
            force_refresh=False,
        )
        session.commit()
        jobs = job_repo.list_jobs(session)
        assert len(jobs) == 1
        assert jobs[0].id == job.id
        assert jobs[0].next_run_at is not None


def test_update_job_enabled_flag(repository, job_repo):
    with repository.session() as session:
        job = job_repo.create_job(
            session,
            name=None,
            channel_account="@example",
            max_videos=None,
            languages=["en"],
            frequency="1h",
            enabled=True,
            force_refresh=False,
        )
        session.commit()

        job_repo.update_job(session, job, enabled=False)
        session.commit()
        assert job.enabled is False
        assert job.next_run_at is None


def test_list_due_jobs(repository, job_repo):
    now = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)
    with repository.session() as session:
        job = job_repo.create_job(
            session,
            name=None,
            channel_account="@due",
            max_videos=5,
            languages=["en"],
            frequency="1h",
            enabled=True,
            force_refresh=False,
        )
        job.next_run_at = datetime(2024, 6, 1, 11, 0, tzinfo=timezone.utc)
        job.last_status = "idle"
        session.commit()

        due = job_repo.list_due_jobs(session, now=now)
        assert len(due) == 1
        assert due[0].channel_account == "@due"
