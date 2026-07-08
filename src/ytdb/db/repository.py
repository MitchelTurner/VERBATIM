"""Database access layer for channels, videos, and transcripts.

All write paths use upsert semantics keyed on YouTube IDs so repeated syncs
are safe. Search helpers power the web UI transcript browser.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from ytdb.db.engine import create_db_engine
from ytdb.db.migrations import run_migrations
from ytdb.db.models import Base, Channel, SyncJob, Transcript, Video
from ytdb.youtube.transcripts import TranscriptData
from ytdb.youtube.channel import ChannelInfo, VideoInfo


class TranscriptRepository:
    """CRUD and upsert operations for transcript data."""

    def __init__(self, database_url: str) -> None:
        self.engine = create_db_engine(database_url)
        self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def init_db(self) -> None:
        """Create tables and apply any lightweight additive migrations."""
        Base.metadata.create_all(self.engine)
        run_migrations(self.engine.url.render_as_string(hide_password=False))

    def session(self) -> Session:
        return self._session_factory()

    def upsert_channel(self, session: Session, channel: ChannelInfo) -> Channel:
        existing = session.scalar(
            select(Channel).where(Channel.youtube_channel_id == channel.channel_id)
        )
        if existing:
            existing.name = channel.name
            existing.url = channel.url
            return existing

        record = Channel(
            youtube_channel_id=channel.channel_id,
            name=channel.name,
            url=channel.url,
        )
        session.add(record)
        session.flush()
        return record

    def upsert_video(self, session: Session, channel: Channel, video: VideoInfo) -> Video:
        existing = session.scalar(
            select(Video).where(Video.youtube_video_id == video.video_id)
        )
        if existing:
            existing.title = video.title
            existing.published_at = video.published_at
            existing.url = video.url
            existing.channel_id = channel.id
            existing.content_type = video.content_type
            existing.is_live = video.is_live
            return existing

        record = Video(
            channel_id=channel.id,
            youtube_video_id=video.video_id,
            title=video.title,
            published_at=video.published_at,
            url=video.url,
            content_type=video.content_type,
            is_live=video.is_live,
        )
        session.add(record)
        session.flush()
        return record

    def upsert_transcript(
        self, session: Session, video: Video, transcript: TranscriptData
    ) -> Transcript:
        existing = session.scalar(
            select(Transcript).where(
                Transcript.video_id == video.id,
                Transcript.language_code == transcript.language_code,
            )
        )
        if existing:
            existing.language = transcript.language
            existing.is_auto_generated = transcript.is_auto_generated
            existing.content = transcript.content
            existing.fetched_at = datetime.now(timezone.utc)
            return existing

        record = Transcript(
            video_id=video.id,
            language=transcript.language,
            language_code=transcript.language_code,
            is_auto_generated=transcript.is_auto_generated,
            content=transcript.content,
        )
        session.add(record)
        session.flush()
        return record

    def video_marked_live(self, session: Session, youtube_video_id: str) -> bool:
        """True if the stored video row is still flagged as a live broadcast."""
        return bool(
            session.scalar(
                select(Video.is_live).where(Video.youtube_video_id == youtube_video_id)
            )
        )

    def list_channels(self, session: Session) -> list[Channel]:
        return list(session.scalars(select(Channel).order_by(Channel.name)))

    def has_transcript(self, session: Session, video_id: int) -> bool:
        return session.scalar(
            select(Transcript.id).where(Transcript.video_id == video_id).limit(1)
        ) is not None

    def count_transcripts_for_channel(self, session: Session, channel_id: int) -> int:
        return session.scalar(
            select(func.count(Transcript.id))
            .join(Video)
            .where(Video.channel_id == channel_id)
        ) or 0

    def get_stats(self, session: Session) -> dict[str, int]:
        return {
            "channels": session.scalar(select(func.count(Channel.id))) or 0,
            "videos": session.scalar(select(func.count(Video.id))) or 0,
            "transcripts": session.scalar(select(func.count(Transcript.id))) or 0,
            "sync_jobs": session.scalar(select(func.count(SyncJob.id))) or 0,
        }

    def search_transcripts(
        self,
        session: Session,
        *,
        search: str | None = None,
        channel_id: int | None = None,
        limit: int = 50,
    ) -> list[tuple[Transcript, Video, Channel]]:
        """Return transcripts newest-first, optionally filtered by channel or text."""
        query = (
            select(Transcript, Video, Channel)
            .join(Video, Transcript.video_id == Video.id)
            .join(Channel, Video.channel_id == Channel.id)
            .order_by(Transcript.fetched_at.desc())
            .limit(limit)
        )
        if channel_id is not None:
            query = query.where(Channel.id == channel_id)
        if search:
            pattern = f"%{search.strip()}%"
            query = query.where(
                or_(
                    Transcript.content.ilike(pattern),
                    Video.title.ilike(pattern),
                    Channel.name.ilike(pattern),
                )
            )
        return list(session.execute(query).all())

    def get_transcript(self, session: Session, transcript_id: int) -> tuple[Transcript, Video, Channel] | None:
        row = session.execute(
            select(Transcript, Video, Channel)
            .join(Video, Transcript.video_id == Video.id)
            .join(Channel, Video.channel_id == Channel.id)
            .where(Transcript.id == transcript_id)
        ).first()
        return row if row else None
