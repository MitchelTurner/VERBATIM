"""Core sync orchestration.

``SyncService`` is the single place that ties together channel discovery
(yt-dlp), caption download (youtube-transcript-api), and database upserts.
Both the CLI ``sync`` command and scheduled web jobs call into this module.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ytdb.config import get_settings
from ytdb.db.repository import TranscriptRepository
from ytdb.youtube.channel import ChannelClient, ChannelInfo, VideoInfo
from ytdb.youtube.transcripts import TranscriptClient

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    channel: ChannelInfo
    videos_processed: int
    transcripts_saved: int
    transcripts_skipped: int
    errors: int


class SyncService:
    """Fetch and persist transcripts for one YouTube channel."""

    def __init__(
        self,
        repository: TranscriptRepository | None = None,
        channel_client: ChannelClient | None = None,
        transcript_client: TranscriptClient | None = None,
        preferred_languages: list[str] | None = None,
    ) -> None:
        settings = get_settings()
        self.repository = repository or TranscriptRepository(settings.database_url)
        self.channel_client = channel_client or ChannelClient()
        self.transcript_client = transcript_client or TranscriptClient(preferred_languages)

    def sync_channel(
        self,
        account: str,
        max_videos: int | None = None,
        skip_existing: bool = True,
        *,
        include_videos: bool = True,
        include_streams: bool = True,
        include_live: bool = True,
    ) -> SyncResult:
        self.repository.init_db()

        channel_info = self.channel_client.get_channel_info(account)
        videos = self.channel_client.list_content(
            account,
            max_items=max_videos,
            include_videos=include_videos,
            include_streams=include_streams,
            include_live=include_live,
        )

        videos_processed = 0
        transcripts_saved = 0
        transcripts_skipped = 0
        errors = 0

        with self.repository.session() as session:
            channel = self.repository.upsert_channel(session, channel_info)

            for video_info in videos:
                videos_processed += 1
                try:
                    saved = self._process_video(
                        session,
                        channel,
                        video_info,
                        skip_existing=skip_existing,
                    )
                    if saved:
                        transcripts_saved += 1
                    else:
                        transcripts_skipped += 1
                except Exception:
                    errors += 1
                    logger.exception("Failed to process video %s", video_info.video_id)

            session.commit()

        return SyncResult(
            channel=channel_info,
            videos_processed=videos_processed,
            transcripts_saved=transcripts_saved,
            transcripts_skipped=transcripts_skipped,
            errors=errors,
        )

    def _process_video(
        self,
        session,
        channel,
        video_info: VideoInfo,
        *,
        skip_existing: bool,
    ) -> bool:
        # Capture live state before upsert_video overwrites it: when a
        # broadcast has ended since the last sync, the stored transcript only
        # covers the stream up to the last mid-broadcast fetch, so it needs
        # one more refresh to include the full stream.
        was_live_in_db = self.repository.video_marked_live(session, video_info.video_id)
        video = self.repository.upsert_video(session, channel, video_info)
        broadcast_ended = was_live_in_db and not video_info.is_live

        # Live broadcasts are never skipped — captions grow as the stream runs,
        # so we re-fetch on every sync while is_live is True, plus once more
        # after the broadcast ends.
        should_skip = (
            skip_existing
            and not video_info.is_live
            and not broadcast_ended
            and self.repository.has_transcript(session, video.id)
        )
        if should_skip:
            return False

        transcript = self.transcript_client.fetch_transcript(video_info.video_id)
        if transcript is None:
            return False

        self.repository.upsert_transcript(session, video, transcript)
        return True
