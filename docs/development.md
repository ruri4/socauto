# Development guide

## Setup

Docker Compose is the self-contained production artifact. Use the native setup below for
development and offline verification; see [operations.md](operations.md) for Compose lifecycle,
backups, and the loopback-only production topology.

Install Python `>=3.14,<3.15`, uv, Bun `>=1.3.0`, FFmpeg, and Chromium or Google Chrome. From the
checkout root:

```bash
uv sync
bun install
bun install --cwd web
cp .env.example .env
uv run alembic upgrade head
```

Start the API, worker, and local panel as needed:

```bash
uv run uvicorn socauto.app:app --host 127.0.0.1 --port 8000
uv run python -m socauto.worker
bun run --cwd web dev
```

The API is at `http://127.0.0.1:8000`; OpenAPI is available at `/docs` and `/openapi.json`.

## Repository layout

| Path | Ownership |
| --- | --- |
| `src/socauto/app.py` | FastAPI application and lifecycle |
| `src/socauto/api/` | Routes, schemas, and safe error responses |
| `src/socauto/config.py` | Environment settings and runtime paths |
| `src/socauto/db/` | SQLite engine, models, claims, and persistence |
| `src/socauto/services/` | Jobs, accounts, media, templates, leases, pipeline |
| `src/socauto/sources/` | X URL and media adapter |
| `src/socauto/destinations/tiktok/` | TikTok sessions, signing, transfer, publishing |
| `migrations/` | Alembic migration history |
| `signer/tiktok/` | Bun/Chromium signing program and vendored attribution |
| `web/` | Independent Svelte/Vite operator panel |
| `scripts/` | Verification and manual TikTok login utility |
| `tests/` | Python tests |

## Common commands

```bash
uv run alembic upgrade head
uv run uvicorn socauto.app:app --host 127.0.0.1 --port 8000
uv run python -m socauto.worker
bun run --cwd web dev
bun run --cwd web check
bun run --cwd web build
bun run --cwd web preview
```

`preview` is local validation only. It is not a production web server.

## Offline verification

Run the complete suite from the checkout root:

```bash
uv run python scripts/verify.py
```

It requires `uv`, Bun, FFmpeg, ffprobe, and a system Chromium/Chrome binary. It creates an
isolated temporary runtime directory and runs:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest --cov=socauto --cov-report=term-missing
bun test signer/tiktok
bun run --cwd web check
bun run --cwd web build
uv run alembic upgrade head
uv run alembic downgrade base
uv run alembic upgrade head
uv run alembic check
uv build
git diff --check
```

The migration commands in `scripts/verify.py` use a disposable database. Run individual checks
only after installing locked dependencies; standalone runtime tests may need Chromium configured
through `SOCAUTO_TIKTOK_CHROMIUM_BINARY`.

## Migrations and packaging

Use `uv run alembic upgrade head` for the runtime database. Review generated migration content
before committing it, and verify current model/migration alignment with `uv run alembic check`.

`uv build` produces Python artifacts, but the wheel contains only `src/socauto`. It excludes the
signer directory, Bun dependencies, web assets, and Chromium, so it cannot by itself run the
documented service. Docker Compose is the supported self-contained artifact; native deployment
requires a complete checkout and managed runtime dependencies.

## Live-test boundary

The suite is offline: it does not authenticate to X or TikTok or submit live publications. The
private (`Only you`) live publication path was manually confirmed on 2026-09-08. That confirmation
does not validate public visibility. Treat `posted` as TikTok acknowledgement, not visible-post
proof. Inspect the account before retrying `upload_outcome_unknown` to avoid duplicates.

See [operations.md](operations.md) for production constraints and [api.md](api.md) for request
workflows.
