from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from ytdb.db.models import Base, Channel, Transcript, Video
from ytdb.db.repository import TranscriptRepository
from ytdb.sync import SyncService
from ytdb.youtube.channel import ChannelClient, ChannelInfo, VideoInfo, normalize_channel_url
from ytdb.youtube.transcripts import TranscriptClient, TranscriptData


@pytest.fixture
def repository():
    repo = TranscriptRepository("sqlite+pysqlite:///:memory:")
    repo.init_db()
    return repo


def test_normalize_channel_url_variants():
    assert normalize_channel_url("@mkbhd") == "https://www.youtube.com/@mkbhd"
    assert normalize_channel_url("mkbhd") == "https://www.youtube.com/@mkbhd"
    assert (
        normalize_channel_url("UC1234567890123456789012")
        == "https://www.youtube.com/channel/UC1234567890123456789012"
    )
    assert (
        normalize_channel_url("https://www.youtube.com/@test")
        == "https://www.youtube.com/@test"
    )


def test_repository_upsert_channel_and_video(repository):
    channel_info = ChannelInfo(
        channel_id="UCtestchannel00000001",
        name="Test Channel",
        url="https://www.youtube.com/@test",
    )
    video_info = VideoInfo(
        video_id="abc123xyz00",
        title="Sample Video",
        published_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        url="https://www.youtube.com/watch?v=abc123xyz00",
    )

    with repository.session() as session:
        channel = repository.upsert_channel(session, channel_info)
        video = repository.upsert_video(session, channel, video_info)
        session.commit()

        assert channel.id is not None
        assert video.channel_id == channel.id

        channel_again = repository.upsert_channel(session, channel_info)
        video_again = repository.upsert_video(session, channel_again, video_info)
        session.commit()

        assert channel_again.id == channel.id
        assert video_again.id == video.id


def test_repository_upsert_transcript(repository):
    channel_info = ChannelInfo("UCtestchannel00000001", "Test", "https://youtube.com/@test")
    video_info = VideoInfo("vid001", "Title", None, "https://youtube.com/watch?v=vid001")
    transcript = TranscriptData("English", "en", False, "Hello world")

    with repository.session() as session:
        channel = repository.upsert_channel(session, channel_info)
        video = repository.upsert_video(session, channel, video_info)
        saved = repository.upsert_transcript(session, video, transcript)
        session.commit()

        assert saved.language_code == "en"
        assert saved.content == "Hello world"

        updated = TranscriptData("English", "en", False, "Updated text")
        saved_again = repository.upsert_transcript(session, video, updated)
        session.commit()

        assert saved_again.id == saved.id
        assert saved_again.content == "Updated text"


@patch("ytdb.sync.get_settings")
def test_sync_service_processes_videos(mock_get_settings, repository):
    mock_get_settings.return_value = MagicMock(database_url="sqlite+pysqlite:///:memory:")

    channel_client = MagicMock()
    channel_client.get_channel_info.return_value = ChannelInfo(
        "UCsyncchannel0000001", "Sync Channel", "https://youtube.com/@sync"
    )
    channel_client.list_content.return_value = [
        VideoInfo("vid100", "One", None, "https://youtube.com/watch?v=vid100"),
        VideoInfo("vid200", "Two", None, "https://youtube.com/watch?v=vid200"),
    ]

    transcript_client = MagicMock()
    transcript_client.fetch_transcript.side_effect = [
        TranscriptData("English", "en", False, "First transcript"),
        None,
    ]

    service = SyncService(
        repository=repository,
        channel_client=channel_client,
        transcript_client=transcript_client,
    )

    result = service.sync_channel("@sync", max_videos=2)

    assert result.videos_processed == 2
    assert result.transcripts_saved == 1
    assert result.transcripts_skipped == 1
    assert result.errors == 0

    with repository.session() as session:
        channels = repository.list_channels(session)
        assert len(channels) == 1
        assert repository.count_transcripts_for_channel(session, channels[0].id) == 1


def test_transcript_client_formats_text():
    class FakeSnippet:
        def __init__(self, text):
            self.text = text

    class FakeFetched:
        snippets = [FakeSnippet("Hello"), FakeSnippet("world")]

    class FakeTranscript:
        language = "English"
        language_code = "en"
        is_generated = False

        def fetch(self):
            return FakeFetched()

    class FakeList:
        def find_transcript(self, languages):
            return FakeTranscript()

        def __iter__(self):
            return iter([])

    class FakeApi:
        def list(self, video_id):
            return FakeList()

    with patch.object(TranscriptClient, "__init__", lambda self, preferred_languages=None: None):
        client = TranscriptClient()
        client.preferred_languages = ["en"]
        client._api = FakeApi()
        result = client.fetch_transcript("video-id")

    assert result is not None
    assert result.content == "Hello\nworld"


def test_transcript_client_raises_on_youtube_block():
    from youtube_transcript_api._errors import RequestBlocked
    from ytdb.youtube.transcripts import TranscriptFetchError

    class FakeApi:
        def list(self, video_id):
            raise RequestBlocked(video_id)

    with patch.object(TranscriptClient, "__init__", lambda self, preferred_languages=None: None):
        client = TranscriptClient()
        client.preferred_languages = ["en"]
        client._api = FakeApi()
        with pytest.raises(TranscriptFetchError) as exc_info:
            client.fetch_transcript("ccm7bUNZZDI")

    assert "ccm7bUNZZDI" in str(exc_info.value)


@patch("ytdb.sync.get_settings")
def test_sync_records_block_errors_instead_of_silent_skip(mock_get_settings, repository):
    from ytdb.youtube.transcripts import TranscriptFetchError

    mock_get_settings.return_value = MagicMock(database_url="sqlite+pysqlite:///:memory:")

    channel_client = MagicMock()
    channel_client.get_channel_info.return_value = ChannelInfo(
        "UCsyncchannel0000001", "Sync Channel", "https://youtube.com/@sync"
    )
    channel_client.list_content.return_value = [
        VideoInfo(
            "ccm7bUNZZDI",
            "Public Safety & Criminal Justice on July 2, 2026",
            None,
            "https://youtube.com/watch?v=ccm7bUNZZDI",
        ),
    ]

    transcript_client = MagicMock()
    transcript_client.fetch_transcript.side_effect = TranscriptFetchError(
        "YouTube blocked caption download for ccm7bUNZZDI"
    )

    service = SyncService(
        repository=repository,
        channel_client=channel_client,
        transcript_client=transcript_client,
    )

    result = service.sync_channel("@sync", max_videos=1)

    assert result.videos_processed == 1
    assert result.transcripts_saved == 0
    assert result.errors == 1
    assert result.error_messages
    assert "ccm7bUNZZDI" in result.error_messages[0]
