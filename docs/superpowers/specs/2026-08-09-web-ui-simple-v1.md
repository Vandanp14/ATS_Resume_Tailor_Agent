# ATS Resume Tailor Agent — Queue-Enabled Web UI v1

**Date:** 2026-08-09

**Status:** Implementation-ready handoff

**Related design:** `docs/superpowers/specs/2026-08-09-web-ui-design.md`

This is the authoritative v1 specification. Where it conflicts with the related design, earlier drafts, or the current one-shot web implementation, this document wins. The implementer must not combine conflicting behavior from those sources.

## Goal

Replace the manual workflow:

```text
Create JD files → save them → run CLI commands one at a time → search output folders
```

with:

```text
Open the local web app → paste and queue JDs → watch each run → preview the result
→ find every application-ready PDF together in resumepdfs/
```

The web app is an adapter around the existing tailoring system. These remain unchanged:

- `master.json` and its loading and validation rules.
- `TailorPipeline.run(master, jd_text, out_dir, no_pdf, job)`.
- JD parsing, evidence selection, rewriting, truth validation, holistic review, one-page fitting, and rendering.
- Prompt templates and model parameters.
- The existing provider, schema-validation retry, quota, and error behavior inside the pipeline.
- The `tailored.json`, `match_report.json`, `resume.tex`, `resume.pdf`, `.done`, and diagnostic artifact contract.
- CLI and batch commands.

The web layer adds no Gemini calls to an individual tailoring run. It only schedules the existing calls safely across queued runs.

## Product Rules

- A user may add more JDs while another job is running.
- Jobs run one at a time in first-in, first-out order.
- Queue order is fixed. Waiting jobs may be removed but not reordered.
- The queue may be paused and resumed. Pausing prevents the next job from starting; it does not interrupt the running job.
- Waiting jobs and paused state survive a server restart.
- An interrupted running job becomes failed after restart and is never automatically rerun.
- Ordinary job failures do not stop later jobs.
- A Gemini quota or `429 ResourceExhausted` failure pauses the queue.
- The UI never automatically retries an entire pipeline, scores, analyzes, summarizes, or improves a completed resume.
- Bridge skills remains off by default and uses only the pipeline's existing optional bridge-planning call.
- ATS scoring stays outside the web app. Continue using `score_outputs.py` when it is needed.

## Deliberately Excluded

Do not implement these in v1:

- A database or external queue service.
- Parallel tailoring jobs or parallel Gemini requests.
- Mid-run cancellation.
- Drag-and-drop queue reordering.
- Automatic retry of a failed pipeline.
- A web scoring endpoint, score subprocess, or cross-project evaluator import.
- Authentication, remote hosting, or multiple users.
- Browser editing or selection of the master resume.
- JD URL fetching, clipboard monitoring, or file uploads.
- Preflight token-count requests or locally estimated token accounting.
- Tracking Gemini traffic created by the CLI, another process, or another API key.
- A Finder-launching or arbitrary-path folder action.
- A frontend framework, Node.js toolchain, bundler, or component-library dependency.

## Architecture

```text
Browser
  ├── Add JD form
  ├── FIFO queue and recent runs
  ├── selected-job progress and preview
  └── rolling Gemini call tracker
          │
          ▼
FastAPI web adapter
  ├── persistent queue registry
  ├── one worker loop
  ├── one process-wide Gemini scheduler
  ├── persistent job metadata and progress journals
  └── one application SSE stream
          │
          ▼
existing TailorPipeline.run(...)
          │
          ├── output/<job-id>/        all original run artifacts
          └── resumepdfs/<name>.pdf   application-ready PDF copy
```

Keep responsibilities narrow:

| Area | Responsibility |
|---|---|
| Entrypoint | Parse validated server, queue, rate, and output settings; bind Uvicorn to `127.0.0.1`. |
| Web application | API routes, security headers, static frontend, typed errors, and app-wide event stream. |
| Queue registry | Persistent FIFO state, one worker loop, job lifecycle, restart hydration, and output history. |
| Gemini scheduler | Process-wide pacing, rolling-minute accounting, persistence of recent call timestamps, and tracker snapshots. |
| Progress reporter | Convert existing `ProgressEvent` values into job events and notify the application stream. |
| Static frontend | Form, queue, tracker, progress, artifact preview, and responsive behavior. |

Do not build a generic task framework. The queue supports this one local tailoring workflow only.

