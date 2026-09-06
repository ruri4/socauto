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

The API has no client authentication or tenant isolation yet. Keep it bound to loopback or behind
an authenticated private gateway. Do not expose it directly to the internet; callers can connect
accounts and queue publications. CORS and frontend integration are not configured.

To connect TikTok, call `POST /v1/accounts/tiktok/auth` from the same host as the API. The request
opens a visible Chromium window and completes after login cookies are captured or the configured
timeout expires. Session JSON is stored with mode `0600` beneath the private data directory.

Public X posts need no source credentials. For restricted posts, set `SOCAUTO_X_COOKIE_FILE` to a
Netscape-format cookie file readable by the worker. Downloads are written beneath the private jobs
directory as H.264/AAC MP4 files; posts containing more than one video are rejected in the MVP.

## Job API

Connect an account, then submit a job with `POST /v1/jobs`:

```json
{
  "source_url": "https://x.com/example/status/123456789",
  "destination_account_id": "00000000-0000-0000-0000-000000000000",
  "caption_override": null
}
```

Replace the account UUID with the ID returned by login or `GET /v1/accounts`.
The response is `202 Accepted` with a job snapshot and a `Location: /v1/jobs/<id>` header.
Submission only writes to SQLite; the separate worker performs downloads and uploads.
Omitted/null captions use tweet text; an empty string explicitly clears the caption. Overrides
are limited to 2200 UTF-16 code units. Publication through the worker is **private-only**.

| Endpoint | Behavior |
| --- | --- |
| `GET /v1/jobs` | Newest-first listing, `offset=0`, `limit=50` (maximum 100) |
| `GET /v1/jobs/{id}` | Current state, safe failure code, timestamps, caption, acknowledgement IDs |
| `POST /v1/jobs/{id}/retry` | `202`; requeue a failed job, reusing retained media when available |
| `DELETE /v1/jobs/{id}` | Cancel, not delete history: `200` immediately or `202` while a download drains |

Listing supports optional `state` and `destination_account_id` filters; `total` counts the filtered
results. Ordering is by creation time descending, then ID. Offset pages are not a frozen snapshot
while other callers submit jobs. Uploading and posted jobs cannot be cancelled (`409`). Repeated
cancellation of a cancelled job succeeds. History continues to protect referenced accounts from
deletion and to deduplicate canonical URLs, including after failure or cancellation.

Errors use `{"detail":{"code":"...","message":"..."}}`. Duplicate submission returns `409`
with code `duplicate_job` and `detail.existing_job_id`. Other expected errors include `404` for a
missing account/job, `409` for an inactive account or invalid/concurrently changed job state,
`422` for invalid input, and `503` with `Retry-After` when SQLite is busy. Validation errors do not
echo request bodies. Responses omit session files, cookies, local media paths, and worker leases.

Ordinary retries accept no body or `{}`. If `error_code` is `upload_outcome_unknown`, inspect the
TikTok account first. Only then explicitly send `{"acknowledge_duplicate_risk":true}` to the retry
endpoint. This can create a duplicate if the original publish succeeded. Requeueing does not prove
that retained media or the session is valid; the worker rechecks both before publication.

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

The worker consumes database jobs submitted through the API. There is no user-facing CLI.
Worker publication is private-only for now.

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

Run the complete offline verification suite from the checkout:

```bash
uv run python scripts/verify.py
```

The script discovers system Chromium (or uses `SOCAUTO_TIKTOK_CHROMIUM_BINARY` from its environment),
sets child-process configuration internally, and fails if required runtime tools are missing. It runs
Ruff, strict mypy, pytest with coverage, Bun tests, real loopback yt-dlp/FFmpeg downloads, offline
Python/Bun/Chromium signing, and API/worker process checks. Migration upgrade/downgrade/upgrade and
drift checks use a disposable database, **not your runtime database**. Builds go to `dist/`.
Install locked dependencies first; tool/package setup may need network access, but the tests do not
log in to or publish on X/TikTok. Live acceptance is deferred in [ROADMAP.md](ROADMAP.md).

Individual checks are also available:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
bun test signer/tiktok
```

Standalone test commands skip Chromium runtime tests unless the browser environment is configured;
`scripts/verify.py` configures it automatically. FFmpeg/ffprobe are required for media runtime tests.
