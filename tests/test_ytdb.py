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
    mock_get_settings.return_value = MagicMock(
        database_url="sqlite+pysqlite:///:memory:",
        youtube_caption_delay=0,
    )

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


@patch("ytdb.sync.get_settings")
def test_sync_does_not_create_video_when_captions_fail(mock_get_settings, repository):
    from ytdb.youtube.transcripts import TranscriptFetchError

    mock_get_settings.return_value = MagicMock(
        database_url="sqlite+pysqlite:///:memory:",
        youtube_caption_delay=0,
    )

    channel_client = MagicMock()
    channel_client.get_channel_info.return_value = ChannelInfo(
        "UCsyncchannel0000001", "Sync Channel", "https://youtube.com/@sync"
    )
    channel_client.list_content.return_value = [
        VideoInfo("newvid", "New", None, "https://youtube.com/watch?v=newvid"),
    ]
    transcript_client = MagicMock()
    transcript_client.fetch_transcript.side_effect = TranscriptFetchError(
        "YouTube rate-limited caption download for newvid after 6 attempts (HTTP 429)"
    )

    service = SyncService(
        repository=repository,
        channel_client=channel_client,
        transcript_client=transcript_client,
    )
    result = service.sync_channel("@sync", max_videos=1)

    assert result.errors == 1
    with repository.session() as session:
        assert repository.get_stats(session)["videos"] == 0
        assert repository.get_stats(session)["transcripts"] == 0


@patch("ytdb.sync.get_settings")
def test_sync_backfills_videos_missing_transcripts(mock_get_settings, repository):
    mock_get_settings.return_value = MagicMock(
        database_url="sqlite+pysqlite:///:memory:",
        youtube_caption_delay=0,
    )

    channel_info = ChannelInfo("UCchannel", "Council", "https://youtube.com/@council")
    with repository.session() as session:
        channel = repository.upsert_channel(session, channel_info)
        channel_id = channel.id
        repository.upsert_video(
            session,
            channel,
            VideoInfo("old1", "Old meeting", None, "https://youtube.com/watch?v=old1"),
        )
        session.commit()

    channel_client = MagicMock()
    channel_client.get_channel_info.return_value = channel_info
    # Newest tab page no longer includes old1 — without backfill it would be ignored.
    channel_client.list_content.return_value = [
        VideoInfo("new1", "New meeting", None, "https://youtube.com/watch?v=new1"),
    ]

    transcript_client = MagicMock()
    transcript_client.fetch_transcript.side_effect = [
        TranscriptData("English", "en", False, "new captions"),
        TranscriptData("English", "en", False, "old captions"),
    ]

    service = SyncService(
        repository=repository,
        channel_client=channel_client,
        transcript_client=transcript_client,
    )
    result = service.sync_channel("@council", max_videos=10, skip_existing=True)

    assert result.transcripts_saved == 2
    assert result.backfilled == 1
    assert transcript_client.fetch_transcript.call_count == 2
    fetched_ids = [call.args[0] for call in transcript_client.fetch_transcript.call_args_list]
    assert fetched_ids == ["new1", "old1"]

    with repository.session() as session:
        assert repository.get_stats(session)["transcripts"] == 2
        assert repository.list_videos_missing_transcripts(session, channel_id) == []


@patch("ytdb.sync.get_settings")
def test_sync_stops_early_after_repeated_rate_limits(mock_get_settings, repository):
    from ytdb.youtube.transcripts import TranscriptFetchError

    mock_get_settings.return_value = MagicMock(
        database_url="sqlite+pysqlite:///:memory:",
        youtube_caption_delay=0,
    )

    channel_client = MagicMock()
    channel_client.get_channel_info.return_value = ChannelInfo(
        "UCchannel", "Council", "https://youtube.com/@council"
    )
    channel_client.list_content.return_value = [
        VideoInfo(f"v{i}", f"Title {i}", None, f"https://youtube.com/watch?v=v{i}")
        for i in range(6)
    ]
    transcript_client = MagicMock()
    transcript_client.fetch_transcript.side_effect = TranscriptFetchError(
        "YouTube rate-limited caption download for v0 after 6 attempts (HTTP 429)"
    )

    service = SyncService(
        repository=repository,
        channel_client=channel_client,
        transcript_client=transcript_client,
    )
    result = service.sync_channel("@council", max_videos=6)

    # Two real attempts, then abort — remaining counted as errors without fetching.
    assert transcript_client.fetch_transcript.call_count == 2
    assert result.errors == 6
    assert any("Stopped early" in msg for msg in (result.error_messages or []))


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

    with patch("ytdb.youtube.transcripts.YouTubeTranscriptApi", return_value=FakeApi()):
        client = TranscriptClient()
        result = client.fetch_transcript("video-id")

    assert result is not None
    assert result.content == "Hello\nworld"


