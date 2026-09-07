# Roadmap

socauto is being built as an API-first X/Twitter-to-TikTok automation backend. The MVP is
currently **8 of 8 implementation/offline-verification phases complete**. Persistence, TikTok
account sessions, X downloads, publishing, the standalone worker pipeline, and job HTTP endpoints
are implemented. **Live end-to-end acceptance is deferred and remains unverified.**

## Current capabilities

- FastAPI service with OpenAPI and `GET /health`
- SQLite persistence managed by SQLModel and Alembic
- Durable job states, URL canonicalization, destination-level deduplication, leases, retries, and
  restart recovery
- Explicit uploaded-cookie import with live TikTok identity validation and an optional persistent
  browser-login utility
- Validated TikTok cookies stored as private, versioned JSON files
- Live session identity checks, paginated account listing, and safe account deletion
- Typed X metadata extraction and private H.264/AAC MP4 downloads through `yt-dlp` and FFmpeg
- Python tooling through `uv`; browser-side signing tooling through Bun and Playwright Core
- HTTP TikTok upload adapter with isolated credentials and an offline-tested Bun signer
- Standalone lease-renewing worker with fenced updates, cancellation, and retained-media cleanup
- Versioned job submission, filtered listing, status, explicit retry, and cancellation endpoints

## Phases

### 1. Backend foundation - complete

Commit: `0a56efe bootstrap backend foundation`

- [x] Python 3.14 `uv` project and locked dependencies
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

### 3. TikTok account sessions - complete

The current cookie-import surface supersedes `92c3012 add TikTok account authentication`.

- [x] `POST /v1/accounts/tiktok/import` with a bounded multipart cookie export
- [x] Live account-info validation before any credential persistence
- [x] Idempotent session replacement by TikTok user ID and multiple destination accounts
- [x] `GET /v1/accounts` with bounded pagination
- [x] `DELETE /v1/accounts/{id}` with referenced-job protection
- [x] Strict required-cookie validation and atomic JSON storage with mode `0600`
- [x] Credential-safe API responses and session-path containment

### 4. X source adapter - complete

Commit: `884ccd6 add X media source adapter`

- [x] Extract tweet metadata and media through the `yt-dlp` Python API
- [x] Support an optional Netscape cookie file for gated posts
- [x] Download into a job-private directory with controlled filenames
- [x] Prefer or merge to TikTok-compatible H.264/AAC MP4 using FFmpeg
- [x] Use tweet text as the default caption while allowing an API override
- [x] Reject multi-video tweets explicitly in the MVP
- [x] Return typed metadata and download failures without credential-bearing diagnostics

### 5. TikTok publishing adapter - complete

- [x] Adapt the required MIT-licensed HTTP flow from TiktokAutoUploader with attribution
- [x] Create upload projects and validate temporary upload credentials
- [x] Transfer 5 MiB chunks with CRC32 values; validate echoed CRCs when present
- [x] Finish and commit uploads with strict HTTP and TikTok status validation
- [x] Generate `_signature` and `X-Bogus` through Bun, Playwright Core, and system Chromium
- [x] Keep one stable user agent across import, signing, transfer, and publication
- [x] Retry transient network and 5xx failures only on explicitly safe operations
- [x] Treat ambiguous publish results as unknown, never as an automatic retry
- [x] Verify mocked HTTP sequencing, failure cases, and real offline signing

Live private upload verification remains in the deferred checklist below. Publish acknowledgements
do not guarantee public visibility, and successful responses may not provide a post URL.

### 6. Worker and pipeline - complete

- [x] Add a standalone worker process with durable job claiming and lease renewal
- [x] Run `pending -> downloading -> downloaded -> uploading -> posted | failed`
- [x] Honor cancellation before an upload claim; drain active stages on graceful shutdown
- [x] Record safe failure codes and acknowledgement IDs, with nullable posted URLs
- [x] Delete media only after durable acknowledgement; retain failed media for retry
- [x] Recover interrupted downloads and mark uncertain interrupted uploads for manual review
- [x] Fence stale workers, isolate attempt directories, and verify retained media before upload
- [x] Verify concurrent claims, heartbeat lifecycle, crash recovery, cleanup, and real process shutdown

