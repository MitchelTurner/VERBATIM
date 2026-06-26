# YouTube Transcript to Database

Fetch transcripts from every video on a selected YouTube channel and store them in PostgreSQL.

## Features

- Accept a channel by URL, `@handle`, or channel ID (`UC...`)
- Discover all videos on the channel via `yt-dlp` (no YouTube API key required)
- Download captions with `youtube-transcript-api` (manual or auto-generated)
- Persist channels, videos, and transcripts in PostgreSQL
- Skip videos that already have transcripts unless `--force` is used
- Idempotent upserts — safe to re-run
- **Web UI** to configure channels, sync frequency, languages, and run jobs on demand

## Quick start (web UI)

### 1. Start PostgreSQL and the API

```bash
docker compose up -d
```

Open http://localhost:8000 to use the settings dashboard.

> **Note:** Run `python -m ytdb serve` to start the app — not bare `python -m ytdb`.
> If you see repeated help text in logs, your start command is missing a subcommand.

### 2. Or run locally for development

```bash
pip install -e .
cp .env.example .env
ytdb init-db

# Terminal 1: API + scheduler
ytdb serve --reload

# Terminal 2: frontend dev server
cd frontend && npm install && npm run dev
```

The Vite dev server runs at http://localhost:5173 and proxies API calls to port 8000.

## Quick start (CLI)

### 1. Start PostgreSQL

```bash
docker compose up -d
```

### 2. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

### 3. Initialize the database

```bash
ytdb init-db
```

### 4. Sync a channel

```bash
# By @handle
ytdb sync @mkbhd --max-videos 10

# By channel URL
ytdb sync "https://www.youtube.com/@mkbhd" --language en

# Re-fetch existing transcripts
ytdb sync @mkbhd --force
```

### 5. List synced channels

```bash
ytdb list-channels
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://ytdb:ytdb@localhost:5432/ytdb` |
| `YOUTUBE_API_KEY` | Optional; not required for core sync | — |

## Database schema

- **channels** — YouTube channel metadata
- **videos** — Videos belonging to a channel
- **transcripts** — Full transcript text per video and language
- **sync_jobs** — Scheduled sync configuration (channel, frequency, languages)
- **sync_runs** — History of each sync execution

Example query:

```sql
SELECT c.name, v.title, t.language_code, LEFT(t.content, 120) AS preview
FROM transcripts t
JOIN videos v ON v.id = t.video_id
JOIN channels c ON c.id = v.channel_id
ORDER BY t.fetched_at DESC
LIMIT 20;
```

## CLI reference

```
ytdb init-db
ytdb list-channels
ytdb sync ACCOUNT [--max-videos N] [--language CODE]... [--force]
ytdb serve [--host 0.0.0.0] [--port 8000] [--reload]
```

## Web UI settings

| Setting | Description |
|---------|-------------|
| Channel | YouTube URL, `@handle`, or channel ID |
| Sync frequency | Manual, 15m, 30m, hourly, 6h, 12h, daily, weekly |
| Max videos | Cap how many recent videos are checked each run |
| Languages | Preferred caption languages (comma-separated) |
| Enabled | Turn scheduled syncs on/off |
| Force refresh | Re-download transcripts even if already stored |


`ACCOUNT` can be:

- `https://www.youtube.com/@handle`
- `@handle` or `handle`
- `UCxxxxxxxxxxxxxxxxxxxxxx` (24-character channel ID)

## Development

```bash
pip install -e .
pip install pytest
pytest
```

## Limitations

- Only videos with available captions are stored (many channels disable captions on some uploads).
- YouTube may rate-limit heavy usage; use `--max-videos` while testing.
- Transcript availability depends on the uploader and YouTube's caption settings.

## Troubleshooting

### Container exits immediately

The API needs a **start command** and a **PostgreSQL `DATABASE_URL`**.

| Environment | Start command |
|-------------|---------------|
| Docker Compose | `docker compose up -d --build` (uses `scripts/entrypoint.sh` automatically) |
| Cloud (Render, Railway, etc.) | Set start command to `/app/scripts/entrypoint.sh` or `uvicorn ytdb.api.app:app --host 0.0.0.0 --port $PORT` |
| Local | `python -m ytdb serve` |

Common causes of `status: exited`:

1. **Missing `DATABASE_URL`** — provision PostgreSQL and set the env var
2. **Wrong start command** — do not use bare `python -m ytdb` (it exits immediately)
3. **Wrong port** — cloud platforms set `PORT`; the entrypoint reads it automatically
4. **Stale Docker image** — rebuild with `docker compose up -d --build`

### Application failed to respond (Render / cloud)

1. Set **`DATABASE_URL`** to your managed PostgreSQL connection string
2. Set **`DB_SSLMODE=require`** for Render, Railway, Neon, and similar hosts
3. Use start command **`/app/scripts/entrypoint.sh`** (Docker) or:
   ```
   uvicorn ytdb.api.app:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips '*'
   ```
4. Health check path: **`/health`** (returns 200 while the DB is still connecting)
5. On Render, deploy with the included `render.yaml` blueprint or link a Postgres database manually

Check deploy logs for `Starting ytdb API on 0.0.0.0:<port>`.

## License

MIT
