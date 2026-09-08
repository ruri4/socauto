# API guide

The API is versioned under `/v1`. Use the running service's `/docs` or `/openapi.json` as the
authoritative schema for response fields and validation details. This guide covers the operator
workflow and endpoint surface.

The API has no authentication. Keep it on loopback or behind an authenticated private gateway.

## Account workflow

1. Export cookies for an authenticated `tiktok.com` browser session.
2. `POST /v1/accounts/tiktok/import` as multipart form data with `file`; optionally provide
   `user_agent` matching the exporting browser.
3. The service validates the identity live before persisting normalized session data.
4. List accounts, create a job using an active account ID, and revalidate sessions when needed.

Cookie imports accept Netscape cookie text, a browser-extension JSON array, or a JSON object with
`cookies`. They are limited to 1 MiB and the original upload is not retained.

## Template workflow

Create reusable templates before submitting jobs, then use their IDs with `saved_template` jobs.
Template names are unique and bodies are capped at 2,200 UTF-16 code units. `{{caption}}` is the
only placeholder; it is substituted literally with normalized X text. Repetition and no
placeholder are valid. Unknown placeholders, whitespace variants, and unmatched braces are not.

Queued saved-template jobs snapshot the template name and body. Editing or deleting a template
does not change queued jobs, history, or retries.

## Job submission

Submit jobs after importing an active account. `POST /v1/jobs` returns `202 Accepted` and a
`Location` header. It writes the job; the separate worker performs download and publication.

```json
{
  "source_url": "https://x.com/example/status/123456789",
  "destination_account_id": "00000000-0000-0000-0000-000000000000",
  "caption_mode": "source",
  "visibility": "private"
}
```

Override caption:

```json
{
  "source_url": "https://x.com/example/status/123456789",
  "destination_account_id": "00000000-0000-0000-0000-000000000000",
  "caption_mode": "override",
  "caption_override": "operator supplied caption",
  "visibility": "public"
}
```

Saved template and inline custom template:

```json
{
  "source_url": "https://x.com/example/status/123456789",
  "destination_account_id": "00000000-0000-0000-0000-000000000000",
  "caption_mode": "saved_template",
  "caption_template_id": "00000000-0000-0000-0000-000000000000"
}
```

```json
{
  "source_url": "https://x.com/example/status/123456789",
  "destination_account_id": "00000000-0000-0000-0000-000000000000",
  "caption_mode": "custom_template",
  "caption_template": "{{caption}}\n#example"
}
```

`visibility` defaults to `private`; only `private` and `public` are accepted. Caption modes are
`source`, `override`, `saved_template`, and `custom_template`. For compatibility, an omitted
mode infers `override` when `caption_override` is present, otherwise `source`; template inputs
always require an explicit template mode.

## Endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | API process health only |
| `POST` | `/v1/accounts/tiktok/import` | Import and live-validate TikTok cookies |
| `POST` | `/v1/accounts/{account_id}/session/validate` | Revalidate a stored account session |
| `GET` | `/v1/accounts` | List accounts, `offset` and `limit` |
| `DELETE` | `/v1/accounts/{account_id}` | Remove an unreferenced account |
| `GET` | `/v1/caption-templates` | List templates, `offset` and `limit` |
| `POST` | `/v1/caption-templates` | Create a template |
| `GET` | `/v1/caption-templates/{template_id}` | Read a template |
| `PATCH` | `/v1/caption-templates/{template_id}` | Change a template name or body |
| `DELETE` | `/v1/caption-templates/{template_id}` | Delete a template |
| `POST` | `/v1/jobs` | Queue a job |
| `GET` | `/v1/jobs` | List jobs, with optional `state` and `destination_account_id` |
| `GET` | `/v1/jobs/{job_id}` | Read current job state and safe result fields |
| `POST` | `/v1/jobs/{job_id}/retry` | Requeue a failed job |
| `DELETE` | `/v1/jobs/{job_id}` | Request cancellation without deleting history |

Pagination defaults to `offset=0` and `limit=50`; `limit` is at most 100. Account, template,
and job listings include `total`, `offset`, and `limit`.

## States, cancellation, and retry

Jobs move through `pending`, `downloading`, `downloaded`, `uploading`, then `posted`, `failed`,
or `cancelled`. A running download drains before a cancellation is recorded. Uploading and posted
jobs cannot be cancelled. Job history is retained for URL deduplication and account protection.

`posted` means the service durably recorded TikTok's acknowledgement. It does not prove that
moderation completed or that a post is visible. The private live path was manually confirmed on
2026-09-08; public visibility has not been manually validated.

Retry accepts no body or `{}` for ordinary failed jobs. If `error_code` is
`upload_outcome_unknown`, inspect the TikTok account first. Retrying then requires:

```json
{"acknowledge_duplicate_risk": true}
```

That acknowledgement can produce a duplicate if the original publication succeeded. Retained
media and sessions are rechecked by the worker.

Expected errors use `{"detail":{"code":"...","message":"..."}}`. Common responses are `404`
for missing resources, `409` for conflicts or invalid transitions, `422` for invalid input, and
`503` with `Retry-After` when SQLite is busy. Responses omit cookies, session paths, local media
paths, and worker leases.