## Dependencies and Startup

Keep these exact direct dependencies:

```text
fastapi==0.141.1
uvicorn==0.52.1
httpx==0.28.1
```

The installed Pydantic version remains `2.12.5`. FastAPI provides request validation, native SSE, and static serving. HTTPX is the direct test dependency for FastAPI's test client.

Run:

```bash
.venv/bin/python webapp.py
```

The entrypoint accepts:

| Argument | Default | Meaning |
|---|---:|---|
| `--master` | `master.json` | Existing master resume. |
| `--output-dir` | `output` | Original per-job artifacts. |
| `--pdf-dir` | `resumepdfs` | Flat library containing PDF copies only. |
| `--state-dir` | `.resume-tailor` | Private queue and scheduler state. |
| `--model` | existing `DEFAULT_MODEL` | Existing pipeline model. |
| `--call-interval` | existing `DEFAULT_CALL_INTERVAL` (`4.5`) | Minimum seconds between web-app Gemini attempts. |
| `--max-calls-per-minute` | `15` | Web-app rolling 60-second request cap. |
| `--max-input-tokens-per-minute` | `250000` | Rolling 60-second cap based on Gemini-reported input-token usage. |
| `--max-requests-per-day` | `500` | Web-app request cap for the current Pacific-time day. |
| `--port` | `8000` | Local HTTP port. |

Validate that intervals are non-negative, the per-minute cap is positive, and configured directories are not files. The host is always `127.0.0.1` and there is no public-host option.

Load and validate the master once at startup. A missing or invalid master stops startup with a clear terminal error. Missing Tectonic does not prevent startup; metadata reports PDF generation unavailable and the UI preselects and locks **Skip PDF**.

## Job Identity, Metadata, and Persistence

Generate one server-owned UUIDv4 `job_id` for every accepted request. Never use company, role, or JD text as a directory name.

Each job has:

- Required company: trimmed, 1–80 characters.
- Required role: trimmed, 1–80 characters.
- Required JD text: trimmed, 1–100,000 characters.
- Bridge-skills and Skip-PDF options.
- State: `queued`, `running`, `completed`, or `failed`.
- Queue position when waiting.
- Created, started, and finished timestamps.
- Safe terminal message and export warning when applicable.
- Original artifacts and PDF-library metadata.

Persistence uses application-owned JSON only:

```text
.resume-tailor/
  queue/
    <job-id>.json              private queued request, including JD text
  queue_state.json             running or paused
  gemini_calls.jsonl           recent web-app attempt and input-token records

output/<job-id>/
  web_job.json                 metadata; never raw JD text
  web_events.jsonl             ordered progress events
  resume.pdf                   original pipeline PDF
  resume.tex
  tailored.json
  match_report.json
  diagnostic_report.json       when produced
  .done
```

Queue payloads use private permissions: state directories `0700` and request files `0600` where the platform supports them. Write complete JSON through an exclusive temporary sibling followed by atomic replacement. Never use a fixed or shared system-temp path.

When the worker claims a queued job, it reads the validated request, transitions the job to running, and removes the queued request only after the data is safely in memory and metadata is persisted. A process crash during that run produces an interrupted failed job on restart. Unclaimed queued files remain in FIFO order.

Persist queue pause state. On startup:

- Preserve the prior paused state.
- Hydrate queued requests in `created_at`, then UUID, order.
- Mark persisted running jobs failed with an interrupted-run message.
- Resume waiting jobs automatically only when the queue is not paused.
- Recover completed and failed history from `output/`.
- Include compatible CLI-created output directories as artifact-only history.

## FIFO Worker and Failure Policy

Use one long-lived worker loop and a condition/event to wake it. Do not create one worker thread per POST.

For each job:

1. Claim the FIFO head only when the queue is running and no job is active.
2. Persist `running` state before making any Gemini call.
3. Emit exactly one `job_started` event.
4. Create the pipeline with the configured model, the shared scheduled provider, the web reporter, and the requested Bridge-skills value.
5. Call the existing pipeline once with the pasted JD and job output directory.
6. Treat return code `0` as completed and nonzero as failed.
7. On success, create the PDF-library copy when PDF generation was requested.
8. Emit exactly one `job_completed` or `job_failed` event and persist terminal state.
9. Release active ownership in `finally`, then consider the next queue item.

Do not wrap `TailorPipeline.run()` in an adapter retry. A retry could repeat several successful Gemini calls.

