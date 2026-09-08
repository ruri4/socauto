# Roadmap

socauto 0.1.0 is a supported, single-host operator service for republishing one X video to a
connected TikTok account. It is not intended as a multi-tenant or public internet service.

## Current status

- API, SQLite persistence, Alembic migrations, and a separate lease-renewing worker are in use.
- X URL canonicalization, one-video download/transcode, account session import and validation,
  retry, cancellation, restart recovery, and durable job history are supported.
- Reusable caption templates support literal `{{caption}}` substitution. Jobs snapshot template
  content, so template changes do not alter queued jobs or retries.
- Per-job visibility is explicit: `private` is the default and `public` is opt-in.
- The private (`Only you`) live publication path was manually confirmed on TikTok on 2026-09-08.
  `posted` remains an acknowledgement state, not a visibility guarantee.
- The local Svelte panel manages accounts, templates, and jobs against the private API.

## Next priorities

### Validate and maintain the supported path

- [ ] Continue operator confirmation for unusual failures and `upload_outcome_unknown` cases.
- [ ] Perform a separately authorized public-visibility acceptance test before treating public
      publication as live-validated.
- [ ] Track TikTok endpoint, session, and signer changes and adapt when the private web flow
      changes.

### Operational hardening

- [x] Ship a self-contained Docker Compose artifact with loopback-only ports, migration gating,
      persistent runtime data, and a static panel server.
- [ ] Define an operator-approved retention and cleanup policy for failed, cancelled, and
      interrupted attempt media.
- [ ] Improve operational monitoring beyond API process health, including worker progress, queue
      age, disk consumption, and session failures.
- [ ] Document and exercise periodic restore drills for the SQLite database and runtime state.

### Future scope, not current deployment scope

- [ ] Add authentication and authorization before any wider network exposure.
- [ ] Add tenant isolation only if the project deliberately moves beyond one trusted operator.
- [ ] Evaluate alternate supported platform APIs if the private TikTok endpoints become unusable.

## Known boundaries and risks

- TikTok endpoints are undocumented; browser signatures and sessions can break or be restricted
  without notice.
- Acknowledgement does not guarantee moderation completion or public visibility. Unknown upload
  outcomes require manual account inspection before a duplicate-risk retry.
- SQLite is a single-host, single-writer datastore. One worker is the supported default.
- Multi-video X posts are intentionally unsupported. Restricted X posts need operator-provided
  cookies.
- Operators remain responsible for media rights, account access, and platform compliance.

See [README.md](README.md) for the supported deployment and [docs/operations.md](docs/operations.md)
for operational limits.
