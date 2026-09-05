# Roadmap

socauto is being built as an API-first X/Twitter-to-TikTok automation backend. The MVP is
currently **3 of 8 phases complete**. Persistence and TikTok account login are working, but the
download, upload, and worker pipeline are not connected yet.

## Current capabilities

- FastAPI service with OpenAPI and `GET /health`
- SQLite persistence managed by SQLModel and Alembic
- Durable job states, URL canonicalization, destination-level deduplication, leases, retries, and
  restart recovery
- Interactive host-local TikTok login through Selenium and Chromium
- Validated TikTok cookies stored as private, versioned JSON files
- Paginated account listing and safe account deletion
- Python tooling through `uv`; browser-side signing tooling through Bun and Playwright Core

## Phases

### 1. Backend foundation - complete

Commit: `0a56efe bootstrap backend foundation`

- [x] Python 3.12 `uv` project and locked dependencies
- [x] FastAPI application factory, health endpoint, and runtime configuration
- [x] Bun and Playwright Core configured for system Chromium
- [x] Private runtime directories and setup documentation

### 2. Durable persistence - complete

Commit: `734101f add durable job persistence`

- [x] Account, job, and media models with an initial Alembic migration
- [x] Canonical X/Twitter status URLs and accidental-repeat deduplication
- [x] Validated job-state transitions and compare-and-set queue claims
- [x] Lease expiry and restart recovery without automatic duplicate TikTok publication
- [x] Retry from retained media after failed uploads

### 3. TikTok account authentication - complete

Commit: `92c3012 add TikTok account authentication`

- [x] `POST /v1/accounts/tiktok/auth`
- [x] `GET /v1/accounts` with bounded pagination
- [x] `DELETE /v1/accounts/{id}` with referenced-job protection
- [x] Visible Selenium login with a bounded timeout and guaranteed browser shutdown
- [x] Strict required-cookie validation and atomic JSON storage with mode `0600`
- [x] Credential-safe API responses and session-path containment

### 4. X source adapter - next

- [ ] Extract tweet metadata and media through the `yt-dlp` Python API
- [ ] Support an optional Netscape cookie file for gated posts
- [ ] Download into a job-private directory with controlled filenames
- [ ] Prefer or merge to TikTok-compatible H.264/AAC MP4 using FFmpeg
- [ ] Use tweet text as the default caption while allowing an API override
- [ ] Reject multi-video tweets explicitly in the MVP
- [ ] Return typed metadata and download failures without credential-bearing diagnostics

### 5. TikTok publishing adapter

- [ ] Adapt the required MIT-licensed HTTP flow from TiktokAutoUploader with attribution
- [ ] Create upload projects and validate temporary upload credentials
- [ ] Transfer 5 MiB chunks with verified CRC32 values
- [ ] Finish and commit uploads with strict HTTP and TikTok status validation
- [ ] Generate `_signature` and `X-Bogus` through Bun, Playwright Core, and system Chromium
- [ ] Keep one stable user agent across login, signing, transfer, and publication
- [ ] Retry only transient network and 5xx failures within strict bounds

### 6. Worker and pipeline

- [ ] Add a standalone worker process with durable job claiming and lease renewal
- [ ] Run `pending -> downloading -> downloaded -> uploading -> posted | failed`
- [ ] Honor cancellation before irreversible publication
- [ ] Record typed, safe failure codes and posted URLs
- [ ] Delete media only after confirmed success; retain failed media for retry
- [ ] Recover interrupted downloads and mark uncertain interrupted uploads for manual review

### 7. Job API

- [ ] `POST /v1/jobs` returning `202 Accepted`
- [ ] Paginated `GET /v1/jobs`
- [ ] `GET /v1/jobs/{id}`
- [ ] `POST /v1/jobs/{id}/retry`
- [ ] `DELETE /v1/jobs/{id}` for cancellation
- [ ] Stable schemas and machine-readable errors for a future frontend

### 8. Completion and verification

- [ ] Unit tests for captions, download selection, cookie handling, signing, chunk CRC, and retries
- [ ] Mocked integration tests for the complete uploader HTTP sequence and worker pipeline
- [ ] API tests for all success, validation, conflict, cancellation, and upstream-failure responses
- [ ] Credential-safe logging tests
- [ ] Ruff, strict mypy, pytest, Alembic drift, build, and process doctor checks
- [ ] Opt-in live X download smoke test
- [ ] Opt-in private TikTok upload smoke test before any public publication test

## MVP completion criteria

The MVP is complete when a connected TikTok account can accept one supported X status URL through
the API, survive API or worker restarts, download exactly one compatible video, publish it once,
report durable progress and safe errors, and clean up confirmed-success media.

## Known risks

- TikTok private endpoints and browser signatures can change without notice.
- Sessions expire, and automated publishing can trigger restrictions, shadow limits, or bans.
- Restricted X posts require user-provided cookies.
- Multi-video X posts remain intentionally unsupported in the MVP.
- Copyright and republishing permission remain the operator's responsibility.
