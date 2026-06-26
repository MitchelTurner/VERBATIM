from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

FREQUENCY_CHOICES = ["manual", "15m", "30m", "1h", "6h", "12h", "24h", "168h"]


class SyncJobCreate(BaseModel):
    name: str | None = None
    channel_account: str = Field(min_length=1, max_length=512)
    max_videos: int | None = Field(default=None, ge=1, le=10000)
    languages: list[str] = Field(default_factory=lambda: ["en"])
    frequency: str = "manual"
    enabled: bool = True
    force_refresh: bool = False


class SyncJobUpdate(BaseModel):
    name: str | None = None
    channel_account: str | None = Field(default=None, min_length=1, max_length=512)
    max_videos: int | None = Field(default=None, ge=1, le=10000)
    languages: list[str] | None = None
    frequency: str | None = None
    enabled: bool | None = None
    force_refresh: bool | None = None


class SyncJobResponse(BaseModel):
    id: int
    name: str | None
    channel_account: str
    max_videos: int | None
    languages: list[str]
    frequency: str
    enabled: bool
    force_refresh: bool
    last_run_at: datetime | None
    next_run_at: datetime | None
    last_status: str
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SyncRunResponse(BaseModel):
    id: int
    job_id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    videos_processed: int
    transcripts_saved: int
    transcripts_skipped: int
    errors: int
    message: str | None

    model_config = {"from_attributes": True}


class FrequencyOption(BaseModel):
    value: str
    label: str


class ChannelSummary(BaseModel):
    id: int
    youtube_channel_id: str
    name: str | None
    url: str
    transcript_count: int

    model_config = {"from_attributes": True}
