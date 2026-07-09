"""Core sync orchestration.

``SyncService`` is the single place that ties together channel discovery
(yt-dlp), caption download (youtube-transcript-api), and database upserts.
Both the CLI ``sync`` command and scheduled web jobs call into this module.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from ytdb.config import get_settings
from ytdb.db.models import Video
from ytdb.db.repository import TranscriptRepository
from ytdb.youtube.channel import ChannelClient, ChannelInfo, VideoInfo
from ytdb.youtube.transcripts import TranscriptClient, TranscriptFetchError, is_rate_limited

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    channel: ChannelInfo
    videos_processed: int
    transcripts_saved: int
    transcripts_skipped: int
    errors: int
    error_messages: list[str] | None = None
    backfilled: int = 0


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
        self.transcript_client = transcript_client or TranscriptClient(
            preferred_languages,
            settings=settings,
        )
        # Space caption downloads so a full sync does not trip YouTube 429s.
        try:
            self._caption_delay = float(getattr(settings, "youtube_caption_delay", 5.0))
        except (TypeError, ValueError):
            self._caption_delay = 5.0
        self._fetched_this_run = 0
        self._consecutive_rate_limits = 0
        self._cooldown_until = 0.0

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
        self._fetched_this_run = 0
        self._consecutive_rate_limits = 0

        channel_info = self.channel_client.get_channel_info(account)
        discovered = self.channel_client.list_content(
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
        backfilled = 0
        error_messages: list[str] = []
        abort_remaining = False

        with self.repository.session() as session:
            channel = self.repository.upsert_channel(session, channel_info)

            # Retry videos left without captions by earlier rate-limited runs.
            # Cap to the same max_items budget so a catch-up sync stays bounded.
            backfill_limit = max_videos if max_videos is not None else 25
            missing_rows = self.repository.list_videos_missing_transcripts(
                session, channel.id, limit=backfill_limit
            )
            videos = self._merge_discovered_and_missing(discovered, missing_rows)
            backfilled = sum(
                1
                for item in videos
                if item.video_id in {row.youtube_video_id for row in missing_rows}
                and item.video_id not in {d.video_id for d in discovered}
            )

            for video_info in videos:
                if abort_remaining:
                    errors += 1
                    continue

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
                        self._consecutive_rate_limits = 0
                    else:
                        transcripts_skipped += 1
                except TranscriptFetchError as exc:
                    errors += 1
                    message = str(exc)
                    if message not in error_messages:
                        error_messages.append(message)
                    logger.error("Caption fetch blocked for %s: %s", video_info.video_id, exc)
                    if is_rate_limited(exc):
                        self._consecutive_rate_limits += 1
                        # Cool down before the next video; rotate proxy session
                        # so the next attempt leaves from a different IP.
                        self._cooldown_until = time.monotonic() + max(
                            30.0, self._caption_delay * 4
                        )
                        rotate = getattr(
                            self.transcript_client, "_rotate_proxy_session", None
                        )
                        if callable(rotate):
                            rotate()
                        # Stop burning the proxy quota once YouTube is clearly
                        # rate-limiting; remaining videos stay for the next run.
                        if self._consecutive_rate_limits >= 2:
                            abort_msg = (
                                "Stopped early after repeated YouTube rate limits "
                                "(HTTP 429). Wait a few minutes, then re-run to "
                                "backfill the rest."
                            )
                            if abort_msg not in error_messages:
                                error_messages.append(abort_msg)
                            abort_remaining = True
                    else:
                        self._consecutive_rate_limits = 0
                except Exception as exc:
                    errors += 1
                    self._consecutive_rate_limits = 0
                    message = f"{video_info.video_id}: {exc}"
                    if len(error_messages) < 5:
                        error_messages.append(message)
                    logger.exception("Failed to process video %s", video_info.video_id)

            session.commit()

        return SyncResult(
            channel=channel_info,
            videos_processed=videos_processed,
            transcripts_saved=transcripts_saved,
            transcripts_skipped=transcripts_skipped,
            errors=errors,
            error_messages=error_messages or None,
            backfilled=backfilled,
        )

    @staticmethod
    def _merge_discovered_and_missing(
        discovered: list[VideoInfo],
        missing_rows: list[Video],
    ) -> list[VideoInfo]:
        """YouTube tab order first, then older DB rows still missing captions."""
        seen = {item.video_id for item in discovered}
        merged = list(discovered)
        for row in missing_rows:
            if row.youtube_video_id in seen:
                continue
            seen.add(row.youtube_video_id)
            merged.append(
                VideoInfo(
                    video_id=row.youtube_video_id,
                    title=row.title,
                    published_at=row.published_at,
                    url=row.url,
                    content_type=row.content_type or "video",  # type: ignore[arg-type]
                    is_live=bool(row.is_live),
                )
            )
        return merged

    def _process_video(
        self,
        session,
        channel,
        video_info: VideoInfo,
        *,
        skip_existing: bool,
    ) -> bool:
        existing = self.repository.get_video_by_youtube_id(session, video_info.video_id)
        was_live_in_db = bool(existing.is_live) if existing is not None else False
        broadcast_ended = was_live_in_db and not video_info.is_live

        # Live broadcasts are never skipped — captions grow as the stream runs,
        # so we re-fetch on every sync while is_live is True, plus once more
        # after the broadcast ends.
        if existing is not None:
            should_skip = (
                skip_existing
                and not video_info.is_live
                and not broadcast_ended
                and self.repository.has_transcript(session, existing.id)
            )
            if should_skip:
                self.repository.upsert_video(session, channel, video_info)
                return False

        self._wait_before_fetch()

        try:
            transcript = self.transcript_client.fetch_transcript(video_info.video_id)
        except TranscriptFetchError:
            # Refresh metadata for videos we already know about, but do not
            # create new orphan rows when caption download fails (429, etc.).
            if existing is not None:
                self.repository.upsert_video(session, channel, video_info)
            raise

        self._fetched_this_run += 1
        video = self.repository.upsert_video(session, channel, video_info)
        if transcript is None:
            return False

        self.repository.upsert_transcript(session, video, transcript)
        return True

    def _wait_before_fetch(self) -> None:
        """Honor per-video delay plus any cooldown from a recent 429."""
        now = time.monotonic()
        wait_for = 0.0
        if self._cooldown_until > now:
            wait_for = self._cooldown_until - now
        elif self._fetched_this_run > 0 and self._caption_delay > 0:
            wait_for = self._caption_delay
        if wait_for > 0:
            time.sleep(wait_for)