After an ordinary validation, rendering, or pipeline failure, continue to the next waiting job. On a Gemini `429` or recognized quota-exhaustion exception:

- Mark the current job failed with a safe quota message.
- Persist the queue as paused.
- Leave all waiting jobs queued and unchanged.
- Require the user to press **Resume queue** after the quota is available again.

## Global Gemini Scheduler and Tracker

The existing `RatePacer` belongs to one pipeline instance, so it resets between jobs. The web adapter therefore injects one shared scheduled provider into every web pipeline. CLI and batch behavior remain unchanged.

Before forwarding each Gemini request, the shared scheduler waits until all known conditions are true:

1. At least `--call-interval` seconds have elapsed since the previous web-app attempt.
2. Fewer than `--max-calls-per-minute` attempts occurred in the previous rolling 60 seconds.
3. Gemini-reported input tokens in the previous rolling 60 seconds are below `--max-input-tokens-per-minute`.
4. Fewer than `--max-requests-per-day` attempts were made since midnight in `America/Los_Angeles`.

Record an attempt ID and timestamp immediately before forwarding the request. Failed outbound attempts still count toward RPM and RPD. After a Gemini response, attach `usage_metadata.prompt_token_count` to that attempt; do not add a separate token-count request. Persist enough history for the rolling minute and current Pacific day, and reload it on startup so a restart cannot reset a safety window.

TPM accounting is deliberately response-based. A request can cross the TPM ceiling because its exact input-token count is not known until Gemini responds; once the observed total reaches the ceiling, subsequent calls wait for enough recorded usage to leave the rolling window. Missing response metadata is represented as incomplete accounting instead of an invented estimate.

The tracker snapshot contains:

```json
{
  "provider": "gemini",
  "window_seconds": 60,
  "requests_in_minute": 7,
  "requests_per_minute_limit": 15,
  "input_tokens_in_minute": 118400,
  "tokens_per_minute_limit": 250000,
  "requests_today": 81,
  "requests_per_day_limit": 500,
  "token_usage_complete": true,
  "minimum_interval_seconds": 4.5,
  "next_allowed_at": "2026-08-09T14:20:31.250Z",
  "day_resets_at": "2026-08-10T07:00:00.000Z",
  "wait_reason": "interval",
  "state": "waiting"
}
```

Allowed tracker states are `ready`, `waiting`, and `paused`; wait reasons are `interval`, `rpm`, `tpm`, and `rpd`. The browser derives its countdown from `next_allowed_at`; the server does not emit one event per second.

The UI labels this as project quota usage recorded by this web app. It cannot see Gemini requests made by the CLI, another process, or another API key, and it does not claim to measure spending. The configured ceilings are 15 RPM, 250,000 input TPM, and 500 RPD; the RPD window resets at midnight Pacific.

For a non-Gemini provider, show the provider name and **Gemini tracker inactive** instead of a misleading zero quota.

## PDF Library

The pipeline continues to write its original `output/<job-id>/resume.pdf`. After a successful PDF run, copy it to:

```text
resumepdfs/<Company> - <Role> - <YYYY-MM-DD> - <job-id-first-8>.pdf
```

Example:

```text
resumepdfs/Stripe - Backend Engineer - 2026-08-09 - a41fd392.pdf
```

Filename rules:

- Preserve company and role exactly in UI metadata.
- For the filename only, replace path separators and control characters, collapse whitespace, trim trailing dots and spaces, and substitute `Untitled` if sanitization empties a component.
- The UUID suffix makes every target collision-safe; never overwrite an existing library file.
- `resumepdfs/` contains `.pdf` files only. JSON, TeX, reports, journals, and markers remain in `output/<job-id>/`.
- Skip-PDF jobs do not create a library entry.

Copy, do not move, the original PDF. This preserves CLI compatibility, completion checks, and the existing artifact contract.

If copying fails after tailoring succeeds:

- Keep the job state `completed`.
- Keep the original `output/<job-id>/resume.pdf` available for preview and download.
- Persist and display a non-terminal PDF-library export warning.
- Do not rerun rendering or the pipeline.

## API Contract

All errors use `application/problem+json`. Unknown fields are rejected. API writes require same-origin JSON.

### `GET /api/meta`

Returns readiness, master name and email only, model/provider, PDF availability, queue state, active job ID, configured directory labels, and the current tracker snapshot. It never returns the master document, JD text, API keys, environment values, or arbitrary filesystem contents.

