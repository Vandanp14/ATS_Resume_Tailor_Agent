# Dashboard cleanup: design

Date: 2026-10-22
Status: approved by user; not built. Resume together with a broader UI pass.
Mockup: `.superpowers/brainstorm/75948-1792624952/content/cleanup.html`

## Why

The job list shows 11 old command-line runs (`output/cisco`, `uber`,
`product_swe_disney`, `uiux_developer_utah_university`, ...) that cannot be
opened: `resume_tailor/web/jobs.py:446-461` adds every `output/` folder without
`web_job.json` as a "CLI run" (with `created_at` = app start, so they jump to
the top), while `job_or_404` (`resume_tailor/web/app.py:337`) accepts only
UUID job ids, so the detail view shows "Unknown job". Deleting is only
possible for queued jobs (`app.py:573`). The user wants the list to reflect
live, openable jobs only, and a manual way to delete old jobs and free space.
Disk use is small (`output/` 4.5 MB, `resumepdfs/` 1.4 MB); this is mostly
about clutter. The user downloads PDFs elsewhere right away, so deleting app
copies is safe for them.

## Decisions (user's)

1. Broken legacy entries disappear from the dashboard.
2. Manual cleanup with checkboxes: individual jobs or select all. No
   age-based or automatic deletion.
3. Deleting a job removes everything related to it: its `output/<job_id>/`
   folder (PDF, .tex, reports, events, checkpoints), its copy in
   `resumepdfs/`, its saved request (`.resume-tailor/requests/<id>.json`) and
   any queue payload.

## Design (from the approved mockup)

- **Hide legacy runs:** stop hydrating folders without `web_job.json` into the
  job list. Their folders stay on disk until cleaned.
- **Select mode:** a "Select" toggle on the job list (Recent view). Checkbox
  per finished/failed job, "Select all finished (N)", running jobs disabled,
  queued jobs keep their existing remove action. A separate checkbox
  "Old command-line folders (N)" lists the legacy folders for deletion. A red
  "Delete N selected" button.
- **Confirm dialog** before any delete: lists the jobs, says what is removed
  and that it can't be undone, shows approximate space freed.
- **Single delete:** "Delete job" button on a finished/failed job's page, same
  confirm.

## Designer's calls (unconfirmed by user)

- Selection resets after each delete; the list updates live (no reload).
- Deletion only touches paths inside the app's own folders (`output/`,
  `resumepdfs/`, `.resume-tailor/`); resolve paths and refuse symlinks or
  anything outside those roots.
- The PDF-library copy is found via the job's persisted `pdf_library_name`.

## Left to the builder

- API shape (e.g. `POST /api/jobs/delete` with ids + `include_legacy`).
- Exact placement/styling, to be folded into the upcoming UI overhaul
  (follow `docs/llm-guides/skills/vandan-ui-system.md`).
