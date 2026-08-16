# ATS Resume Tailor Agent — Application Tracker

**Date:** 2026-08-13
**Status:** Implemented; canonical maintenance handoff
**Related specification:** `docs/superpowers/specs/2026-08-09-web-ui-simple-v1.md`

This document is the authoritative specification for application tracking in the local web app. Where it conflicts with an earlier tracker proposal or an implementation assumption, this document wins. The existing tailoring queue, one-page fit recovery, pipeline, CLI, and artifact contracts remain unchanged.

## Goal

Let the user record whether a tailored job has been applied to, update that record later, and review all applications in one readable dashboard. The app also maintains a spreadsheet-friendly CSV export.

The supported workflow is:

```text
Create or open a tailoring job
→ mark it Not applied or Applied
→ optionally record the applied date, posting URL, and notes
→ review or edit it later in the Applications dashboard
→ download the current aggregate as applications.csv
```

The dashboard is the authoritative editing surface. The CSV is a derived export and is not imported back into the app.

## Product Rules

- Every web job created after application tracking was enabled has exactly one application record.
- Application status is independent of tailoring state. A completed, failed, queued, running, or action-required tailoring job can still be tracked.
- Status has exactly two values in this version: `not_applied` and `applied`.
- New trackable web jobs default to `not_applied`.
- Changing status to `applied` records an application date. If none is supplied, the server uses its current local calendar date.
- Changing status to `not_applied` clears the application date.
- Job URL and notes survive either status choice.
- The Applications dashboard and selected-job view edit the same persisted record.
- CSV is regenerated from persisted job metadata. It is never a second source of truth.
- CLI-only output directories are excluded because they do not have reliable application metadata.
- Legacy web jobs whose persisted metadata predates application tracking are also excluded from the Applications dashboard and CSV. They remain available in normal job history, but are not assigned fabricated tracking or creation dates.
- Updates survive browser refreshes and server restarts.
- Multiple browser tabs receive tracking updates through the existing application SSE stream.

## Deliberately Excluded

Do not add these in this version:

- CSV import or synchronization of manual CSV edits.
- Interview, offer, rejection, withdrawal, or follow-up stages.
- Authentication, accounts, multi-user ownership, or cloud synchronization.
- Automated job-board scraping or URL fetching.
- Email/calendar reminders or notifications.
- Automatic application submission.
- A database or new runtime dependency.
- Changes to Gemini calls, tailoring prompts, fitting behavior, or generated resume artifacts.

## Data Contract

Extend the existing persisted job model with an `application` object:

| Field | Type | Default | Rules |
|---|---|---:|---|
| `status` | `not_applied \| applied` | `not_applied` | Required in persisted and API representations. |
| `applied_on` | `YYYY-MM-DD \| null` | `null` | Set for Applied; cleared for Not applied. |
| `job_url` | `string \| null` | `null` | Trimmed HTTP or HTTPS URL, maximum 2,048 characters. |
| `notes` | `string` | `""` | Maximum 4,000 characters; preserve internal line breaks. |
| `updated_at` | UTC ISO-8601 timestamp or `null` | `null` | Server-owned; changes only when the record changes. |
| `revision` | non-negative integer | `0` | Server-owned optimistic-concurrency version. |

Persist `application_tracking_available: true` for new trackable jobs. Missing or false availability on a legacy job prevents that job from entering the aggregate dashboard or CSV.

Persistence remains inside each job's existing metadata file:

```text
output/<job-id>/web_job.json
```

The private state directory also contains the derived aggregate:

```text
.resume-tailor/applications.csv
```

### Compatibility and hydration

- The new `application` field must use a default factory so existing `web_job.json` files still validate without a migration script.
- Startup hydration detects whether the original persisted document had application-tracking metadata. A legacy file without it receives `application_tracking_available=false` in memory and is omitted from tracking aggregates.
- Do not eagerly rewrite every legacy job file solely to add defaults. Persist the expanded model on the next legitimate mutation.
- Existing response fields remain backward compatible; application data is additive.
- The aggregate CSV is rebuilt at startup from trackable web jobs only.

### Normalization

- Trim outer whitespace from `job_url`; convert an empty value to `null`.
- Accept only absolute `http://` or `https://` URLs. Reject credentials embedded in URLs and all other schemes.
- Preserve notes content except outer whitespace may be trimmed. Never interpret notes as HTML.
- When a successful request produces no semantic change, return the current record without changing `updated_at` or `revision`.

## API Contract

All request models are strict Pydantic v2 boundary models with unknown fields forbidden. Validation errors use the app's existing RFC 9457 problem response.

### List applications

```text
GET /api/applications
```

Return an object with:

