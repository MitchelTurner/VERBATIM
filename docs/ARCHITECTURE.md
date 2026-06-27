# Architecture

This document explains how the main pieces of **ytdb** fit together. Read this if you want to modify the sync logic, add API endpoints, or understand why certain design choices were made.

## High-level flow

```
User / Scheduler
      │
      ▼
  SyncService.sync_channel()
      │
      ├─► ChannelClient (yt-dlp)     → discover channel + list videos/streams/live
      ├─► TranscriptClient           → download captions for each video
      └─► TranscriptRepository       → upsert channel, video, transcript rows
```

The **web UI** and **CLI** are thin clients over the same `SyncService`. Scheduled jobs go through `jobs/runner.py`, which wraps `SyncService` with job/run bookkeeping.

## Python packages

### `ytdb.cli`

Click command group registered as the `ytdb` console script. Commands:

- `init-db` — create tables and run lightweight migrations
- `sync` — one-shot channel sync from the terminal
- `list-channels` — print stored channels
- `serve` — start uvicorn with the FastAPI app

The root group intentionally shows a short hint (not full help spam) when invoked without a subcommand.

### `ytdb.sync.SyncService`

Orchestrates a single channel sync:

1. Resolve channel metadata via `ChannelClient.get_channel_info()`
2. List candidate videos via `ChannelClient.list_content()` (videos / streams / live tabs)
3. For each item, upsert DB records and fetch captions

**Skip logic:** When `skip_existing=True` (the default), videos that already have a transcript are skipped — **except live broadcasts**, which are always re-fetched so captions stay current while the stream is active.

### `ytdb.youtube.channel.ChannelClient`

Uses **yt-dlp** in flat playlist mode to enumerate channel tabs:

| Tab URL suffix | Content |
|--------------|---------|
| `/live` | Currently broadcasting stream (full extract, not flat) |
| `/streams` | Past live streams |
| `/videos` | Regular uploads |

Results are de-duplicated by video ID. Live items are sorted first.

### `ytdb.youtube.transcripts.TranscriptClient`

Wraps **youtube-transcript-api**. Tries preferred language codes in order; returns the first transcript found (manual captions preferred over auto-generated when both exist for a language).

### `ytdb.db`

| Module | Role |
|--------|------|
| `models.py` | SQLAlchemy ORM tables |
| `repository.py` | Upserts, stats, transcript search |
| `job_repository.py` | CRUD for `sync_jobs` and `sync_runs` |
| `migrations.py` | Small additive schema patches after `create_all` |
| `engine.py` | Connection URL normalization and SSL mode detection |

All upsert methods are **idempotent** — safe to call repeatedly with the same YouTube IDs.

### `ytdb.jobs.runner`

- `run_sync_job(job_id)` — marks a job running, calls `SyncService`, records results
- `poll_due_jobs()` — called every minute by APScheduler; finds jobs where `next_run_at <= now`

A process-wide lock prevents two concurrent runs of the same job.

### `ytdb.api.app`

FastAPI application with:

- **Non-blocking startup** — DB init and scheduler start in a background asyncio task so `/health` responds immediately on Railway
- **Static file mount** — serves `frontend/dist` at `/` when the build exists
- **CORS** — open for local Vite dev proxy

### `ytdb.scheduler`

Maps frequency strings (`"24h"`, `"15m"`, etc.) to human labels and computes `next_run_at` timestamps. `"manual"` means no automatic scheduling.

## Frontend (`frontend/`)

React + Vite SPA served by FastAPI in production.

| Path | Purpose |
|------|---------|
| `src/App.tsx` | Tab layout, data fetching, toast notifications |
| `src/api.ts` | Typed fetch wrapper for `/api/*` |
| `src/components/JobForm.tsx` | Create/edit sync jobs with quick-start templates |
| `src/components/JobCard.tsx` | Job summary + expandable run history |
| `src/components/TranscriptPanel.tsx` | Search and read stored transcripts |
| `src/hooks/useToast.ts` | Auto-dismissing notification stack |

The dashboard polls job/stats data every 10 seconds so run status updates without a manual refresh.

## Deployment

`scripts/entrypoint.sh`:

1. Validates `DATABASE_URL` is set
2. Optionally waits for Postgres (`scripts/wait_for_db.py`)
3. Starts uvicorn on `$HOST:$PORT`

Railway sets `PORT` automatically. The Dockerfile builds the frontend into `frontend/dist` before the image is deployed.

## Adding a new feature — common touch points

| Change | Files to edit |
|--------|---------------|
| New sync option | `models.py`, `schemas.py`, `job_repository.py`, `SyncService`, `JobForm.tsx` |
| New API endpoint | `routes.py`, `schemas.py`, `api.ts`, frontend component |
| New content type from YouTube | `channel.py`, `VideoInfo`, `sync.py` skip logic |
| Schema change | `models.py`, `migrations.py`, add a test |