### `POST /api/jobs`

Requires an `Idempotency-Key` UUID header.

```json
{
  "company": "Stripe",
  "role": "Backend Engineer",
  "jd_text": "full pasted job description",
  "bridge_skills": false,
  "no_pdf": false
}
```

Returns `202`:

```json
{
  "job_id": "uuid",
  "state": "queued",
  "queue_position": 3,
  "status_url": "/api/jobs/uuid",
  "events_url": "/api/events"
}
```

An active job does not cause `409`; the new job joins the queue. Identical replay with the same key returns the original response. Reusing a key with different fields returns `422`. An in-progress identical key returns `409`. Validation failures do not reserve a key.

### `GET /api/queue`

Returns queue state, active job ID, ordered waiting jobs, queue count, and tracker snapshot. It never includes JD text.

### `POST /api/queue/pause` and `POST /api/queue/resume`

Pause or resume future job starts and return the updated queue snapshot. Pause does not interrupt a running job. Both operations are idempotent.

### `DELETE /api/jobs/{job_id}`

Deletes only a queued job and its private queued request, then returns `204`. Running, completed, or failed jobs return `409`. Unknown UUIDs return `404`.

### `GET /api/jobs`

Returns active, queued, completed, failed, and compatible CLI-created runs without JD text. Each entry includes company, role, state, queue position where applicable, timestamps, current stage, safe message, artifacts, PDF-library name, and export warning.

### `GET /api/jobs/{job_id}`

Returns the complete safe job snapshot and recorded progress events. Unknown UUIDs return `404`.

### `GET /api/events`

Uses FastAPI's native `EventSourceResponse` as the single live stream for:

- `queue_changed`
- `job_started`
- Existing pipeline stage, retry, warning, and detail event kinds
- `job_completed`
- `job_failed`
- `tracker_changed`

Job-specific events include `job_id`. Event IDs are monotonic for the server process. On connection or reconnection, the frontend first fetches authoritative queue and job snapshots, then applies newer live events and ignores duplicate IDs. Built-in keepalive is sufficient.

### `GET /api/jobs/{job_id}/files/{artifact}`

Allow only:

```text
resume.pdf
resume.tex
tailored.json
match_report.json
diagnostic_report.json
```

Map names to the server-owned job directory. Never join arbitrary client paths. `resume.pdf?download=0` is inline for preview; downloads use attachment disposition. The original job PDF is authoritative for this route even when a PDF-library copy exists.

There is no `/score` route.

## UI Layout

Use a light, high-contrast **Precision Tool** variant that is intentionally distinct from the dark Vandan defaults: warm off-white canvas, white working surfaces, a dark slate job rail, near-black text, and one restrained cool-blue action color. Use system/SF typography, tabular numerals for quota and timing data, compact controls, and consistent 10–18 px radii. Do not use gradients, glass surfaces, AI icon clichés, decorative card grids, or oversized landing-page spacing.

### Desktop: two-pane workspace

Use the full viewport without horizontal overflow:

1. **Job rail — fixed 280 px dark pane**
   - One dominant **New tailoring** action.
   - Compact queue health with Pause/Resume only when a job is active, waiting, or the queue is paused.
   - Queue/Recent segmented filter rather than two simultaneous lists.
   - Active job first, then waiting jobs in numbered FIFO order.
   - Waiting rows expose a separate Remove button; rows never contain nested interactive controls.

2. **Work canvas — remaining light pane**
   - With no selection, show one calm empty state and one **New tailoring** action.
   - For a selected job, show company, role, state, elapsed time, current stage, and any safe warning in a compact overview.
   - Use accessible tabs for **Progress**, **Resume Preview**, and **Files**.
   - Progress contains the existing 13 stages plus the optional Bridge-skills stage, with retries, warnings, and expandable verbose details.
   - Resume Preview embeds the finished PDF or safely renders structured resume data when PDF generation was skipped.
   - Files contains the application-ready PDF as the dominant download and TeX, JSON, report, or diagnostic files as secondary actions.

The JD form is not a permanent pane. **New tailoring** opens a native modal drawer: a 520 px right-side panel on desktop and a full-screen task on mobile. This removes the empty form from the normal monitoring workflow while keeping repeated pasting one action away.

