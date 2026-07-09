# VERBATIM

[![CI](https://github.com/TheMitchyBoy/VERBATIM/actions/workflows/ci.yml/badge.svg)](https://github.com/TheMitchyBoy/VERBATIM/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](#license)

**VERBATIM** syncs YouTube channel transcripts into PostgreSQL — with a web dashboard to schedule jobs, browse stored captions, and keep live streams up to date.

No YouTube Data API key is required. Channel discovery uses **yt-dlp**; caption download uses **youtube-transcript-api**.

---

## What it does

1. **Discover** videos, past live streams, and currently broadcasting live streams on a channel
2. **Download** captions (manual or auto-generated) in your preferred languages
3. **Store** channels, videos, and full transcript text in PostgreSQL
4. **Schedule** recurring sync jobs from the web UI or run one-off syncs from the CLI
5. **Browse** stored transcripts with full-text search in the dashboard

```mermaid
flowchart LR
    subgraph inputs [Inputs]
        CLI[ytdb CLI]
        UI[VERBATIM dashboard]
    end

    subgraph core [VERBATIM core]
        API[FastAPI + scheduler]
        Sync[SyncService]
        YTDLP[yt-dlp channel discovery]
        YTT[youtube-transcript-api]
    end

    DB[(PostgreSQL)]

    CLI --> Sync
    UI --> API --> Sync
    Sync --> YTDLP
    Sync --> YTT
    Sync --> DB
    API --> DB
```

---

## Features

| Area | Capabilities |
|------|--------------|
| **Channel input** | URL, `@handle`, or channel ID (`UC...`) |
| **Content types** | Regular uploads, past live streams, currently live broadcasts |
| **Languages** | Comma-separated preference list; first available match wins |
| **Scheduling** | Manual, 15m, 30m, hourly, 6h, 12h, daily, weekly |
| **Idempotent** | Safe to re-run; skips existing transcripts unless force-refresh is on |
| **Live streams** | Re-fetches captions on every sync while still broadcasting |
| **Web UI** | Stats dashboard, job management, transcript search & viewer |
| **CLI** | `init-db`, `sync`, `list-channels`, `serve` |

---

## Quick start (web UI)

### Docker (recommended)

```bash
docker compose up -d --build
```

Open **http://localhost:8000**

### Local development

```bash
pip install -e .
cp .env.example .env
ytdb init-db

# Terminal 1 — API + background scheduler
ytdb serve --reload

# Terminal 2 — frontend dev server (hot reload)
cd frontend && npm install && npm run dev
```

- API: http://localhost:8000
- Vite dev UI: http://localhost:5173 (proxies `/api` to port 8000)

> **Important:** Always run `ytdb serve` (or the Docker entrypoint) — not bare `python -m ytdb`.
> Without a subcommand the process prints help and exits.

---

## Web dashboard guide

### Stats bar

Shows live counts for transcripts, videos, channels, and sync jobs. Refreshes every 10 seconds.

### Sync jobs tab

| Control | What it does |
|---------|--------------|
| **Quick-start templates** | Pre-fill settings for daily uploads, live-only syncs, or one-off manual runs |
| **Channel** | YouTube URL, `@handle`, or `UC...` channel ID |
| **Sync frequency** | How often the background scheduler runs the job automatically |
| **Max items** | Cap how many videos/streams are checked per run |
| **Content types** | Toggle live broadcast, past streams, and regular uploads |
| **Enabled** | Turn scheduled runs on/off (manual "Run now" still works) |
| **Force refresh** | Re-download transcripts even if already stored |
| **Run now** | Trigger an immediate background sync |
| **History** | Expand to see past run results (saved/skipped/errors) |

### Transcripts tab

- Search by video title, channel name, or transcript text
- Filter by channel
- Click a result to read the full transcript
- Link opens the video on YouTube

---

## Quick start (CLI)

```bash
docker compose up -d          # start PostgreSQL
pip install -e .
cp .env.example .env
ytdb init-db

# Sync up to 10 recent videos from a channel
ytdb sync @mkbhd --max-videos 10

# Re-fetch existing transcripts
ytdb sync @mkbhd --force

# List channels already in the database
ytdb list-channels
```

### CLI reference

```
ytdb init-db
ytdb list-channels
ytdb sync ACCOUNT [--max-videos N] [--language CODE]... [--force]
                   [--videos/--no-videos] [--streams/--no-streams] [--live/--no-live]
ytdb serve [--host HOST] [--port PORT] [--reload]
```

`ACCOUNT` accepts:

- `https://www.youtube.com/@handle`
- `@handle` or `handle`
- `UCxxxxxxxxxxxxxxxxxxxxxx` (24-character channel ID)

---

## API reference

All endpoints are prefixed with `/api`.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness probe (`ready` indicates DB + scheduler are up) |
| `GET` | `/api/stats` | Dashboard counts |
| `GET` | `/api/channels` | Synced channels with transcript counts |
| `GET` | `/api/transcripts` | Search transcripts (`?search=`, `?channel_id=`, `?limit=`) |
| `GET` | `/api/transcripts/{id}` | Full transcript content |
| `GET` | `/api/frequencies` | Valid sync frequency options |
| `GET` | `/api/jobs` | List sync jobs |
| `POST` | `/api/jobs` | Create a sync job |
| `PATCH` | `/api/jobs/{id}` | Update a sync job |
| `DELETE` | `/api/jobs/{id}` | Delete a sync job |
| `POST` | `/api/jobs/{id}/run` | Trigger a background sync |
| `GET` | `/api/jobs/{id}/runs` | Run history for a job |

---

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://ytdb:ytdb@localhost:5432/ytdb` |
| `HOST` | API bind host | `0.0.0.0` |
| `PORT` | API bind port | `8000` |
| `DB_SSLMODE` | Override SSL mode (`require`, `disable`, etc.) | Auto-detected from hostname |
| `DB_INIT_RETRIES` | DB connection attempts on startup | `30` |
| `DB_INIT_RETRY_DELAY` | Seconds between startup retries | `2` |
| `YOUTUBE_API_KEY` | Optional; **not used** by core sync | — |
| `WEBSHARE_PROXY_USERNAME` | Webshare rotating residential proxy username | — |
| `WEBSHARE_PROXY_PASSWORD` | Webshare rotating residential proxy password | — |
| `YOUTUBE_HTTP_PROXY` | Generic HTTP(S)/SOCKS proxy URL for captions | — |
| `YOUTUBE_HTTPS_PROXY` | Generic HTTPS proxy URL for captions | — |
| `YOUTUBE_CAPTION_DELAY` | Seconds to wait between caption downloads | `5` |
| `YOUTUBE_CAPTION_MAX_RETRIES` | Extra attempts after HTTP 429 before failing a video | `5` |

---

## Database schema

| Table | Purpose |
|-------|---------|
| `channels` | YouTube channel metadata |
| `videos` | Videos and streams belonging to a channel |
| `transcripts` | Full caption text per video + language |
| `sync_jobs` | Scheduled sync configuration |
| `sync_runs` | Per-execution history and stats |

Example query:

```sql
SELECT c.name, v.title, t.language_code, LEFT(t.content, 120) AS preview
FROM transcripts t
JOIN videos v ON v.id = t.video_id
JOIN channels c ON c.id = v.channel_id
ORDER BY t.fetched_at DESC
LIMIT 20;
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for a deeper walkthrough of how the code is organized.

---

## Project structure

```
├── src/ytdb/
│   ├── cli.py              # Click CLI entry point
│   ├── sync.py             # Core sync orchestration
│   ├── scheduler.py        # Frequency → next-run calculations
│   ├── api/                # FastAPI app, routes, schemas
│   ├── db/                 # SQLAlchemy models, repository, migrations
│   ├── jobs/               # Background sync job runner
│   └── youtube/            # yt-dlp channel client + transcript fetcher
├── frontend/               # React + Vite dashboard
├── scripts/entrypoint.sh   # Docker / Railway start script
├── docker-compose.yml
├── railway.toml
└── tests/
```

---

## Development

```bash
pip install -e ".[dev]"
pytest
cd frontend && npm run build
```

---

## Deploy on Railway

1. [Railway](https://railway.com) → **New Project** → **Deploy from GitHub repo**
2. Add **PostgreSQL** → link `DATABASE_URL` = `${{Postgres.DATABASE_URL}}`
3. Railway reads `railway.toml` automatically:

| Setting | Value |
|---------|-------|
| Start command | `/app/scripts/entrypoint.sh` |
| Health check | `/health` |

4. Push to GitHub or click **Deploy**

Expected deploy logs:

```
Starting VERBATIM API on 0.0.0.0:<port>
Application process started; database init running in background
Database initialized and scheduler started
```

> Do **not** set `DB_SSLMODE` for Railway private Postgres URLs (`*.railway.internal`).
> `render.yaml` is for Render only; Railway uses `railway.toml`.

---

## Troubleshooting

### Container exits immediately

| Cause | Fix |
|-------|-----|
| Missing `DATABASE_URL` | Provision PostgreSQL and set the env var |
| Wrong start command | Use `ytdb serve` or `/app/scripts/entrypoint.sh` — not bare `python -m ytdb` |
| Wrong port | Cloud platforms set `PORT`; the entrypoint reads it automatically |
| Stale image | Rebuild: `docker compose up -d --build` |

### Application failed to respond (Railway / cloud)

1. `DATABASE_URL` references your Postgres service
2. Start command is `/app/scripts/entrypoint.sh`
3. Health check path is `/health`
4. Leave `DB_SSLMODE` unset for `*.railway.internal` URLs

### No transcripts saved

- The video may not have captions enabled
- Try a different language code
- Use `--force` or enable **Force refresh** to re-attempt failed videos

### YouTube blocked caption download (cloud IP)

YouTube blocks most cloud-provider IPs (Railway, Render, AWS, GCP, Azure). Channel discovery via yt-dlp can still work while caption downloads fail with `RequestBlocked` / `IpBlocked`.

**Fix:** route caption requests through a rotating **residential** proxy.

1. Create a [Webshare](https://www.webshare.io/) account and buy a **Residential** package (not “Proxy Server” or “Static Residential”)
2. Copy **Proxy Username** and **Proxy Password** from the [Webshare proxy settings](https://dashboard.webshare.io/proxy/settings)
3. In Railway → your service → **Variables**, set:
   - `WEBSHARE_PROXY_USERNAME`
   - `WEBSHARE_PROXY_PASSWORD`
4. Redeploy, then click **Run now** on the sync job

Alternatively set `YOUTUBE_HTTPS_PROXY` (and optionally `YOUTUBE_HTTP_PROXY`) to any `http://user:pass@host:port` residential proxy URL.

If History shows `too many 429 error responses`, YouTube is rate-limiting caption fetches. The app spaces downloads (`YOUTUBE_CAPTION_DELAY`, default 5s), retries with backoff **and a fresh Webshare proxy IP each attempt**, cools down after 429s, stops early after repeated limits, and backfills missing transcripts on the next run. Wait a few minutes, then **Run now** again; raise `YOUTUBE_CAPTION_DELAY` to `8` if 429s continue. Also confirm your Webshare plan is **Residential** (rotating), not Proxy Server / Static Residential.

Videos without transcripts are normal after a rate-limited run — the video row is saved (or was saved earlier) but captions failed. Re-running the job fills those gaps without needing Force refresh.

### Daily sync not running

- The job must have **Enabled** checked
- Frequency must be set (e.g. **Daily / 24h**), not **Manual only**
- The scheduler polls every minute; check run history for errors

---

## Limitations

- Only videos with available captions are stored
- YouTube blocks caption downloads from most cloud IPs — configure a residential proxy (see Troubleshooting)
- YouTube may rate-limit heavy usage — use `--max-videos` while testing
- Transcript availability depends on the uploader and YouTube caption settings

---

## License

MIT
