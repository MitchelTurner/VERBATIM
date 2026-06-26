from __future__ import annotations

import logging

import click

from ytdb.config import get_settings
from ytdb.db.repository import TranscriptRepository
from ytdb.sync import SyncService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@click.group()
def cli() -> None:
    """Fetch YouTube transcripts from a channel and store them in PostgreSQL."""


@cli.command("init-db")
def init_db() -> None:
    """Create database tables."""
    settings = get_settings()
    repository = TranscriptRepository(settings.database_url)
    repository.init_db()
    click.echo("Database tables created.")


@cli.command("list-channels")
def list_channels() -> None:
    """List channels stored in the database."""
    settings = get_settings()
    repository = TranscriptRepository(settings.database_url)
    repository.init_db()

    with repository.session() as session:
        channels = repository.list_channels(session)

    if not channels:
        click.echo("No channels found.")
        return

    for channel in channels:
        with repository.session() as session:
            transcript_count = repository.count_transcripts_for_channel(session, channel.id)
        click.echo(
            f"{channel.name or channel.youtube_channel_id} "
            f"({channel.youtube_channel_id}) - {transcript_count} transcripts"
        )


@cli.command("sync")
@click.argument("account")
@click.option(
    "--max-videos",
    type=int,
    default=None,
    help="Maximum number of videos to process from the channel.",
)
@click.option(
    "--language",
    "languages",
    multiple=True,
    default=["en"],
    show_default=True,
    help="Preferred transcript language codes (repeatable).",
)
@click.option(
    "--force",
    is_flag=True,
    help="Re-fetch transcripts even if they already exist in the database.",
)
def sync(account: str, max_videos: int | None, languages: tuple[str, ...], force: bool) -> None:
    """Sync transcripts for a YouTube account/channel.

    ACCOUNT can be a channel URL, @handle, channel ID (UC...), or handle without @.
    """
    service = SyncService(preferred_languages=list(languages))
    result = service.sync_channel(
        account,
        max_videos=max_videos,
        skip_existing=not force,
    )

    click.echo(f"Channel: {result.channel.name} ({result.channel.channel_id})")
    click.echo(f"Videos processed: {result.videos_processed}")
    click.echo(f"Transcripts saved: {result.transcripts_saved}")
    click.echo(f"Transcripts skipped: {result.transcripts_skipped}")
    if result.errors:
        click.echo(f"Errors: {result.errors}")


@cli.command("serve")
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=8000, show_default=True, type=int)
@click.option("--reload", is_flag=True, help="Enable auto-reload for development.")
def serve(host: str, port: int, reload: bool) -> None:
    """Start the web UI and API server."""
    import uvicorn

    uvicorn.run(
        "ytdb.api.app:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    cli()
