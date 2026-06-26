from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ytdb.db.engine import create_db_engine
from ytdb.db.models import Base, Channel, Transcript, Video
from ytdb.youtube.transcripts import TranscriptData
from ytdb.youtube.channel import ChannelInfo, VideoInfo


class TranscriptRepository:
    def __init__(self, database_url: str) -> None:
        self.engine = create_db_engine(database_url)
        self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def init_db(self) -> None:
        Base.metadata.create_all(self.engine)

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
            return existing

        record = Video(
            channel_id=channel.id,
            youtube_video_id=video.video_id,
            title=video.title,
            published_at=video.published_at,
            url=video.url,
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