The top bar contains product identity, master identity, model/provider, server/PDF status, and a compact Gemini tracker. The collapsed tracker shows RPM, such as `7/15`; its disclosure shows RPM, observed input TPM, and RPD progress plus the next-allowed or daily-reset explanation. It is operational status, not a decorative chart.

### Selection and repeated-paste flow

- On load, select the active job; otherwise select the newest completed or failed run.
- Clicking a queue/history row selects it in the work canvas.
- Adding another JD never steals detail focus from the active job after enqueue.
- After successful enqueue, clear Company, Role, and JD, preserve Advanced-option choices, close the drawer, and announce the queue position in an `aria-live="polite"` region.
- On failed submission, preserve every entered value, show the inline error, and re-enable the button.

### Mobile

Do not squeeze the desktop panes. At widths below 768 px, render one full-width task at a time:

- Jobs is the default screen and contains the queue/recent rail.
- Selecting a job opens its full-width detail screen; a visible Back to jobs action restores the list.
- New tailoring is a full-screen native dialog with a sticky action footer.
- The compact top bar retains the Gemini tracker.
- Use at least 44 px targets and never require hover.

### Form behavior

This is a short form, so use inline errors only:

- Show visible Company, Role, and Job description labels plus one-line JD help.
- Keep Bridge skills and Skip PDF inside a collapsed Advanced options disclosure.
- Validate each field on blur and submit; after a field first errors, revalidate it on input.
- Reserve error-slot height to prevent layout shift and use `aria-describedby` and `aria-invalid`.
- Empty JD copy: “Paste the job description you want to tailor this resume for.”
- Disable the button only while enqueue is in flight and show **Adding…**.
- Guard against double submission in the browser and through the server idempotency key.
- Rely on native dialog focus trapping and return focus to the opener when the dialog closes.

### Queue, tracker, and preview states

Queue, tracker, selected job, preview, and history each implement loading, error, empty, and success states.

- Queue empty: “No queued jobs” and a direct **New tailoring** action; do not show Pause when there is nothing to pause.
- Queue paused: persistent warning row with **Resume queue**.
- Quota paused: explain that waiting jobs are safe and no new calls will start.
- Preview pending: show the job progress state, not a blank iframe.
- Preview unavailable because Skip PDF was selected: render `tailored.json` through safe DOM creation.
- Export warning: explain that the PDF remains available from the job even though its library copy failed.

Abort stale fetches when selection changes. Open one application EventSource, close it on teardown, and refetch snapshots after reconnect. Insert all server, JD, company, role, report, and error values with `textContent` or element properties, never `innerHTML`.

Use `aria-live="polite"` for normal queue and stage updates and `role="alert"` for actionable failures. Provide a skip link, semantic landmarks, native controls, visible focus rings, arrow-key tab navigation, and `prefers-reduced-motion` static end states.

## Security and Prompt-Injection Boundary

- Bind only to `127.0.0.1` and do not enable CORS.
- Validate every API body with strict Pydantic models and explicit field allowlists.
- Keep Gemini credentials and full master data server-side.
- Use server-generated UUIDs and artifact allowlists.
- Return safe browser errors and log technical details only to the terminal without JD text or secrets.
- Enforce `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy`, same-origin CSP with `object-src 'none'`, and `Cache-Control: no-store` on API and sensitive artifact responses.
- Use `frame-src 'self'` for the PDF iframe rather than weakening `object-src`.
- Never render untrusted values as HTML.
- Never pass user input to a shell, dynamic import, `eval`, or filesystem path.

The application must not scan, index, summarize, import, execute, or treat instructions from `/tmp`, `$TMPDIR`, or any other system temporary directory as application input.

Only these sources may influence a run:

- The configured master file loaded through the existing schema.
- A queued request created and schema-validated by this application.
- Existing application prompt templates and configuration.

Treat JD, company, and role values as untrusted data. JD text is passed only as the existing pipeline's JD input. The web adapter must not reinterpret embedded text as configuration, tool commands, paths, URLs, or agent instructions.

Queue hydration reads only server-generated UUID filenames beneath the resolved state directory, rejects symlinks and unexpected schemas, and never loads arbitrary adjacent files. Tests use pytest `tmp_path`, never a fixed `/tmp/webtest_output` directory.

## Implementation Boundaries

Expected implementation areas are:

- Local server entrypoint and dependency pins.
- Web API, queue registry, shared Gemini scheduler, event reporter, and strict models.
- Static HTML, JavaScript, and CSS.
- Focused web, queue, scheduler, persistence, artifact, and UI contract tests.
- README web quickstart only after implementation is verified.

