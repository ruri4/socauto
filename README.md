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

To connect TikTok, call `POST /v1/accounts/tiktok/auth` from the same host as the API. The request
opens a visible Chromium window and completes after login cookies are captured or the configured
timeout expires. Session JSON is stored with mode `0600` beneath the private data directory.

Public X posts need no source credentials. For restricted posts, set `SOCAUTO_X_COOKIE_FILE` to a
Netscape-format cookie file readable by the worker. Downloads are written beneath the private jobs
directory as H.264/AAC MP4 files; posts containing more than one video are rejected in the MVP.

## TikTok adapter

`TikTokDestination` is the synchronous publishing boundary for the worker. It accepts a
validated `TikTokSession`, an MP4 path, and a caption. Publication defaults to private (`visibility=1`);
public visibility requires an explicit `visibility=0`. Hashtag metadata uses UTF-16 offsets and
matching markup. Mentions remain plain text, without account lookups.

Media transfer and publishing use HTTP, with a separate cookie-free upload-CDN session. The
temporary VOD credentials use AWS Signature V4. Transfer streams 5 MiB CRC32-tagged chunks,
then validates finish, commit, and publish responses. Only metadata and chunk calls retry
transient connection/timeout and 5xx failures. Final publication is never automatically retried:
timeouts, 5xx responses, or malformed acknowledgements produce `upload_outcome_unknown`.

The Bun signer launches a short-lived, network-blocked Chromium context and does not receive
account cookies. Its vendored assets and attribution are in `signer/tiktok/`. Run from the checkout
root, or set `SOCAUTO_TIKTOK_SIGNER_SCRIPT` to its absolute path. Python wheels do not contain the
Bun dependencies or signer directory; deploy these alongside the backend. The pipeline, rather
than the adapter, persists job results and cleans acknowledged-success media.

A `PublishResult` means TikTok acknowledged the request, not that moderation finished or a public
post is visible. A post URL may be unavailable. Local tests do **not** establish that the current
private endpoint accepts these signatures; an opt-in private-account smoke test is still required.
Do not enable raw `http.client` wire dumps or log Requests objects, cookies, signed URLs, or responses.

## Worker

Apply migrations, then run the worker separately from the API, from the same checkout directory
and with the same `SOCAUTO_DATA_DIR`:

```bash
uv run alembic upgrade head
uv run python -m socauto.worker
```

The worker consumes existing database jobs. HTTP job submission and retry endpoints arrive in
phase 7; this phase does not add a user-facing CLI. Worker publication is private-only for now.

- Each claim executes one stage: `pending -> downloading -> downloaded`, then
  `downloaded -> uploading -> posted | failed`. The resolved caption survives restarts and retries.
- Short SQLite transactions atomically claim jobs. A separate heartbeat renews the lease every
  third of `SOCAUTO_WORKER_LEASE_SECONDS` (default 300). Completion and renewal require the same
  unexpired claim; a stale worker cannot overwrite recovery or a replacement worker's result.
  The adapter checks ownership again immediately before its irreversible publish request.
- Downloads use `jobs/<job-id>/<attempt-id>/video.mp4`, preventing a late, expired download from
  overwriting its replacement. Retained media is checked for path containment, size, and SHA-256
  before upload. The jobs directory must remain private to trusted local processes.
- Cancellation is accepted before an upload claim. A running download finishes before cancellation
  is recorded; an upload already claimed cannot be cancelled safely. `SIGINT`/`SIGTERM` stop new
  claims and let the active stage finish while heartbeats continue. Forced termination is recovered
  after lease expiry, not immediately on restart.
- Expired downloads are requeued. Expired uploads fail with `upload_outcome_unknown`, requiring
  manual review before retry. Bounded retries live inside the source/HTTP adapters; the worker never
  blindly replays a whole publish operation, including after a retryable transport error.
- `posted` means a durable TikTok acknowledgement, **not confirmed public visibility**. Creation,
  video, and optional post identifiers are saved even when `posted_url` is null. If the acknowledgement
  cannot be saved before lease loss or a crash, retain the media and review the unknown outcome.
- Successful attempt files are removed only after committing `posted`. Cleanup failures are retried
  by later worker passes. Failed, cancelled, and orphaned interrupted attempts are retained for
  inspection, not automatically pruned. Monitor disk usage; no retention policy exists yet.

## Development

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
bun test signer/tiktok
# Include the offline Chromium signer smoke test:
SOCAUTO_TIKTOK_CHROMIUM_BINARY=/usr/bin/chromium-browser bun test signer/tiktok
```