def test_transcript_client_raises_on_youtube_block():
    from youtube_transcript_api._errors import RequestBlocked
    from ytdb.youtube.transcripts import TranscriptFetchError

    class FakeApi:
        def list(self, video_id):
            raise RequestBlocked(video_id)

    with patch("ytdb.youtube.transcripts.YouTubeTranscriptApi", return_value=FakeApi()):
        client = TranscriptClient(max_retries=0)
        with pytest.raises(TranscriptFetchError) as exc_info:
            client.fetch_transcript("ccm7bUNZZDI")

    assert "ccm7bUNZZDI" in str(exc_info.value)
    assert "WEBSHARE_PROXY_USERNAME" in str(exc_info.value)


def test_transcript_client_retries_on_429_then_succeeds():
    from requests.exceptions import RetryError

    class FakeSnippet:
        def __init__(self, text):
            self.text = text

    class FakeFetched:
        snippets = [FakeSnippet("hello")]

    class FakeTranscript:
        language = "English"
        language_code = "en"
        is_generated = True

        def fetch(self):
            return FakeFetched()

    class FakeList:
        def find_transcript(self, languages):
            return FakeTranscript()

        def find_generated_transcript(self, languages):
            return FakeTranscript()

        def __iter__(self):
            return iter([FakeTranscript()])

    class FlakyApi:
        def __init__(self):
            self.calls = 0

        def list(self, video_id):
            self.calls += 1
            if self.calls == 1:
                raise RetryError(
                    "HTTPSConnectionPool(host='www.youtube.com', port=443): "
                    "Max retries exceeded with url: /api/timedtext "
                    "(Caused by ResponseError('too many 429 error responses'))"
                )
            return FakeList()

    sleeps: list[float] = []
    api = FlakyApi()
    with patch("ytdb.youtube.transcripts.YouTubeTranscriptApi", return_value=api):
        client = TranscriptClient(
            max_retries=3,
            retry_base_delay=5.0,
            sleep=sleeps.append,
        )
        result = client.fetch_transcript("cHzveGb-UPI")

    assert result is not None
    assert result.content == "hello"
    assert api.calls == 2
    assert sleeps == [5.0]


def test_transcript_client_gives_up_after_429_retries():
    from requests.exceptions import RetryError
    from ytdb.youtube.transcripts import TranscriptFetchError

    class Always429:
        def list(self, video_id):
            raise RetryError("too many 429 error responses")

    sleeps: list[float] = []
    with patch("ytdb.youtube.transcripts.YouTubeTranscriptApi", return_value=Always429()):
        client = TranscriptClient(
            max_retries=2,
            retry_base_delay=5.0,
            sleep=sleeps.append,
        )
        with pytest.raises(TranscriptFetchError) as exc_info:
            client.fetch_transcript("cHzveGb-UPI")

    assert "rate-limited" in str(exc_info.value).lower() or "429" in str(exc_info.value)
    assert sleeps == [5.0, 10.0]


@patch("ytdb.sync.get_settings")
def test_sync_spaces_caption_downloads(mock_get_settings, repository):
    mock_get_settings.return_value = MagicMock(
        database_url="sqlite+pysqlite:///:memory:",
        youtube_caption_delay=1.5,
        youtube_caption_max_retries=5,
    )

    channel_client = MagicMock()
    channel_client.get_channel_info.return_value = ChannelInfo(
        "UCsyncchannel0000001", "Sync Channel", "https://youtube.com/@sync"
    )
    channel_client.list_content.return_value = [
        VideoInfo("vid1", "One", None, "https://youtube.com/watch?v=vid1"),
        VideoInfo("vid2", "Two", None, "https://youtube.com/watch?v=vid2"),
    ]

    transcript_client = MagicMock()
    transcript_client.fetch_transcript.return_value = TranscriptData(
        "English", "en", False, "text"
    )

    service = SyncService(
        repository=repository,
        channel_client=channel_client,
        transcript_client=transcript_client,
    )
    service._caption_delay = 1.5

    with patch("ytdb.sync.time.sleep") as sleep_mock:
        result = service.sync_channel("@sync", max_videos=2)

    assert result.transcripts_saved == 2
    # Delay only between downloads, not before the first.
    sleep_mock.assert_called_once_with(1.5)


