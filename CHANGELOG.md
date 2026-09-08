# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-09-08

### Added

- Single-host API and worker pipeline for republishing one supported X video to TikTok.
- Durable SQLite jobs, Alembic migrations, account cookie import and live identity validation.
- X media download/transcode, TikTok upload/signing, retry safety, cancellation, and recovery.
- Reusable caption templates with immutable per-job snapshots.
- Explicit per-job TikTok visibility, with private as the default and public as opt-in.
- Local Svelte operator panel for accounts, templates, and jobs.
- Docker Compose production artifact with migration gating, non-root API/worker containers,
  loopback-only API/panel ports, persistent runtime volume, and nginx static panel serving.

### Verified

- The private (`Only you`) live publication path was manually confirmed on TikTok on 2026-09-08.
  This confirmation does not establish public-visibility acceptance. API state `posted` records
  TikTok acknowledgement and is not, by itself, a visibility confirmation.

### Security

- The documented scope is one trusted operator on one host. The API and panel do not provide
  authentication or tenant isolation and must remain loopback-only or behind an authenticated
  private gateway.