### 7. Job API - complete

- [x] `POST /v1/jobs` returning `202 Accepted` and a status Location
- [x] Paginated `GET /v1/jobs` with state/account filters
- [x] `GET /v1/jobs/{id}` with safe state, caption, and acknowledgement fields
- [x] `POST /v1/jobs/{id}/retry` with explicit duplicate-risk acknowledgement for unknown outcomes
- [x] `DELETE /v1/jobs/{id}` for cancellation, preserving history and deduplication
- [x] Stable schemas, bounded validation, and machine-readable documented errors
- [x] API/worker integration tests, safe SQLite contention responses, and stale retry fencing

### 8. Offline completion and verification - complete

- [x] Unit tests for captions, download selection, cookie handling, signing, chunk CRC, and retries
- [x] Mocked integration tests for the complete uploader HTTP sequence and worker pipeline
- [x] API success, validation, conflict, cancellation, and expected operational-error tests
- [x] Credential-safe logging and session-storage failure/transaction rollback tests
- [x] Real loopback yt-dlp downloads with synthetic H.264/AAC media and FFmpeg merging
- [x] Correct final output resolution from yt-dlp's `requested_downloads` metadata
- [x] Real API restart/persistence and graceful API/worker process shutdown tests
- [x] Real offline Python-to-Bun-to-Chromium signing without platform requests
- [x] Repeatable `uv run python scripts/verify.py`, no inline environment assignments
- [x] Ruff, strict mypy, pytest coverage, Bun tests, isolated migration round trips/drift, and builds

Verified on 2026-09-06: **153 Python tests passed**, **93% Python statement coverage**, strict mypy
over 61 files, and **3 Bun tests passed** including Chromium. Two upstream TestClient deprecation
warnings remain. Coverage is not proof of live endpoint compatibility.

Reverified on 2026-09-07 after replacing browser authentication with uploaded-cookie import:
**170 Python tests passed**, **93% Python statement coverage**, strict mypy over 63 files, and
**3 Bun tests passed** including Chromium. Live TikTok compatibility remains unverified.

The experimental signed, paginated TikTok profile-content read surface was removed after live
testing showed that TikTok's page-native requests depend on browser-bound telemetry that cannot be
reproduced reliably by the service transport. The profile-login utility remains available for
authentication, while the supported adapter is limited to account validation, transfer, and
publishing.

### Deferred live acceptance - pending, run separately when authorized

No live X download, TikTok cookie validation, upload, or publication was run during phase 8.

- [ ] Choose an authorized single-video X post and a test TikTok account; keep the API private.
- [ ] Import an authorized TikTok cookie export and verify the returned identity without logging it.
- [ ] Download the chosen X post; inspect actual H.264/AAC codecs, caption, and one-video selection.
- [ ] Repeat with source cookies only if restricted-post support is needed.
- [ ] Submit through the API and worker with **private visibility**, then inspect the TikTok account
      directly to confirm one playable private post. A `posted` acknowledgement alone is insufficient.
- [ ] Check durable status/IDs, duplicate submission protection, and successful-media cleanup.
- [ ] Confirm safe expired-session/error handling and retained-media retry. Inspect the account before
      acknowledging duplicate risk for an unknown outcome; never blindly replay a publish.
- [ ] Record versions, date, safe result identifiers, and any endpoint/signature changes here.
- [ ] Consider a separate explicitly authorized public-publication test only after private acceptance.

## MVP completion criteria

Live MVP acceptance is still pending. It requires a connected TikTok account to accept one supported
X status URL through the API, survive API or worker restarts, download exactly one compatible video,
produce one verified private post, report durable progress and safe errors, and clean up media after
durable acknowledgement. Exactly-once publication cannot be guaranteed across a lost acknowledgement;
unknown outcomes require manual review rather than automatic retries.

## Known risks

- TikTok private endpoints and browser signatures can change without notice.
- Sessions expire, and automated publishing can trigger restrictions, shadow limits, or bans.
- Restricted X posts require user-provided cookies.
- Multi-video X posts remain intentionally unsupported in the MVP.
- Copyright and republishing permission remain the operator's responsibility.
