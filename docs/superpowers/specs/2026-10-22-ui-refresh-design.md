# UI refresh and dashboard cleanup: design

Date: 2026-10-22
Status: approved in brainstorming; supersedes the layout parts of
`2026-10-22-dashboard-cleanup-design.md` (its cleanup decisions still hold
and are restated here).
Mockups (open in a browser): `docs/superpowers/specs/mockups/2026-10-22-ui-refresh/`
- `direction-a-v2.html`: approved look for start / running / done
- `history.html`: top bar, skill check inside the form, history
- `delete-flow.html`: approved delete process, four frames
- `skill-check-original.html`: the chip behaviour already shipped (layout B)

## Why

The user wants a fresh, tasteful look built around how they actually use the
app, and a clean dashboard: the job list today shows 11 old command-line runs
that cannot be opened, and finished jobs cannot be deleted. Design direction
comes from the `frontend-design` skill, **not** `vandan-ui-system` (user's
explicit choice for this project).

## The user's flow (theirs)

Paste the job description, enter company and role → answer the skill check if
asked → run → watch progress → download the PDF → apply elsewhere → later,
delete old jobs. They sometimes read the review but want a short summary
(keyword coverage) and clearly worded flagged qualifications instead of the
current detail-heavy panels.

## Goals

1. "New resume" is the home screen, not a dialog.
2. While running, progress is the main thing on screen.
3. When done, a short summary and a prominent **Download PDF**, next to a
   preview of the resume page.
4. Old command-line runs disappear from the list.
5. Manual cleanup: checkboxes for individual jobs or all finished; delete
   removes everything tied to a job; confirm before deleting.

## Non-goals

- No change to tailoring logic, prompts, models, or the PDF template.
- No automatic or age-based deletion.
- No new frameworks: stays vanilla HTML/CSS/JS served by FastAPI from `static/`.
- Not using `vandan-ui-system` (no dark-first, no Linear look).

## Anti-goals

- Any extra click between pasting the job description and getting the PDF.
- Losing an existing capability: skill check, college posting, model provider,
  Skip PDF, bullet review and fit-recovery pauses, resume a failed run, tailor
  again, files, quota display, sign-in.
- Deleting anything outside the app's own folders, or deleting without confirm.

## Visual system (approved: layout from mockup A, colors from mockup B)

- Colors: background `#F2F2F0`; surfaces `#FBFBFA`; page/paper and inputs
  `#FFFFFF`; ink/text `#1B1B1F`; muted text `#55554E` / `#77776F`; hairlines
  `#DEDED9` / `#E6E6E1`; green for done and Download `#0E7C55` (soft `#E3F2EB`);
  amber for "look at this" `#FFF1D6` with text `#5C3800`/`#7A4A00`; red for
  failed and delete `#9A2A1F` (soft `#FBE7E5`).
- Type: Instrument Sans for the interface; Source Serif 4 for the resume-page
  preview (Google Fonts). Sentence case; no all-caps labels.
- Buttons: pill-shaped. Primary "Tailor resume" is ink black; "Download PDF" is
  green; destructive actions are red.
- Light theme only for this pass (the current app is light; the mockups are light).

## Screens

### Top bar
App name; a two-way switch **New resume / History (N)**; Gemini usage shown
quietly on the right; sign out. Replaces the left job rail. While a job runs,
a small status line shows in the top bar so the user can leave and come back.