- `summary.total`
- `summary.applied`
- `summary.not_applied`
- `items`, ordered by job creation time descending

Each item includes:

- `job_id`, `company`, `role`, and `source`
- current tailoring `state`
- `created_at` and `finished_at`
- `resume_available`
- the complete application record

Only `source=web` jobs with `application_tracking_available=true` are included.

### Update one application

```text
PUT /api/jobs/{job_id}/application
```

The request replaces the complete user-editable application record:

```json
{
  "status": "applied",
  "applied_on": "2026-08-13",
  "job_url": "https://example.com/jobs/123",
  "notes": "Submitted through the company portal.",
  "revision": 0
}
```

Behavior:

- `200`: update committed atomically; return the current application item.
- `200`: an identical replay of the immediately committed payload returns the current item without another revision increment.
- `404`: the job does not exist.
- `409`: the supplied revision is stale and the requested values differ from current persisted values.
- `409`: the job predates application tracking and is not eligible for a fabricated tracking record.
- `422`: status, date, URL, notes, revision, or request shape is invalid.
- A real change increments `revision` by one and writes `updated_at` in UTC.
- The job metadata write completes before the success response or SSE event.
- A failed write leaves both in-memory and on-disk state unchanged.

The endpoint is a complete-replacement `PUT`, not a partial `PATCH`, so retries and conflict comparison have one unambiguous payload.

### Download CSV

```text
GET /api/applications.csv
```

Return `text/csv; charset=utf-8` as attachment `applications.csv`, with these columns in this exact order:

1. `job_id`
2. `company`
3. `role`
4. `application_status`
5. `applied_on`
6. `job_url`
7. `notes`
8. `tracking_updated_at`
9. `tailoring_state`
10. `created_at`
11. `finished_at`
12. `resume_available`

Use Python's standard `csv` module with correct quoting for commas, quotes, and embedded newlines. Before export, prefix a single quote to any user-controlled cell whose first non-whitespace character is `=`, `+`, `-`, or `@` to prevent spreadsheet formula execution.

### Existing responses and events

- Add the application record to existing job list and detail responses.
- Add `job_application_updated` to the existing SSE event allowlist.
- Event data contains `job_id` and the current public application item.
- Publish only after persistence and CSV regeneration succeed.
- Clients receiving the event update cached list, dashboard, and selected-job state without refetching unrelated pipeline events.

## Persistence and Concurrency

- Reuse the queue registry's existing mutex and atomic sibling-file replacement helper.
- The registry owns all tracking reads and mutations; routes do not write files directly.
- Apply model validation and normalization before taking the mutation lock.
- Under the lock, compare revisions, create the next persisted model, atomically replace `web_job.json`, regenerate the CSV, then update in-memory state.
- If CSV regeneration fails after the job write, rebuild it from persisted jobs before returning. Do not roll back a valid job record to stale data.
- Generate CSV from a stable registry snapshot, not while iterating a mutable job collection.
- Regenerate `.resume-tailor/applications.csv` at startup, after a web job is created or removed, and after every successful tracking change.
- The CSV file is derived. External edits may be overwritten by the next regeneration and are not read as application mutations.

## User Interface

Extend the current plain HTML/CSS/JavaScript Precision Tool interface; do not add a frontend framework or build step.

### Navigation and dashboard

- Add an **Applications** action to the app header.
- Activating it replaces the main detail workspace with the Applications dashboard while preserving the existing job rail and queue state.
- Returning to a job restores the previous detail tab and selection.
- On mobile, Applications is a full workspace view with a clear Jobs/Back action.

The dashboard contains:

- Title and short description.
- Summary metrics for Total, Applied, and Not applied.
- Search by company or role.
- Native filter controls for All, Not applied, and Applied.
- **Download CSV** action linked to `/api/applications.csv`.
- Compact responsive rows that become stacked cards on narrow screens.

Each row shows:

- Company and role.
- Application status.
- Applied date or an em dash.
- Tailoring state.
- Last tracking update.
- An **Edit** action.

Default ordering is newest tailoring job first. Filtering and search are client-side over the loaded application list; they must compose with one another.

### Selected-job tracking section

- Add a compact **Application** section near the existing job overview.
- Show Applied or Not applied independently from the tailoring-state badge.
- Show applied date, URL, and a shortened notes preview when present.
- Provide an **Edit application** button that opens the same editor used by dashboard rows.

### Shared editor

Use one native `<dialog>` containing one short form:

1. Visible label and native `<select>` for status.
2. Visible label and native date input for applied date.
3. Visible label and `type="url"` input for job URL.
4. Visible label and textarea for notes.
5. Reserved inline error slots and an `aria-live` submission-status region.
6. Cancel and Save changes buttons.

