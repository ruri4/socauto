# socauto

API-first automation for downloading media from supported sources and publishing it to
connected social accounts. The MVP accepts X/Twitter links and publishes one video to TikTok.

TikTok publishing uses undocumented web endpoints and browser-generated request signatures.
Those interfaces can change without notice, sessions can expire, and automated activity can
trigger platform restrictions. Only republish media you have permission to use.

## Stack

- Python 3.12, managed by `uv`
- FastAPI, Uvicorn, SQLModel, SQLite, and Alembic
- `yt-dlp` and FFmpeg for X media
- Requests for TikTok transfer and publishing
- Selenium for interactive TikTok login
- Bun, Playwright Core, and system Chromium for TikTok request signing

There is no frontend or official-platform API dependency.

## Prerequisites

- `uv`
- Bun 1.3 or newer
- FFmpeg
- Chromium or Google Chrome available on the host

## Setup

```bash
uv sync
bun install
cp .env.example .env
uv run alembic upgrade head
```

Run the development API:

```bash
uv run uvicorn socauto.app:app --reload
```

The OpenAPI document is available at `/openapi.json`, and interactive API documentation is at
`/docs`. Runtime state is stored under `SOCAUTO_DATA_DIR` and is ignored by Git.

## Development

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```