### New resume (home)
Two columns (stack on mobile): left, the form (job description, company, role,
**Tailor resume**); right, a blank resume page. **Check skills** behaviour stays
as shipped: after the check, the chip panel ("Do you know these? N not on your
resume") appears inside the form and the button becomes Tailor resume. College
posting, model provider and Skip PDF move to one collapsed **More options** row.
The remembered-skills editor stays reachable there.

### Running
Left: thin progress track across the top, company and role, a plain checklist
of the pipeline stages (done in green, current in bold ink, upcoming muted),
time left, and plain-language notes ("Gemini is busy, so it's using a backup
model"). Right: the resume page "inks in" as stages finish (a visual
progress cue, not the real text). Warnings appear only when they need the user.

### Done
Left: large keyword-coverage percentage with one plain sentence; a green line
when everything the resume states is included; flagged qualifications as amber
notes in plain wording ("Not on your resume: Section 508 / ADA. Tick it in the
skill check if you've done this work."); **Download PDF** (green) and **Delete**.
Right: the real PDF preview. A **Details** link opens the full review, claims to
check, and files. Bullet-review and fit-recovery pauses appear here as the
action the user must take.

### History
A plain list (company, role, date, status tag: Ready / Running / Failed /
Queued). Click opens that job's running or done screen. **Select** enters the
delete flow below.

## Cleanup (unchanged decisions from the cleanup design)

1. Hide legacy runs: stop hydrating `output/` folders without `web_job.json`
   into the job list (`resume_tailor/web/jobs.py:446-461`). They stay on disk
   until deleted.
2. Delete flow (mockup `delete-flow.html`): Select → checkboxes (individual,
   "Select all finished (N)", "Old command-line folders (N)"; running jobs
   disabled; queued jobs keep their existing remove action) → red
   "Delete N resumes" → confirm dialog listing items, what is removed, that it
   can't be undone, and approximate space freed → list updates live with a
   short confirmation note.
3. Single delete: **Delete** on the done screen, same confirm.
4. Deleting a job removes: `output/<job_id>/` entirely, its PDF in
   `resumepdfs/` (`pdf_library_name`), `.resume-tailor/requests/<id>.json`,
   and any queue payload.
5. Safety: resolve paths, refuse symlinks and anything outside `output/`,
   `resumepdfs/`, `.resume-tailor/`; never delete a running job.

## Designer's calls

- **Screen states and routing:** pressing Tailor resume turns the main area
  into that job's running screen (URL hash `#job/<id>`), which becomes its
  done screen when finished. **New resume** in the top bar always shows a blank
  form; **History** shows the list. The top-bar status line links to the
  running job. Deep links and reload keep working through the hash.
- **Summary numbers:** the big percentage is the deterministic
  `keyword_coverage.computed_coverage_pct` labelled "keyword match with the
  posting" (not the model's `coverage_pct`). The green line "Everything your
  resume states is included" shows only when
  `keyword_coverage.missing_supported_terms` is empty. Amber notes: college
  qualification rows with status `unsupported` ("Not on your resume: …") and
  `supported_not_on_page` ("True, but not shown on the page: …");
  `covered_with_substitution` is a neutral grey note. Truth concerns (if any)
  show on the summary in red. Missing must-haves, recommendations, claims to
  check and files live behind **Details**.
- **Progress checklist:** five grouped steps, each done when its last stage
  completes: Read the posting (Preflight, Parse job description, both Research
  stages, Map requirement coverage); Match your experience (Select work,
  Select projects, Plan evidence); Write your resume (Tailor skills, Rewrite
  work, Rewrite projects, Assemble draft); Review (Holistic review, Validate
  review edits, Write summary, Apply bullet review); Fit and save (Render and
  fit one page, Emergency bullet concision, Audit emergency concision, Write
  artifacts). Skipped stages count as done.
- **Time and model notes:** no backend changes; show **elapsed time**, not
  time left (no estimate exists). Existing warning events that say a model is
  "unavailable … falling back to …" or "Every model is busy … waiting" become
  the plain note "Gemini is busy, so it's using a backup model" / "Gemini is
  busy; waiting to retry". Other warnings appear under Details.
- **Other states:** jobs paused for bullet review or fit recovery
  (`action_required`) get an amber **Needs you** tag, open to their action, and
  can be deleted. The queue pause/resume control moves to the top bar next to
  Gemini usage.
- Starting a second job while one runs queues it; it appears in History.
- The full review, files, and logs stay reachable behind **Details**.
- Selection resets after each delete.
- Existing element ids used by tests may change only together with the tests.

## Left to the builder

- API shape for bulk delete (e.g. `POST /api/jobs/delete` with job ids and an
  `include_legacy` flag) and the size estimate.
- How the "inking in" page is drawn (CSS placeholder lines are fine).
- Exact spacing, responsive breakpoints, and motion (respect reduced motion).
- Splitting `static/app.js` (1852 lines) into modules if it helps; no build step.
