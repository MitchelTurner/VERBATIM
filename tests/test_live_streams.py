from unittest.mock import MagicMock, patch

import pytest

from ytdb.sync import SyncService
from ytdb.youtube.channel import ChannelInfo, VideoInfo


@pytest.fixture
def repository():
    from ytdb.db.repository import TranscriptRepository

    repo = TranscriptRepository("sqlite+pysqlite:///:memory:")
    repo.init_db()
    return repo


def test_list_content_dedupes_live_and_stream(repository):
    channel_client = MagicMock()
    channel_client.get_channel_info.return_value = ChannelInfo(
        "UCchannel", "Channel", "https://youtube.com/@channel"
    )
    channel_client.list_content.return_value = [
        VideoInfo("live1", "Live now", None, "https://youtube.com/watch?v=live1", "live", True),
        VideoInfo("stream1", "Past stream", None, "https://youtube.com/watch?v=stream1", "stream", False),
    ]

    transcript_client = MagicMock()
    transcript_client.fetch_transcript.return_value = MagicMock(
        language="English",
        language_code="en",
        is_auto_generated=True,
        content="hello",
    )

    service = SyncService(
        repository=repository,
        channel_client=channel_client,
        transcript_client=transcript_client,
    )

    result = service.sync_channel(
        "@channel",
        include_videos=False,
        include_streams=True,
        include_live=True,
    )

    assert result.videos_processed == 2
    assert result.transcripts_saved == 2
    channel_client.list_content.assert_called_once_with(
        "@channel",
        max_items=None,
        include_videos=False,
        include_streams=True,
        include_live=True,
    )


def test_live_stream_is_not_skipped_when_transcript_exists(repository):
    channel_client = MagicMock()
    channel_client.get_channel_info.return_value = ChannelInfo(
        "UCchannel", "Channel", "https://youtube.com/@channel"
    )
    channel_client.list_content.return_value = [
        VideoInfo("live1", "Live now", None, "https://youtube.com/watch?v=live1", "live", True),
    ]

    transcript_client = MagicMock()
    transcript_client.fetch_transcript.side_effect = [
        type("T", (), {
            "language": "English",
            "language_code": "en",
            "is_auto_generated": True,
            "content": "part one",
        })(),
        type("T", (), {
            "language": "English",
            "language_code": "en",
            "is_auto_generated": True,
            "content": "part one updated",
        })(),
    ]

    service = SyncService(
        repository=repository,
        channel_client=channel_client,
        transcript_client=transcript_client,
    )

    first = service.sync_channel("@channel", skip_existing=True)
    second = service.sync_channel("@channel", skip_existing=True)

    assert first.transcripts_saved == 1
    assert second.transcripts_saved == 1
    assert transcript_client.fetch_transcript.call_count == 2


def test_transcript_refetched_once_after_broadcast_ends(repository):
    """A transcript saved mid-broadcast only covers part of the stream. When
    the broadcast ends, it must be re-fetched once for the full content, then
    skipped on later syncs as usual."""
    channel_client = MagicMock()
    channel_client.get_channel_info.return_value = ChannelInfo(
        "UCchannel", "Channel", "https://youtube.com/@channel"
    )
    live_variant = VideoInfo(
        "meet1", "Council meeting", None, "https://youtube.com/watch?v=meet1", "live", True
    )
    ended_variant = VideoInfo(
        "meet1", "Council meeting", None, "https://youtube.com/watch?v=meet1", "stream", False
    )
    channel_client.list_content.side_effect = [
        [live_variant],
        [ended_variant],
        [ended_variant],
    ]

    def transcript(content):
        return MagicMock(
            language="English",
            language_code="en",
            is_auto_generated=True,
            content=content,
        )

    transcript_client = MagicMock()
    transcript_client.fetch_transcript.side_effect = [
        transcript("partial mid-meeting captions"),
        transcript("full meeting captions"),
    ]

    service = SyncService(
        repository=repository,
        channel_client=channel_client,
        transcript_client=transcript_client,
    )

    service.sync_channel("@channel", skip_existing=True)
    second = service.sync_channel("@channel", skip_existing=True)
    third = service.sync_channel("@channel", skip_existing=True)

    # Fetched while live, then exactly once more after the broadcast ended.
    assert transcript_client.fetch_transcript.call_count == 2
    assert second.transcripts_saved == 1
    assert third.transcripts_skipped == 1

    with repository.session() as session:
        rows = repository.search_transcripts(session)
        assert len(rows) == 1
        assert rows[0][0].content == "full meeting captions"


def test_max_items_does_not_starve_videos_tab():
    """A long streams backlog must not crowd new uploads out of the cap.

    City council channels stream every meeting, so the streams tab alone can
    fill ``max_items``. New recordings posted to the videos tab must still be
    picked up (regression test for new uploads never syncing).
    """
    from ytdb.youtube.channel import ChannelClient

    def stream(n):
        return VideoInfo(
            f"stream{n}", f"Old meeting {n}", None,
            f"https://youtube.com/watch?v=stream{n}", "stream", False,
        )

    def video(n):
        return VideoInfo(
            f"video{n}", f"New recording {n}", None,
            f"https://youtube.com/watch?v=video{n}", "video", False,
        )

    client = ChannelClient()
    streams = [stream(n) for n in range(4)]
    videos = [video(n) for n in range(2)]

    with patch.object(client, "get_current_live", return_value=None), patch.object(
        client, "_list_tab", side_effect=[streams, videos]
    ):
        results = client.list_content("@council", max_items=4)

    assert len(results) == 4
    result_ids = [item.video_id for item in results]
    # The newest videos-tab uploads must be present, interleaved with the
    # newest streams instead of being truncated away.
    assert "video0" in result_ids
    assert "video1" in result_ids
    assert result_ids[:2] == ["stream0", "video0"]


def test_live_broadcast_sorts_first_within_max_items():
    from ytdb.youtube.channel import ChannelClient

    live = VideoInfo(
        "live1", "Live now", None, "https://youtube.com/watch?v=live1", "live", True
    )
    streams = [
        VideoInfo(
            f"stream{n}", f"Meeting {n}", None,
            f"https://youtube.com/watch?v=stream{n}", "stream", False,
        )
        for n in range(3)
    ]

    client = ChannelClient()
    with patch.object(client, "get_current_live", return_value=live), patch.object(
        client, "_list_tab", side_effect=[streams, []]
    ):
        results = client.list_content("@council", max_items=2)

    assert [item.video_id for item in results] == ["live1", "stream0"]
    assert results[0].is_live is True


def test_channel_client_merge_prioritizes_live():
    from ytdb.youtube.channel import ChannelClient

    client = ChannelClient()
    same_id = VideoInfo(
        "abc123",
        "Title",
        None,
        "https://youtube.com/watch?v=abc123",
        "video",
        False,
    )
    live_id = VideoInfo(
        "abc123",
        "Title live",
        None,
        "https://youtube.com/watch?v=abc123",
        "live",
        True,
    )

    with patch.object(client, "get_current_live", return_value=None), patch.object(
        client, "_list_tab", side_effect=[[same_id], []]
    ):
        results = client.list_content(
            "@channel",
            include_videos=True,
            include_streams=False,
            include_live=False,
        )

    assert len(results) == 1
    assert results[0].content_type == "video"

    with patch.object(client, "get_current_live", return_value=live_id), patch.object(
        client, "_list_tab", side_effect=[[same_id], []]
    ):
        results = client.list_content(
            "@channel",
            include_videos=True,
            include_streams=False,
            include_live=True,
        )

    assert len(results) == 1
    assert results[0].is_live is True
    assert results[0].content_type == "live"
