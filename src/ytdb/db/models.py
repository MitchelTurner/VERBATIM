"""SQLAlchemy ORM models for the transcript database.

Relationship overview:
    Channel 1──* Video 1──* Transcript
    SyncJob 1──* SyncRun

``content_type`` on Video is one of: video, stream, live.
``is_live`` is True while a broadcast is still in progress.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    youtube_channel_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(512))
    url: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    videos: Mapped[list[Video]] = relationship(back_populates="channel")


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), index=True)
    youtube_video_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(1024))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    url: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(16), default="video")
    is_live: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    channel: Mapped[Channel] = relationship(back_populates="videos")
    transcripts: Mapped[list[Transcript]] = relationship(back_populates="video")


class Transcript(Base):
    __tablename__ = "transcripts"
    __table_args__ = (
        UniqueConstraint("video_id", "language_code", name="uq_transcript_video_language"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), index=True)
    language: Mapped[str] = mapped_column(String(64))
    language_code: Mapped[str] = mapped_column(String(16))
    is_auto_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    content: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    video: Mapped[Video] = relationship(back_populates="transcripts")


class SyncJob(Base):
    __tablename__ = "sync_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(String(256))
    channel_account: Mapped[str] = mapped_column(String(512))
    max_videos: Mapped[int | None] = mapped_column(Integer)
    languages: Mapped[list[str]] = mapped_column(JSON, default=list)
    frequency: Mapped[str] = mapped_column(String(32), default="manual")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    force_refresh: Mapped[bool] = mapped_column(Boolean, default=False)
    include_videos: Mapped[bool] = mapped_column(Boolean, default=True)
    include_streams: Mapped[bool] = mapped_column(Boolean, default=True)
    include_live: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str] = mapped_column(String(32), default="idle")
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Deleting a job removes its run history (FK ondelete=CASCADE as well).
    runs: Mapped[list[SyncRun]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("sync_jobs.id", ondelete="CASCADE"), index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32))
    videos_processed: Mapped[int] = mapped_column(Integer, default=0)
    transcripts_saved: Mapped[int] = mapped_column(Integer, default=0)
    transcripts_skipped: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text)

    job: Mapped[SyncJob] = relationship(back_populates="runs")
