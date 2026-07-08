"""Download video captions via youtube-transcript-api.

Tries ``preferred_languages`` in order and returns the first match.
Returns None when captions are disabled or the video is unavailable.

YouTube bot / IP blocks raise ``TranscriptFetchError`` so the sync run
records a real error instead of silently counting the video as skipped.

Cloud hosts (Railway, Render, AWS, etc.) are routinely blocked by YouTube.
Pass a residential proxy via settings — Webshare rotating residential is
the path recommended by youtube-transcript-api — so caption requests leave
from a non-datacenter IP.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    AgeRestricted,
    IpBlocked,
    NoTranscriptFound,
    PoTokenRequired,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeRequestFailed,
)
from youtube_transcript_api._transcripts import FetchedTranscript
from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig

if TYPE_CHECKING:
    from ytdb.config import Settings

logger = logging.getLogger(__name__)

# Errors that mean "this video has no captions we can use" — skip, don't fail.
_SKIP_ERRORS = (TranscriptsDisabled, VideoUnavailable, NoTranscriptFound, AgeRestricted)

# Errors that mean YouTube is blocking us — fail loudly so the run history
# shows why new meetings aren't appearing.
_BLOCK_ERRORS = (RequestBlocked, IpBlocked, PoTokenRequired, YouTubeRequestFailed)

_PROXY_HINT = (
    "YouTube is blocking this host's IP (common on Railway/cloud). "
    "Set WEBSHARE_PROXY_USERNAME and WEBSHARE_PROXY_PASSWORD "
    "(or YOUTUBE_HTTPS_PROXY) to a residential proxy, then re-run the sync."
)


class TranscriptFetchError(RuntimeError):
    """Raised when YouTube blocks or otherwise prevents caption download."""


@dataclass(frozen=True)
class TranscriptData:
    language: str
    language_code: str
    is_auto_generated: bool
    content: str


def build_proxy_config(settings: Settings | None):
    """Build a youtube-transcript-api proxy config from app settings, if any."""
    if settings is None:
        return None

    if settings.webshare_proxy_username and settings.webshare_proxy_password:
        return WebshareProxyConfig(
            proxy_username=settings.webshare_proxy_username,
            proxy_password=settings.webshare_proxy_password,
        )

    if settings.youtube_http_proxy or settings.youtube_https_proxy:
        return GenericProxyConfig(
            http_url=settings.youtube_http_proxy,
            https_url=settings.youtube_https_proxy,
        )

    return None


class TranscriptClient:
    def __init__(
        self,
        preferred_languages: list[str] | None = None,
        *,
        settings: Settings | None = None,
        proxy_config=None,
    ) -> None:
        self.preferred_languages = preferred_languages or ["en"]
        self._using_proxy = False

        if proxy_config is None and settings is not None:
            proxy_config = build_proxy_config(settings)

        if proxy_config is not None:
            self._api = YouTubeTranscriptApi(proxy_config=proxy_config)
            self._using_proxy = True
            logger.info("Caption downloads will use a configured proxy")
        else:
            self._api = YouTubeTranscriptApi()

    def fetch_transcript(self, video_id: str) -> TranscriptData | None:
        try:
            transcript_list = self._api.list(video_id)
        except _SKIP_ERRORS:
            return None
        except _BLOCK_ERRORS as exc:
            raise TranscriptFetchError(self._block_message(video_id, exc)) from exc

        transcript = self._select_transcript(transcript_list)
        if transcript is None:
            return None

        try:
            fetched = transcript.fetch()
        except _SKIP_ERRORS:
            return None
        except _BLOCK_ERRORS as exc:
            raise TranscriptFetchError(self._block_message(video_id, exc)) from exc

        text = self._format_transcript(fetched)
        if not text.strip():
            return None

        return TranscriptData(
            language=transcript.language,
            language_code=transcript.language_code,
            is_auto_generated=transcript.is_generated,
            content=text,
        )

    def _block_message(self, video_id: str, exc: Exception) -> str:
        if self._using_proxy:
            return (
                f"YouTube blocked caption download for {video_id} even through "
                f"the configured proxy: {exc}"
            )
        return f"YouTube blocked caption download for {video_id}. {_PROXY_HINT}"

    def _select_transcript(self, transcript_list):
        try:
            return transcript_list.find_transcript(self.preferred_languages)
        except NoTranscriptFound:
            pass

        try:
            return transcript_list.find_generated_transcript(self.preferred_languages)
        except NoTranscriptFound:
            pass

        try:
            return next(iter(transcript_list))
        except StopIteration:
            return None

    @staticmethod
    def _format_transcript(fetched: FetchedTranscript) -> str:
        return "\n".join(
            snippet.text.strip() for snippet in fetched.snippets if snippet.text
        )
