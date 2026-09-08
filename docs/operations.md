# Operations guide

## Supported topology

socauto supports one trusted operator on one host: a loopback-bound API, one separate worker,
SQLite, private runtime storage, and a local panel. Docker Compose is the supported self-contained
production path. One worker is the supported default. SQLite is single-host and single-writer
constrained; do not treat fenced job claims as broad worker-scaling support.

The API and panel have no authentication or tenant isolation. Keep them on loopback or behind an
authenticated private gateway. Do not expose account import or job creation to the public internet.

## Docker Compose production path

Install Docker Engine with the Compose plugin, then run from the checkout root:

```bash
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f
```

The panel is `http://127.0.0.1:8080` and the direct API is `http://127.0.0.1:8000`. Both bindings
are loopback-only. `migrate` runs `alembic upgrade head` once, and API/worker start only after it
completes successfully. `/health` reports API process liveness only, not worker, TikTok, account,
queue, or storage health.

`docker compose run --rm migrate` is an optional standalone migration command for a stopped stack;
normal `docker compose up -d` already runs and gates on that service.

Useful lifecycle commands:

```bash
docker compose logs -f api worker web
docker compose stop
docker compose up -d
docker compose down
docker compose build --pull
docker compose up -d
```

The last two commands are the upgrade path after backing up the volume and updating the checkout.
`docker compose down` keeps named volumes; do not add `--volumes` unless intentionally discarding
runtime state. Compose reads optional `.env` values only for `SOCAUTO_LOG_LEVEL`, worker poll/lease,
signer timeout, and TikTok HTTP impersonation, timeout, and attempts. Container data, Chromium,
browser-profile, and signer paths are intentionally fixed, and `SOCAUTO_X_COOKIE_FILE` is omitted.
Startup uses safe defaults when no `.env` exists.

The named `socauto-data` volume is mounted at `/app/data` for migration, API, and worker. It holds
`socauto.db`, SQLite WAL/shm files while active, sessions, browser-profile data, and retained job
media. Inspect it without writing to it:

```bash
docker run --rm -v socauto_socauto-data:/data:ro alpine:3.22 ls -la /data
docker volume inspect socauto_socauto-data
```

Compose prefixes the volume with its project name (`socauto_socauto-data` by default). For a safe
backup, stop API and worker first, then archive the complete volume. Use an existing access-restricted
directory outside the checkout, such as `/srv/backups/socauto` owned by the trusted operator with
mode `0700`. Restore only while stopped:

```bash
docker compose stop
docker run --rm -v socauto_socauto-data:/data:ro -v /srv/backups/socauto:/backup alpine:3.22 \
  tar czf /backup/socauto-data-$(date +%F).tgz -C /data .
docker compose up -d
```

Treat that archive as credentials and media. To replace a volume from a backup, stop the stack and
confirm the current volume may be discarded. Remove it, then have Compose create its labeled volume
without starting migration before extracting as root, so numeric UID/GID `10001` and restrictive
modes are preserved:

```bash
docker compose down
docker volume rm socauto_socauto-data
docker compose create migrate
docker run --rm -v socauto_socauto-data:/data -v /srv/backups/socauto:/backup:ro alpine:3.22 \
  tar xzpf /backup/socauto-data-YYYY-MM-DD.tgz -C /data
docker compose up -d
```

No service runs during extraction. `docker compose up -d` then runs migrations. Validate account
sessions and inspect any recovered in-flight jobs before retrying.

For restricted X posts, create an untracked `compose.x-cookies.yaml` beside `compose.yaml`:

```yaml
services:
  worker:
    environment:
      SOCAUTO_X_COOKIE_FILE: /run/secrets/x-cookies.txt
    volumes:
      - type: bind
        source: /absolute/path/to/x-cookies.txt
        target: /run/secrets/x-cookies.txt
        read_only: true
```

Start with `docker compose -f compose.yaml -f compose.x-cookies.yaml up -d`. Do not set an empty
`SOCAUTO_X_COOKIE_FILE`: Pydantic treats it as a path. Never check the override or cookie file in.

## Native prerequisites and installation

Install Python `>=3.14,<3.15`, uv, Bun `>=1.3.0`, FFmpeg, and Chromium or Google Chrome. From the
checkout root:

```bash
uv sync
bun install
bun install --cwd web
cp .env.example .env
uv run alembic upgrade head
```

The wheel packages only `src/socauto`; it does not contain `signer/`, Bun dependencies, web assets,
or Chromium. Docker Compose packages those assets. Native deployment requires a complete checkout,
or an equivalent separately managed runtime.

## Configuration

Settings use the `SOCAUTO_` prefix and read `.env` in the working directory. Defaults below match
the current settings and [`.env.example`](../.env.example).