Interaction rules:

- Choosing Applied reveals/enables the date field and pre-fills the browser's local date only when no date exists.
- Choosing Not applied clears and disables/hides the date field.
- Validate untouched fields on blur or submit, not on first keystroke.
- Once a field has errored, revalidate it on input.
- Keep Save enabled; explain validation failures after activation.
- Disable Save only while a request is in flight to prevent double submission.
- Failed requests preserve every entered value.
- On `409`, retain the draft and show: “This application changed in another view.” Offer **Reload latest** and keep Cancel available.
- On success, close the dialog, announce the save, and update dashboard/detail/list state immediately.
- Opening sets focus on Status; closing returns focus to the invoking control.

### Async and responsive states

- Dashboard ships loading skeleton, error with Try again, empty with New tailoring, and populated states.
- Search/filter with zero matches has a separate “No applications match” state and Clear filters action.
- Untrusted company, role, URL label, and notes content is rendered with `textContent` only.
- Keep existing 44-pixel targets, visible focus rings, light visual tokens, responsive behavior, and reduced-motion handling.
- Desktop uses a compact data table. Mobile uses stacked rows; do not squeeze the desktop table horizontally.

## Implementation Boundaries

The expected change is contained within the web adapter and its static client:

- `resume_tailor/web/models.py`: application enums and strict public/private request/response models.
- `resume_tailor/web/jobs.py`: persistence, concurrency, CSV projection, and SSE publication.
- `resume_tailor/web/app.py`: list, update, and CSV routes plus event allowlisting.
- `static/index.html`, `static/app.js`, and `static/app.css`: dashboard, editor, state handling, and responsive presentation.
- Web model, registry, endpoint, CSV, and UI tests.

Do not modify tailoring-core models, prompts, rendering, fit recovery, provider scheduling, or CLI behavior.

## Verification

### Model and persistence tests

- A legacy job file without tracking metadata remains visible in normal history, reports tracking unavailable, and is excluded from dashboard and CSV without an eager disk rewrite.
- A changed record survives registry and application restarts.
- Applied without a supplied date receives the server-local current date.
- Applied to Not applied clears the date but preserves URL and notes.
- Identical updates do not change revision or updated timestamp.
- Failed atomic writes leave valid prior state readable.

### API tests

- List response returns only web jobs, newest first, with accurate summary counts.
- Valid updates return 200 and increment revision once.
- Identical replay returns 200 without another increment.
- Conflicting stale revision returns an RFC 9457 409.
- Unknown job returns 404.
- Unknown fields, invalid status/date/URL, embedded URL credentials, oversized notes, and invalid revisions return 422.
- Existing job list/detail clients remain compatible with the additive application field.
- Successful updates emit exactly one `job_application_updated` event after persistence.

### CSV tests

- Header names and order exactly match this specification.
- Rows exclude CLI jobs and reflect current persisted values.
- Commas, quotes, Unicode, and multiline notes round-trip through a standards-compliant CSV parser.
- Formula-leading cells are neutralized.
- Startup, creation, removal, and update regenerate the derived file.
- Download headers, media type, and filename are correct.

### UI tests

- Dashboard renders loading, error, empty, populated, filtered, searched, and no-match states.
- Summary counts and filters update after a save and after an SSE event.
- Both detail and dashboard entry points open the same populated editor.
- Date defaulting and clearing follow status changes.
- Validation timing, duplicate-submit prevention, request-failure preservation, conflict recovery, focus return, and live announcements work.
- Company, role, URL, and notes never enter an HTML rendering sink.
- Desktop and mobile screenshots confirm table-to-stacked-row adaptation.

### Regression gate

Run:

```bash
.venv/bin/python -m pytest -q -m "not integration"
.venv/bin/python -m pytest -q -m integration
node --check static/app.js
git diff --check
```

The non-integration suite must make no live Gemini calls. The existing PDF integration test may retain its current environment requirements.

## Acceptance Criteria

- Every trackable web job visibly shows Applied or Not applied; legacy jobs remain only in normal job history.
- A user can edit status, applied date, posting URL, and notes from either the job view or Applications dashboard.
- Tracking updates survive refresh and server restart without changing tailoring artifacts.
- The Applications dashboard aggregates all trackable web jobs and supports search and status filtering without inventing dates for legacy runs.
- Downloaded and on-disk `applications.csv` represent the same current persisted records.
- Concurrent stale edits are detected instead of silently overwriting newer data.
- CSV formula injection, malformed input, and raw HTML rendering are prevented.
- Existing queue, fit-recovery, artifact, CLI, and pipeline behavior remains unchanged.
- No dependency, database, frontend framework, or additional model call is introduced.
