"""Download video captions via youtube-transcript-api.

Tries ``preferred_languages`` in order and returns the first match.
Returns None when captions are disabled or the video is unavailable.

YouTube bot / IP blocks raise ``TranscriptFetchError`` so the sync run
records a real error instead of silently counting the video as skipped.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

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

logger = logging.getLogger(__name__)

# Errors that mean "this video has no captions we can use" — skip, don't fail.
_SKIP_ERRORS = (TranscriptsDisabled, VideoUnavailable, NoTranscriptFound, AgeRestricted)

# Errors that mean YouTube is blocking us — fail loudly so the run history
# shows why new meetings aren't appearing.
_BLOCK_ERRORS = (RequestBlocked, IpBlocked, PoTokenRequired, YouTubeRequestFailed)


class TranscriptFetchError(RuntimeError):
    """Raised when YouTube blocks or otherwise prevents caption download."""


@dataclass(frozen=True)
class TranscriptData:
    language: str
    language_code: str
    is_auto_generated: bool
    content: str


class TranscriptClient:
    def __init__(self, preferred_languages: list[str] | None = None) -> None:
        self.preferred_languages = preferred_languages or ["en"]
        self._api = YouTubeTranscriptApi()

    def fetch_transcript(self, video_id: str) -> TranscriptData | None:
        try:
            transcript_list = self._api.list(video_id)
        except _SKIP_ERRORS:
            return None
        except _BLOCK_ERRORS as exc:
            raise TranscriptFetchError(
                f"YouTube blocked caption download for {video_id}: {exc}"
            ) from exc

        transcript = self._select_transcript(transcript_list)
        if transcript is None:
            return None

        try:
            fetched = transcript.fetch()
        except _SKIP_ERRORS:
            return None
        except _BLOCK_ERRORS as exc:
            raise TranscriptFetchError(
                f"YouTube blocked caption download for {video_id}: {exc}"
            ) from exc

        text = self._format_transcript(fetched)
        if not text.strip():
            return None

        return TranscriptData(
            language=transcript.language,
            language_code=transcript.language_code,
            is_auto_generated=transcript.is_generated,
            content=text,
        )

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
