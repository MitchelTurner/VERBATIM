"""Command-line interface for ytdb.

Entry point: ``ytdb`` (see pyproject.toml [project.scripts]).

Typical usage:
    ytdb init-db
    ytdb sync @channel --max-videos 25
    ytdb serve --reload
"""
from __future__ import annotations

import logging

import click

from ytdb.config import get_settings
from ytdb.db.repository import TranscriptRepository
from ytdb.sync import SyncService

logger = logging.getLogger(__name__)


@click.command("init-db")
def init_db() -> None:
    """Create database tables."""
    settings = get_settings()
    repository = TranscriptRepository(settings.database_url)
    repository.init_db()
    click.echo("Database tables created.")


@click.command("list-channels")
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


@click.command("sync")
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
@click.option("--videos/--no-videos", default=True, help="Include regular uploaded videos.")
@click.option("--streams/--no-streams", default=True, help="Include past live streams.")
@click.option("--live/--no-live", default=True, help="Include the currently live broadcast.")
def sync(
    account: str,
    max_videos: int | None,
    languages: tuple[str, ...],
    force: bool,
    videos: bool,
    streams: bool,
    live: bool,
) -> None:
    """Sync transcripts for a YouTube account/channel.

    ACCOUNT can be a channel URL, @handle, channel ID (UC...), or handle without @.
    """
    service = SyncService(preferred_languages=list(languages))
    result = service.sync_channel(
        account,
        max_videos=max_videos,
        skip_existing=not force,
        include_videos=videos,
        include_streams=streams,
        include_live=live,
    )

    click.echo(f"Channel: {result.channel.name} ({result.channel.channel_id})")
    click.echo(f"Videos processed: {result.videos_processed}")
    click.echo(f"Transcripts saved: {result.transcripts_saved}")
    click.echo(f"Transcripts skipped: {result.transcripts_skipped}")
    if result.errors:
        click.echo(f"Errors: {result.errors}")


@click.command("serve")
@click.option("--host", default=None, help="Bind host (defaults to HOST env or 0.0.0.0).")
@click.option("--port", default=None, type=int, help="Bind port (defaults to PORT env or 8000).")
@click.option("--reload", is_flag=True, help="Enable auto-reload for development.")
def serve(host: str | None, port: int | None, reload: bool) -> None:
    """Start the web UI and API server."""
    import uvicorn

    settings = get_settings()
    bind_host = host or settings.host
    bind_port = port or settings.port

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )

    uvicorn.run(
        "ytdb.api.app:app",
        host=bind_host,
        port=bind_port,
        reload=reload,
        reload_dirs=["src/ytdb/api", "frontend/dist"] if reload else None,
    )


# Registered once here so importing cli.py multiple times (e.g. in tests)
# does not duplicate subcommands on the Click group.
ALL_COMMANDS = (init_db, list_channels, sync, serve)


@click.group(invoke_without_command=True, no_args_is_help=False)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """VERBATIM — fetch YouTube transcripts and store them in PostgreSQL."""
    if ctx.invoked_subcommand is None:
        click.echo("VERBATIM — no command specified.")
        click.echo()
        click.echo("Try one of:")
        click.echo("  python -m ytdb serve     Start the VERBATIM dashboard")
        click.echo("  python -m ytdb sync @channel")
        click.echo("  python -m ytdb init-db")
        click.echo()
        click.echo("Run with --help to see all commands.")
        ctx.exit(2)


for command in ALL_COMMANDS:
    if command.name not in cli.commands:
        cli.add_command(command)
