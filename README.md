# socauto

socauto is a single-host, operator-controlled service that republishes one supported X video
to a connected TikTok account. An API queues durable jobs; a separate worker downloads media,
renders the caption, and publishes it.

The supported flow is X status URL -> one H.264/AAC MP4 -> TikTok. Multi-video X posts are not
supported. Operators can import TikTok sessions, manage reusable caption templates, select an
explicit per-job visibility, review durable job state, retry safely, and cancel eligible work.

## Status

Version 0.1.0 is release-ready for its documented single-host scope. The private (`Only you`)
live publication path was manually confirmed on TikTok on 2026-09-08. This does not validate
public visibility. `posted` means TikTok acknowledged a publication request; it does not itself
confirm that a post is visible. Operator confirmation established the private live path.

## Stack and prerequisites

- Python `>=3.14,<3.15`, managed with [uv](https://docs.astral.sh/uv/)
- FastAPI, Uvicorn, SQLModel, SQLite, and Alembic
- yt-dlp and FFmpeg for X media
- Bun `>=1.3.0`, Playwright Core, and system Chromium or Chrome for TikTok signing
- Svelte/Vite local operator panel in [`web/`](web/)

Install `uv`, Bun 1.3+, FFmpeg, and Chromium or Google Chrome before setup.

## Quick setup

Run these commands from the checkout root:

```bash
uv sync
bun install
bun install --cwd web
cp .env.example .env
uv run alembic upgrade head
```

Review [configuration and operations](docs/operations.md) before using real credentials.

## Run in production

Docker Compose is the supported self-contained production artifact. It builds the API, migration,
worker, signer, Chromium, FFmpeg, and panel, then keeps both host ports loopback-only:

```bash
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f
```

Open the panel at `http://127.0.0.1:8080`; the direct API is at `http://127.0.0.1:8000`. Compose
applies migrations before starting the API and worker. The named `socauto-data` volume holds SQLite,
sessions, browser-profile data, and retained media. See [operations](docs/operations.md) for
backup, upgrade, restricted-X cookie mounts, and native-process deployment.

For a native deployment, run the API and worker as separate supervised processes from the same
checkout and with the same environment and `SOCAUTO_DATA_DIR`:

```bash
uv run uvicorn socauto.app:app --host 127.0.0.1 --port 8000
```

```bash
uv run python -m socauto.worker
```

Apply migrations before starting either process after installation or an upgrade:

```bash
uv run alembic upgrade head
```

`/health` reports only that the API process responds. It does not establish database, worker,
TikTok, or account-session health.

The API and panel have no authentication or tenant isolation. Bind the API to loopback, or put
it behind an authenticated private gateway. Do not expose either directly to the internet:
callers can import credentials and queue publications.

## Local operator panel

With the API running locally, start the panel in another terminal:

```bash
bun run --cwd web dev
```

Use these commands for local validation:

```bash
bun run --cwd web check
bun run --cwd web build
bun run --cwd web preview
```

Vite preview is not a production server. Serve `web/dist/` with externally managed static
hosting and proxy `/v1` and `/health` to the private API. The development and preview servers
bind to `127.0.0.1` and use that proxy automatically.

## First job

Import an authenticated TikTok cookie export through the panel or `POST /v1/accounts/tiktok/import`.
Then submit a job using the returned account ID:

```json
{
  "source_url": "https://x.com/example/status/123456789",
  "destination_account_id": "00000000-0000-0000-0000-000000000000",
  "caption_mode": "source",
  "visibility": "private"
}
```

Jobs default to `private`; `public` must be selected explicitly. Caption modes are `source`,
`override`, `saved_template`, and `custom_template`. Templates support the literal
`{{caption}}` placeholder and are snapshotted when a job is queued, so later template edits do
not alter queued jobs or retries.

The API returns `202 Accepted` and a job snapshot. The worker performs the work asynchronously.
For endpoint details, request contracts, retry handling, and job states, see
[the API guide](docs/api.md) or the live schema at `/docs`.

## Documentation

- [API guide](docs/api.md), accounts, templates, jobs, states, and retry behavior
- [Operations guide](docs/operations.md), topology, configuration, backups, upgrades, and security
- [Development guide](docs/development.md), local setup and offline verification
- [Roadmap](ROADMAP.md), current status, open work, and known risks
- [Changelog](CHANGELOG.md), release history

## Security and platform limits

- TikTok uses undocumented web endpoints and browser-generated signatures. Sessions can expire,
  endpoints can change, and automated activity can face restrictions.
- Treat cookie exports, `.env`, the runtime directory, and browser profiles as secrets. Never
  commit them, paste them into logs, or use an online cookie converter.
- Account import verifies TikTok identity live before storage; it does not prove publication
  permission. Restricted X posts require an operator-provided Netscape cookie file.
- TikTok acknowledgements can be ambiguous. If a job has `upload_outcome_unknown`, inspect the
  TikTok account before retrying and explicitly acknowledge duplicate risk only when appropriate.
- Successful media is cleaned up only after durable acknowledgement. Failed, cancelled, and
  interrupted attempts can remain until an operator removes them. No automatic retention policy
  exists.
- SQLite and the runtime layout support one host. One worker is the supported default.

## Packaging note

Docker Compose is the supported self-contained artifact. The Python wheel contains only
`src/socauto`; it excludes the Bun signer dependencies, `signer/`, web assets, and Chromium. A
wheel-only deployment therefore still requires those runtime assets to be supplied separately.
