"""YouTube channel and video discovery via yt-dlp.

We scrape channel tab playlists (/videos, /streams, /live) instead of using
the YouTube Data API, so no API key is required. yt-dlp handles handle/URL
normalization and returns metadata for each playlist entry.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import yt_dlp

ContentType = Literal["video", "stream", "live"]

CHANNEL_ID_PATTERN = re.compile(
    r"(?:youtube\.com/channel/|youtu\.be/channel/)([A-Za-z0-9_-]+)"
)


@dataclass(frozen=True)
class ChannelInfo:
    channel_id: str
    name: str | None
    url: str


@dataclass(frozen=True)
class VideoInfo:
    video_id: str
    title: str | None
    published_at: datetime | None
    url: str
    content_type: ContentType = "video"
    is_live: bool = False


def normalize_channel_url(account: str) -> str:
    """Turn a handle, channel ID, or partial URL into a canonical YouTube URL."""
    account = account.strip()
    if account.startswith("http://") or account.startswith("https://"):
        return account.rstrip("/")

    if account.startswith("UC") and len(account) == 24:
        return f"https://www.youtube.com/channel/{account}"

    if account.startswith("@"):
        return f"https://www.youtube.com/{account}"

    return f"https://www.youtube.com/@{account}"


class ChannelClient:
    def __init__(self) -> None:
        self._ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "skip_download": True,
        }

    def get_channel_info(self, account: str) -> ChannelInfo:
        url = normalize_channel_url(account)
        with yt_dlp.YoutubeDL(self._ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        channel_id = info.get("channel_id") or info.get("id")
        if not channel_id:
            raise ValueError(f"Could not resolve channel ID from: {account}")

        return ChannelInfo(
            channel_id=channel_id,
            name=info.get("channel") or info.get("uploader") or info.get("title"),
            url=info.get("channel_url") or info.get("webpage_url") or url,
        )

    def list_videos(self, account: str, max_videos: int | None = None) -> list[VideoInfo]:
        return self.list_content(
            account,
            max_items=max_videos,
            include_videos=True,
            include_streams=False,
            include_live=False,
        )

    def list_content(
        self,
        account: str,
        *,
        max_items: int | None = None,
        include_videos: bool = True,
        include_streams: bool = True,
        include_live: bool = True,
    ) -> list[VideoInfo]:
        """Collect videos from enabled channel tabs, de-duplicated by video ID.

        Live items are listed first. When the same video appears in multiple
        tabs, the live variant wins so ``is_live`` stays accurate.
        """
        base_url = normalize_channel_url(account)
        collected: dict[str, VideoInfo] = {}

        if include_live:
            live = self.get_current_live(account)
            if live is not None:
                collected[live.video_id] = live

        if include_streams:
            for item in self._list_tab(base_url, "streams", max_items):
                if item.video_id not in collected or item.is_live:
                    collected[item.video_id] = item

        if include_videos:
            for item in self._list_tab(base_url, "videos", max_items):
                existing = collected.get(item.video_id)
                if existing is None:
                    collected[item.video_id] = item
                elif item.is_live and not existing.is_live:
                    collected[item.video_id] = item

        results = list(collected.values())
        results.sort(
            key=lambda item: (
                0 if item.is_live else 1,
                0 if item.content_type == "stream" else 1,
                -(item.published_at.timestamp() if item.published_at else 0),
            ),
        )

        if max_items is not None:
            return results[:max_items]
        return results

    def get_current_live(self, account: str) -> VideoInfo | None:
        base_url = normalize_channel_url(account)
        live_url = f"{base_url}/live"
        opts = {
            **self._ydl_opts,
            "extract_flat": False,
        }

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(live_url, download=False)
        except Exception:
            return None

        if not info:
            return None

        if info.get("_type") == "playlist":
            entries = info.get("entries") or []
            info = next((entry for entry in entries if entry), None)
            if not info:
                return None

        if not self._is_live_broadcast(info):
            return None

        return self._info_to_video(info, content_type="live", is_live=True)

    def _list_tab(
        self,
        base_url: str,
        tab: str,
        max_items: int | None,
    ) -> list[VideoInfo]:
        tab_url = f"{base_url}/{tab}"
        opts = {
            **self._ydl_opts,
            "playlistend": max_items,
        }

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                playlist = ydl.extract_info(tab_url, download=False)
        except Exception:
            return []

        entries = playlist.get("entries") or []
        content_type: ContentType = "stream" if tab == "streams" else "video"
        videos: list[VideoInfo] = []

        for entry in entries:
            if not entry:
                continue
            video = self._entry_to_video(entry, content_type=content_type)
            if video:
                videos.append(video)

        return videos

    def _entry_to_video(
        self,
        entry: dict[str, Any],
        *,
        content_type: ContentType = "video",
    ) -> VideoInfo | None:
        video_id = entry.get("id")
        if not video_id or str(video_id).startswith("UC"):
            return None

        is_live = self._is_live_broadcast(entry)
        if is_live:
            content_type = "live"
        elif content_type == "video" and self._was_live_stream(entry):
            content_type = "stream"

        published_at = self._parse_timestamp(
            entry.get("timestamp") or entry.get("release_timestamp")
        )
        url = (
            entry.get("webpage_url")
            or entry.get("url")
            or f"https://www.youtube.com/watch?v={video_id}"
        )

        return VideoInfo(
            video_id=video_id,
            title=entry.get("title"),
            published_at=published_at,
            url=url,
            content_type=content_type,
            is_live=is_live,
        )

    def _info_to_video(
        self,
        info: dict[str, Any],
        *,
        content_type: ContentType,
        is_live: bool,
    ) -> VideoInfo:
        video_id = info.get("id")
        if not video_id:
            raise ValueError("Missing video id")

        return VideoInfo(
            video_id=video_id,
            title=info.get("title"),
            published_at=self._parse_timestamp(info.get("timestamp")),
            url=info.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}",
            content_type=content_type,
            is_live=is_live,
        )

    @staticmethod
    def _is_live_broadcast(entry: dict[str, Any]) -> bool:
        if entry.get("is_live"):
            return True
        return entry.get("live_status") == "is_live"

    @staticmethod
    def _was_live_stream(entry: dict[str, Any]) -> bool:
        if entry.get("was_live"):
            return True
        return entry.get("live_status") == "was_live"

    @staticmethod
    def _parse_timestamp(value: int | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromtimestamp(value, tz=timezone.utc)
