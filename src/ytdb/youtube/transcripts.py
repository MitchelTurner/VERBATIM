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
too quickly. This client backs off and retries on 429s with a fresh proxy
session each attempt (so Webshare rotates to a new residential IP), and
SyncService spaces downloads with ``YOUTUBE_CAPTION_DELAY``.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import quote

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
from youtube_transcript_api.proxies import GenericProxyConfig, ProxyConfig, WebshareProxyConfig

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


class RotatingWebshareProxyConfig(ProxyConfig):
    """Webshare rotating residential proxy with a unique session per client.

    youtube-transcript-api's default Webshare config turns on urllib3 retries
    for HTTP 429 with no backoff, which burns the same proxy IP in milliseconds
    and surfaces as ``too many 429 error responses``. We disable those instant
    retries and instead rotate the Webshare session id ourselves between
    attempts so each retry leaves from a different residential IP.
    """

    def __init__(
        self,
        proxy_username: str,
        proxy_password: str,
        *,
        session_id: str | None = None,
        filter_ip_locations: list[str] | None = None,
        domain_name: str = WebshareProxyConfig.DEFAULT_DOMAIN_NAME,
        proxy_port: int = WebshareProxyConfig.DEFAULT_PORT,
    ) -> None:
        self.proxy_username = proxy_username
        self.proxy_password = proxy_password
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self._filter_ip_locations = filter_ip_locations or []
        self.domain_name = domain_name
        self.proxy_port = proxy_port

    def with_new_session(self) -> RotatingWebshareProxyConfig:
        return RotatingWebshareProxyConfig(
            proxy_username=self.proxy_username,
            proxy_password=self.proxy_password,
            session_id=uuid.uuid4().hex[:12],
            filter_ip_locations=list(self._filter_ip_locations),
            domain_name=self.domain_name,
            proxy_port=self.proxy_port,
        )

    @property
    def url(self) -> str:
        location_codes = "".join(
            f"-{location_code.upper()}" for location_code in self._filter_ip_locations
        )
        username = self.proxy_username
        for suffix in ("-rotate",):
            if username.endswith(suffix):
                username = username[: -len(suffix)]
        # session-<id> forces Webshare onto a distinct sticky IP; a new id
        # on each retry is how we rotate after a 429.
        user = f"{username}{location_codes}-session-{self.session_id}"
        password = quote(self.proxy_password, safe="")
        return f"http://{quote(user, safe='')}:{password}@{self.domain_name}:{self.proxy_port}/"

    def to_requests_dict(self) -> dict[str, str]:
        return {"http": self.url, "https": self.url}

    @property
    def prevent_keeping_connections_alive(self) -> bool:
        return True

    @property
    def retries_when_blocked(self) -> int:
        # 0 = no urllib3 instant 429 retries; we back off ourselves.
        return 0


def build_proxy_config(settings: Settings | None):
    """Build a youtube-transcript-api proxy config from app settings, if any."""
    if settings is None:
        return None

    if settings.webshare_proxy_username and settings.webshare_proxy_password:
        return RotatingWebshareProxyConfig(
            proxy_username=settings.webshare_proxy_username,
            proxy_password=settings.webshare_proxy_password,
        )

    if settings.youtube_http_proxy or settings.youtube_https_proxy:
        return GenericProxyConfig(
            http_url=settings.youtube_http_proxy,
            https_url=settings.youtube_https_proxy,
        )

    return None


def is_rate_limited(exc: BaseException) -> bool:
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


# Backwards-compatible alias used by older imports/tests.
_is_rate_limited = is_rate_limited


class TranscriptClient:
    def __init__(
        self,
        preferred_languages: list[str] | None = None,
        *,
        settings: Settings | None = None,
        proxy_config=None,
        max_retries: int | None = None,
        retry_base_delay: float = 5.0,
        sleep=time.sleep,
    ) -> None:
        self.preferred_languages = preferred_languages or ["en"]
        self._proxy_config = None
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

        self._proxy_config = proxy_config
        self._using_proxy = proxy_config is not None
        self._api = self._new_api()
        if self._using_proxy:
            logger.info("Caption downloads will use a configured proxy")

    def _new_api(self) -> YouTubeTranscriptApi:
        if self._proxy_config is None:
            return YouTubeTranscriptApi()
        return YouTubeTranscriptApi(proxy_config=self._proxy_config)

    def _rotate_proxy_session(self) -> None:
        """Open a fresh HTTP client, optionally on a new Webshare session/IP."""
        if isinstance(self._proxy_config, RotatingWebshareProxyConfig):
            self._proxy_config = self._proxy_config.with_new_session()
            logger.info(
                "Rotated Webshare proxy session to %s", self._proxy_config.session_id
            )
        self._api = self._new_api()

    def fetch_transcript(self, video_id: str) -> TranscriptData | None:
        last_error: Exception | None = None
        attempts = max(1, self._max_retries + 1)

        for attempt in range(attempts):
            try:
                return self._fetch_once(video_id)
            except _SKIP_ERRORS:
                return None
            except _BLOCK_ERRORS as exc:
                if is_rate_limited(exc) and attempt < attempts - 1:
                    last_error = exc
                    self._backoff(video_id, attempt, exc)
                    self._rotate_proxy_session()
                    continue
                raise TranscriptFetchError(self._block_message(video_id, exc)) from exc
            except _RETRYABLE_ERRORS as exc:
                if is_rate_limited(exc) and attempt < attempts - 1:
                    last_error = exc
                    self._backoff(video_id, attempt, exc)
                    self._rotate_proxy_session()
                    continue
                if is_rate_limited(exc):
                    raise TranscriptFetchError(
                        f"YouTube rate-limited caption download for {video_id} "
                        f"after {attempts} attempts (HTTP 429). Wait a few minutes "
                        f"and re-run; if this keeps happening set "
                        f"YOUTUBE_CAPTION_DELAY=8. Last error: {exc}"
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
        # 5s, 10s, 20s, 40s, 60s (capped) — long enough for Webshare to land
        # on a fresh IP and for YouTube's short-lived 429 to clear.
        delay = min(60.0, self._retry_base_delay * (2**attempt))
        logger.warning(
            "YouTube rate-limited %s (attempt %s/%s); sleeping %.1fs then rotating proxy — %s",
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

        # Prefer a plain language track over specialty variants (e.g. gemini ASR)
        # when falling back — those variants seem to 429 more aggressively.
        try:
            tracks = list(transcript_list)
        except TypeError:
            tracks = []
        if not tracks:
            return None

        preferred = [
            track
            for track in tracks
            if getattr(track, "language_code", None) in self.preferred_languages
            and "gemini" not in (getattr(track, "language", "") or "").lower()
        ]
        if preferred:
            return preferred[0]
        return tracks[0]

    @staticmethod
    def _format_transcript(fetched: FetchedTranscript) -> str:
        return "\n".join(
            snippet.text.strip() for snippet in fetched.snippets if snippet.text
        )