| Variable | Default | Purpose |
| --- | --- | --- |
| `SOCAUTO_DATA_DIR` | `data` | Runtime root: SQLite, sessions, and job media |
| `SOCAUTO_LOG_LEVEL` | `INFO` | Worker log level |
| `SOCAUTO_WORKER_POLL_SECONDS` | `2` | Idle worker poll interval, 0.1-60 |
| `SOCAUTO_WORKER_LEASE_SECONDS` | `300` | Claim lease duration, 30-3600 |
| `SOCAUTO_X_COOKIE_FILE` | unset | Netscape cookie file for restricted X posts |
| `SOCAUTO_TIKTOK_USER_AGENT` | built-in Chrome UA | Fallback for imports without a user agent |
| `SOCAUTO_TIKTOK_CHROMIUM_BINARY` | auto-detect | Chromium/Chrome executable |
| `SOCAUTO_TIKTOK_BROWSER_PROFILE_DIR` | `data/tiktok-browser-profile` | Manual-login browser profile |
| `SOCAUTO_TIKTOK_SIGNER_SCRIPT` | `signer/tiktok/sign.js` | Bun TikTok signer script |
| `SOCAUTO_TIKTOK_SIGNER_TIMEOUT_SECONDS` | `45` | Signer timeout, 10-120 |
| `SOCAUTO_TIKTOK_HTTP_IMPERSONATE` | `chrome` | curl_cffi impersonation profile |
| `SOCAUTO_TIKTOK_HTTP_TIMEOUT_SECONDS` | `30` | TikTok HTTP timeout, 5-120 |
| `SOCAUTO_TIKTOK_HTTP_ATTEMPTS` | `3` | Safe HTTP request attempts, 1-5 |

Relative paths resolve from the process working directory, except database paths are resolved to
an absolute SQLite path by the service. Start from the checkout root so `.env`, `signer/`, and
relative data paths work. Runtime directories are created with mode `0700`; session files are
stored beneath `data/sessions` with mode `0600`. Ensure the service user owns and can protect the
whole runtime root. Do not share browser profiles or run concurrent Chromium processes against one.

## Native startup order

After install and before each API/worker rollout, migrate first:

```bash
uv run alembic upgrade head
uv run uvicorn socauto.app:app --host 127.0.0.1 --port 8000
uv run python -m socauto.worker
```

Use separate supervisor units or terminals for the final two commands. Keep their runtime
environment identical. `/health` returns only `{"status":"ok"}` when the API responds; it does
not check the worker, TikTok, account sessions, or queue progress.

## Native panel and static serving

Build the panel from the checkout root:

```bash
bun run --cwd web check
bun run --cwd web build
```

Serve `web/dist/` with an external static server. Configure that server or private gateway to
proxy `/v1` and `/health` to `http://127.0.0.1:8000`. Keep the backend private. `bun run --cwd web
preview` is for local validation only, not production serving. The Compose web image uses nginx,
not Vite, for this purpose.

## Storage, monitoring, and retention

`SOCAUTO_DATA_DIR` contains `socauto.db`, SQLite WAL/shm files while active, `sessions/`, and
`jobs/<job-id>/<attempt-id>/video.mp4`. Successful media is cleaned after a durable `posted`
acknowledgement. Failed, cancelled, and orphaned attempts may remain for inspection; there is no
automatic retention policy. Monitor disk consumption and set an operator-reviewed cleanup policy.

Monitor the API process separately from the worker. Check worker logs, job state/age through the
API, SQLite storage capacity, session-validation failures, and remaining attempt media. A healthy
`/health` response alone is insufficient.

## Backup and restore

For a consistent snapshot, stop or quiesce both API and worker first. Copy the entire runtime
directory or Compose volume, including `socauto.db`, any SQLite WAL/shm files present, `sessions/`,
and retained `jobs/` media, while both processes remain stopped. Store the backup with permissions
suitable for credentials and media.

To restore, stop both processes, replace the runtime directory with the snapshot while preserving
ownership and restrictive permissions, run `uv run alembic upgrade head`, then start API and
worker in the documented order. Validate account sessions and inspect any recovered in-flight jobs
before retrying. Do not copy a live SQLite file without quiescing the writers.

## Shutdown, recovery, and upgrade

Send `SIGINT` or `SIGTERM` to the worker for graceful shutdown. It stops claiming new work and
lets its active stage finish while maintaining its lease. Forced termination is recovered after
lease expiry: expired downloads are requeued, while expired uploads become
`upload_outcome_unknown` and require account inspection before a duplicate-risk retry.

For an upgrade:

1. Read the release notes and back up/quiesce runtime state.
2. Update the checkout and rebuild the Compose images, or install locked native dependencies.
3. Apply migrations with `docker compose up -d` or `uv run alembic upgrade head`.
4. Run `uv run python scripts/verify.py` when the host has the documented tools.
5. Restart API, then worker, and inspect logs, health, and a known job state.

## Credential and platform handling

Cookie exports, `.env`, X cookie files, signer inputs, and browser profiles are secrets. Never
commit them, include them in logs, or pass them through online converters. TikTok uses undocumented
private endpoints and browser-generated signatures. Sessions may expire and endpoint behavior may
change or trigger platform restrictions. `posted` records acknowledgement, not confirmed visibility;
inspect the account before retrying an unknown outcome. Operators remain responsible for rights and
platform compliance.