Do not modify:

- `master.json`.
- Prompt templates.
- Evidence, assembly, validation, review, rendering, or scoring behavior.
- Existing CLI or batch semantics.

If a shared provider must be injected, use the pipeline's existing provider seam. The standard CLI and batch construction paths retain their current pacing behavior.

## Test Plan

### Queue and lifecycle

- Multiple rapid submissions return distinct queued jobs in FIFO order.
- Simultaneous identical submissions with one idempotency key create one job.
- Exactly one pipeline executes at a time.
- Pause prevents the next start but does not interrupt the active job.
- Resume starts the FIFO head.
- Removing a queued job deletes only its private request.
- Ordinary failure continues; quota failure pauses and preserves waiting jobs.
- No adapter path calls `TailorPipeline.run()` more than once per job.
- Restart restores queued order and pause state, marks an interrupted active job failed, and never reruns it.

### Gemini scheduler

- Use a fake clock and fake provider; tests never sleep or call Gemini.
- Enforce at least 4.5 seconds between attempts.
- Enforce no more than 15 attempts in any rolling 60 seconds.
- Gate follow-up attempts after observed input usage reaches 250,000 tokens in a rolling 60 seconds.
- Enforce no more than 500 attempts in a Pacific-time day and calculate the daylight-saving-safe midnight reset.
- Mark token usage incomplete when Gemini omits usage metadata; never substitute an estimate.
- Preserve pacing across two different pipeline/job instances.
- Count failed attempts toward RPM and RPD.
- Count SDK-level transport retries by invoking the scheduler immediately before every provider attempt.
- Reload recent attempts and token usage after restart and delay the next call correctly.
- Publish accurate ready, waiting, and paused snapshots without per-second server events.
- Non-Gemini providers render the tracker inactive.

### Artifacts and PDF library

- Successful PDF runs retain every original artifact and create exactly one named PDF-library copy.
- Company and role sanitization prevents traversal and control-character filenames.
- UUID suffixes prevent overwrites.
- `resumepdfs/` receives no JSON, TeX, journal, or marker files.
- Skip-PDF jobs create no library entry.
- Copy failure preserves completed state and original PDF while recording a warning.
- Inline preview, attachment download, missing files, unknown artifacts, and traversal attempts behave correctly.

### API, security, and UI

- Validate missing, blank, oversized, wrong-type, and unknown fields.
- Verify idempotency replay and conflict behavior.
- Verify private queue permissions, atomic state writes, symlink rejection, and no system-temp scanning.
- Verify host/origin/content-type guards and problem responses.
- Verify the two-pane desktop structure, native new-job drawer, accessible detail tabs, and task-switched mobile structure.
- Verify visible labels, inline error timing, focus behavior, preserved values, status announcements, tracker copy, safe text rendering, reduced motion, and 44 px targets.
- Verify loading, error, empty, and success for every async region.
- Verify snapshot refetch, single EventSource use, duplicate-event handling, and reconnect behavior.

Run:

```bash
.venv/bin/python -m pytest -q -m "not integration"
```

After automated verification, manually queue at least three existing JDs, add the second and third while the first is running, pause and resume the queue, refresh the browser, restart the server with one job waiting, preview completed PDFs, inspect `resumepdfs/`, and exercise keyboard and mobile layouts. Manual runs should use an explicit low-cost test allowance because they make real Gemini calls.

## Acceptance Criteria

- A user can paste several JDs without creating JD files or repeatedly invoking the CLI.
- Jobs run in persistent FIFO order with one active pipeline and no parallel Gemini calls.
- Gemini attempts are globally spaced by at least 4.5 seconds and capped across web jobs at 15 RPM, 250,000 observed input TPM, and 500 RPD resetting at midnight Pacific.
- The UI shows an honest web-app-only call tracker and pauses safely on quota failure.
- Company and role make queue entries and PDFs recognizable without another Gemini call.
- Every completed PDF is easy to find in `resumepdfs/`, while original job artifacts remain compatible in `output/<job-id>/`.
- PDF preview and downloads work from the selected job.
- `master.json`, core tailoring logic, prompts, CLI, and batch behavior remain unchanged.
- The web layer performs no automatic scoring or whole-pipeline retry.
- Queue persistence cannot load arbitrary temporary or attacker-named files.
- Existing non-integration tests and the new web suite pass without live model calls.
