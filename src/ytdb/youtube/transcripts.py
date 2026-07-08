"""Download video captions via youtube-transcript-api.

Tries ``preferred_languages`` in order and returns the first match.
Returns None when captions are disabled or the video is unavailable.

YouTube bot / IP blocks raise ``TranscriptFetchError`` so the sync run
records a real error instead of silently counting the video as skipped.

Cloud hosts (Railway, Render, AWS, etc.) are routinely blocked by YouTube.
Pass a residential proxy via settings — Webshare rotating residential is
the path recommended by youtube-transcript-api — so caption requests leave
from a non-datacenter IP.

Even with a proxy, YouTube rate-limits (HTTP 429) when captions are fetched
too quickly. This client backs off and retries on 429s, and SyncService
spaces downloads with ``YOUTUBE_CAPTION_DELAY``.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import RetryError
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

# Transient transport failures that often wrap HTTP 429 from YouTube.
_RETRYABLE_ERRORS = (RetryError, RequestsConnectionError, YouTubeRequestFailed)

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
            retries_when_blocked=10,
        )

    if settings.youtube_http_proxy or settings.youtube_https_proxy:
        return GenericProxyConfig(
            http_url=settings.youtube_http_proxy,
            https_url=settings.youtube_https_proxy,
        )

    return None


def _is_rate_limited(exc: BaseException) -> bool:
    """True when the failure looks like YouTube HTTP 429 / retry exhaustion."""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        text = str(current).lower()
        if "429" in text or "too many" in text or "rate limit" in text:
            return True
        if isinstance(current, RetryError):
            return True
        current = current.__cause__ or current.__context__
    return False


class TranscriptClient:
    def __init__(
        self,
        preferred_languages: list[str] | None = None,
        *,
        settings: Settings | None = None,
        proxy_config=None,
        max_retries: int | None = None,
        retry_base_delay: float = 2.0,
        sleep=time.sleep,
    ) -> None:
        self.preferred_languages = preferred_languages or ["en"]
        self._using_proxy = False
        self._max_retries = (
            max_retries
            if max_retries is not None
            else (settings.youtube_caption_max_retries if settings else 5)
        )
        self._retry_base_delay = retry_base_delay
        self._sleep = sleep

        if proxy_config is None and settings is not None:
            proxy_config = build_proxy_config(settings)

        if proxy_config is not None:
            self._api = YouTubeTranscriptApi(proxy_config=proxy_config)
            self._using_proxy = True
            logger.info("Caption downloads will use a configured proxy")
        else:
            self._api = YouTubeTranscriptApi()

    def fetch_transcript(self, video_id: str) -> TranscriptData | None:
        last_error: Exception | None = None
        attempts = max(1, self._max_retries + 1)

        for attempt in range(attempts):
            try:
                return self._fetch_once(video_id)
            except _SKIP_ERRORS:
                return None
            except _BLOCK_ERRORS as exc:
                if _is_rate_limited(exc) and attempt < attempts - 1:
                    last_error = exc
                    self._backoff(video_id, attempt, exc)
                    continue
                raise TranscriptFetchError(self._block_message(video_id, exc)) from exc
            except _RETRYABLE_ERRORS as exc:
                if _is_rate_limited(exc) and attempt < attempts - 1:
                    last_error = exc
                    self._backoff(video_id, attempt, exc)
                    continue
                if _is_rate_limited(exc):
                    raise TranscriptFetchError(
                        f"YouTube rate-limited caption download for {video_id} "
                        f"after {attempts} attempts (HTTP 429). Wait a minute and "
                        f"re-run, or raise YOUTUBE_CAPTION_DELAY. Last error: {exc}"
                    ) from exc
                raise TranscriptFetchError(
                    f"Caption download failed for {video_id}: {exc}"
                ) from exc

        if last_error is not None:
            raise TranscriptFetchError(
                f"YouTube rate-limited caption download for {video_id}: {last_error}"
            ) from last_error
        return None

    def _fetch_once(self, video_id: str) -> TranscriptData | None:
        transcript_list = self._api.list(video_id)
        transcript = self._select_transcript(transcript_list)
        if transcript is None:
            return None

        fetched = transcript.fetch()
        text = self._format_transcript(fetched)
        if not text.strip():
            return None

        return TranscriptData(
            language=transcript.language,
            language_code=transcript.language_code,
            is_auto_generated=transcript.is_generated,
            content=text,
        )

    def _backoff(self, video_id: str, attempt: int, exc: Exception) -> None:
        delay = self._retry_base_delay * (2**attempt)
        logger.warning(
            "YouTube rate-limited %s (attempt %s/%s); sleeping %.1fs — %s",
            video_id,
            attempt + 1,
            self._max_retries + 1,
            delay,
            exc,
        )
        self._sleep(delay)

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