def test_build_proxy_config_prefers_webshare():
    from ytdb.config import Settings
    from ytdb.youtube.transcripts import RotatingWebshareProxyConfig, build_proxy_config

    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        host="0.0.0.0",
        port=8000,
        db_init_retries=1,
        db_init_retry_delay=0.1,
        webshare_proxy_username="user",
        webshare_proxy_password="pass",
        youtube_https_proxy="http://other:proxy@host:8080",
    )
    config = build_proxy_config(settings)
    assert isinstance(config, RotatingWebshareProxyConfig)
    assert config.retries_when_blocked == 0
    assert "-session-" in config.url
    rotated = config.with_new_session()
    assert rotated.session_id != config.session_id
    assert rotated.url != config.url


def test_build_proxy_config_generic():
    from ytdb.config import Settings
    from ytdb.youtube.transcripts import build_proxy_config
    from youtube_transcript_api.proxies import GenericProxyConfig

    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        host="0.0.0.0",
        port=8000,
        db_init_retries=1,
        db_init_retry_delay=0.1,
        youtube_https_proxy="http://user:pass@proxy.example:8080",
    )
    config = build_proxy_config(settings)
    assert isinstance(config, GenericProxyConfig)


def test_build_proxy_config_none_without_env():
    from ytdb.config import Settings
    from ytdb.youtube.transcripts import build_proxy_config

    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        host="0.0.0.0",
        port=8000,
        db_init_retries=1,
        db_init_retry_delay=0.1,
    )
    assert build_proxy_config(settings) is None
    assert build_proxy_config(None) is None


def test_transcript_client_uses_proxy_config():
    from youtube_transcript_api.proxies import GenericProxyConfig

    proxy = GenericProxyConfig(https_url="http://user:pass@proxy.example:8080")
    with patch("ytdb.youtube.transcripts.YouTubeTranscriptApi") as api_cls:
        client = TranscriptClient(proxy_config=proxy)
        api_cls.assert_called_once_with(proxy_config=proxy)
        assert client._using_proxy is True


def test_transcript_client_rotates_webshare_session_on_429():
    from requests.exceptions import RetryError
    from ytdb.youtube.transcripts import RotatingWebshareProxyConfig

    class FakeSnippet:
        def __init__(self, text):
            self.text = text

    class FakeFetched:
        snippets = [FakeSnippet("hello")]

    class FakeTranscript:
        language = "English"
        language_code = "en"
        is_generated = True

        def fetch(self):
            return FakeFetched()

    class FakeList:
        def find_transcript(self, languages):
            return FakeTranscript()

        def find_generated_transcript(self, languages):
            return FakeTranscript()

        def __iter__(self):
            return iter([FakeTranscript()])

    class FlakyApi:
        calls = 0

        def list(self, video_id):
            FlakyApi.calls += 1
            if FlakyApi.calls == 1:
                raise RetryError("too many 429 error responses")
            return FakeList()

    proxy = RotatingWebshareProxyConfig("user", "pass", session_id="aaaa")
    sleeps: list[float] = []
    with patch("ytdb.youtube.transcripts.YouTubeTranscriptApi", side_effect=lambda **kwargs: FlakyApi()):
        client = TranscriptClient(
            proxy_config=proxy,
            max_retries=2,
            retry_base_delay=5.0,
            sleep=sleeps.append,
        )
        first_session = client._proxy_config.session_id
        result = client.fetch_transcript("cHzveGb-UPI")

    assert result is not None
    assert result.content == "hello"
    assert sleeps == [5.0]
    assert client._proxy_config.session_id != first_session


@patch("ytdb.sync.get_settings")
def test_sync_records_block_errors_instead_of_silent_skip(mock_get_settings, repository):
    from ytdb.youtube.transcripts import TranscriptFetchError

    mock_get_settings.return_value = MagicMock(
        database_url="sqlite+pysqlite:///:memory:",
        youtube_caption_delay=0,
        youtube_caption_max_retries=5,
    )

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
