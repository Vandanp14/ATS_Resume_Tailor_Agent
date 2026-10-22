# UI Refresh and Dashboard Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the web UI around the user's loop (paste → run → watch → download → clean up) in the approved look, hide unopenable legacy runs, and add manual delete with confirm.

**Architecture:** Backend gets three small changes in `resume_tailor/web/` (no legacy hydration, a cleanup API, two summary fields on the review payload). The frontend stays vanilla HTML/CSS/JS with no build step: pure display logic moves into a new classic script `static/view-model.js` (unit-tested with `node --test`), and `static/index.html`, `static/app.css`, `static/app.js` are rebuilt into three hash-routed views (New resume, Job, History) under a top bar.

**Tech Stack:** Python 3.13 / FastAPI / pytest (`.venv/bin/python -m pytest -q`); vanilla JS (ES2022, classic scripts), Node 22 for `node --test`; Google Fonts Instrument Sans + Source Serif 4.

**Spec:** `docs/superpowers/specs/2026-10-22-ui-refresh-design.md` (mockups in `docs/superpowers/specs/mockups/2026-10-22-ui-refresh/`)

## Global Constraints

- No change to tailoring logic, prompts, models, or the PDF template.
- Vanilla HTML/CSS/JS served from `static/`; no frameworks, no build step; `innerHTML`, `insertAdjacentHTML`, `document.write` stay banned in `app.js` (existing tests).
- Do not use `vandan-ui-system`; follow the spec's visual system exactly:
  background `#F2F2F0`; surfaces `#FBFBFA`; paper/inputs `#FFFFFF`; ink `#1B1B1F`; muted `#55554E` / `#77776F`; hairlines `#DEDED9` / `#E6E6E1`; green `#0E7C55` (soft `#E3F2EB`); amber `#FFF1D6` with text `#5C3800`/`#7A4A00`; red `#9A2A1F` (soft `#FBE7E5`). Instrument Sans (UI), Source Serif 4 (resume page). Pill buttons: primary ink black, Download green, destructive red. Light theme only. Sentence case, no all-caps labels.
- Every existing capability survives: skill check + remembered skills, college posting, model provider, Skip PDF, Bridge skills, Research company, bullet review and fit-recovery pauses, resume a failed run, tailor again, files, log, quota display, queue pause/resume, sign out.
- Delete only inside `output/`, `resumepdfs/`, `.resume-tailor/`; refuse symlinks; never delete a running job; always confirm in the UI.
- Keep the accessibility floor the current CSS has: `:focus-visible` styles, `prefers-reduced-motion`, `100dvh`, labelled controls, `role="alert"`/`aria-live` regions (existing tests assert these).
- Full suite green after every task: `.venv/bin/python -m pytest -q` (includes the node tests via Task 3's wrapper).

## Review Focus

1. **Reload / deep link on a job hash** (`#job/<id>` for a finished, running, failed, or deleted job): reload shows that job's screen; a deleted or unknown id falls back to History with a plain note, never a blank page. Test in Task 5.
2. **Deleting the job currently on screen** (single delete from the done screen): after confirm, the view moves to History and the stream keeps working. Test in Task 7.
3. **Select all while a job finishes mid-selection:** "Select all finished" counts only jobs finished at click time; a job that was running when selected is rejected by the server (409) and the UI reports which ones were skipped. Test in Task 2 (server) and Task 7 (UI message).
4. **Old reports without `keyword_coverage` or `qualification_coverage`** (jobs from before these features): the done screen shows the model's estimate labelled "estimated", no green line, no notes, and no errors. Test in Tasks 3 and 4.
5. **Narrow screens (≤ 720px):** the two-column screens stack (form/status first, page second), the top-bar switch stays reachable, checkboxes keep ≥ 44px rows. Test in Task 8 (Playwright at 390px).

---

### Task 1: Hide legacy command-line runs

**Files:**
- Modify: `resume_tailor/web/jobs.py:446-461` (remove the CLI-run hydration loop; keep `_cli_state` only if still used elsewhere, else delete it)
- Test: `tests/test_webapp.py`

**Interfaces:**
- Produces: `GET /api/jobs` lists only folders with `web_job.json`.

- [ ] **Step 1: Write failing test** `test_legacy_cli_folders_are_not_listed`: create `output/product_swe_disney/{tailored.json,resume.pdf}` (no `web_job.json`) before building the app with `make_app`; `GET /api/jobs` contains no entry with `job_id == "product_swe_disney"`.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_webapp.py -k legacy_cli -q` — Expected: FAIL.
- [ ] **Step 3: Remove the hydration loop.**
- [ ] **Step 4: Run** the test and the full suite — Expected: PASS.
- [ ] **Step 5: Commit** `fix: stop listing unopenable command-line runs`.

### Task 2: Cleanup API

**Files:**
- Modify: `resume_tailor/web/jobs.py` (new registry methods), `resume_tailor/web/app.py` (routes), `resume_tailor/web/models.py` (request/response models)
- Test: `tests/test_web_cleanup.py` (new)

**Interfaces:**
- Produces:
  - `class CleanupRequest(BaseModel): job_ids: list[str] = Field(default_factory=list, max_length=1000); include_legacy: bool = False` (strict, extra forbid).
  - `class CleanupItem(BaseModel): id: str; label: str; bytes: int`
  - `class CleanupInventory(BaseModel): jobs: list[CleanupItem]; legacy: list[CleanupItem]` — `jobs` covers every deletable web job (states `completed`, `failed`, `action_required`); `label` = "Company, Role".
  - `class CleanupResult(BaseModel): deleted_jobs: list[str]; deleted_legacy: list[str]; skipped: list[CleanupItem]; freed_bytes: int` (`skipped.label` holds the reason, e.g. "Running, can't delete").
  - `GET /api/cleanup` → `CleanupInventory`; `POST /api/cleanup` body `CleanupRequest` → `CleanupResult`.
  - `QueueRegistry.cleanup_inventory() -> CleanupInventory`, `QueueRegistry.delete(request: CleanupRequest) -> CleanupResult`.
- Deleting a job removes `output/<id>/` (recursive), `resumepdfs/<pdf_library_name>` (fallback: any `resumepdfs/*` whose stem ends with ` - <first 8 chars of id>`), `.resume-tailor/requests/<id>.json`, the queue payload; then drops it from the registry and publishes a queue/job-list change event so open pages update. Legacy = `output/*` directories without `web_job.json`.
- Safety: every path is resolved and must stay under its root (`output_dir`, `pdf_dir`, `state_dir`); symlinked dirs/files are skipped (reported in `skipped`), never followed. Queued and running jobs are skipped with a reason.

- [ ] **Step 1: Write failing tests** in `tests/test_web_cleanup.py` (use `make_app` + `fake_factory` from `tests/conftest.py`; complete a job via `create_job` + `wait_for`):
  - `test_inventory_lists_finished_jobs_and_legacy_folders_with_sizes`
  - `test_delete_removes_folder_pdf_copy_and_saved_request` (all three paths gone; `freed_bytes > 0`; job gone from `GET /api/jobs`)
  - `test_delete_legacy_folders_only_when_asked`
  - `test_running_or_queued_jobs_are_skipped_with_reason` (Review Focus 3: response 200 with the id in `skipped`, folder untouched)
  - `test_symlinked_or_outside_paths_are_never_deleted` (a symlink `output/evil -> <tmp>/outside` is reported skipped and `outside` still exists)
  - `test_unknown_ids_are_skipped_not_errors`
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_web_cleanup.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces; keep `DELETE /api/jobs/{id}` (queued removal) unchanged.
- [ ] **Step 4: Run** new tests + full suite — Expected: PASS.
- [ ] **Step 5: Commit** `feat: cleanup API for finished jobs and old folders`.

### Task 3: Summary fields and display logic

**Files:**
- Modify: `resume_tailor/web/review.py` (`read_review` return dict)
- Create: `static/view-model.js`, `tests/js/view-model.test.cjs`, `tests/test_view_model_js.py` (runs node)
- Test: `tests/test_college_mode.py` (review payload), the new files

**Interfaces:**
- Produces in `read_review`: `"keyword_match_pct": float | None` (from `keyword_coverage.computed_coverage_pct`, else None), `"all_stated_included": bool | None` (True when `keyword_coverage.missing_supported_terms` is empty; None when `keyword_coverage` absent).
- Produces in `static/view-model.js` (classic script; defines `globalThis.ViewModel = {...}` and, when `typeof module !== "undefined"`, `module.exports = ViewModel`):
  - `STEP_GROUPS`: the spec's five steps, exact labels "Read the posting", "Match your experience", "Write your resume", "Review", "Fit and save", each with its stage names copied from the spec.
  - `progressSteps(stageStatusFor: (stageName) => "done"|"active"|"pending"|"skipped") -> Array<{label, status: "done"|"active"|"pending"}>` — a step is done when all its stages are done or skipped, active when any stage is active, else pending.
  - `friendlyNote(message: string) -> string | null` — "unavailable … falling back" → "Gemini is busy, so it's using a backup model."; "Every model is busy" → "Gemini is busy; waiting to retry."; else null.
  - `summary(review) -> {pct: number|null, estimated: boolean, allIncluded: boolean, notes: Array<{tone: "amber"|"grey"|"red", text}>}` — `pct` = `keyword_match_pct`, else `coverage_pct` with `estimated: true` (Review Focus 4); notes: qualification rows `unsupported` → amber "Not on your resume: <reason's named terms or line>. Tick it in the skill check if you've done this work." (use the row's `reason` after "not in your resume:" when present, else the line text); `supported_not_on_page` → amber "True, but not shown on the page: <line>"; `covered_with_substitution` → grey "Met through your completed credits: <line>"; each truth violation → red "Check this claim: <claim>".
  - `historyTag(state) -> {text, tone}`: completed → Ready/green, running → Running/ink, failed → Failed/red, queued → Queued/grey, action_required → Needs you/amber.

- [ ] **Step 1: Write failing tests**:
  - pytest `test_review_payload_has_keyword_match_fields` (report with `keyword_coverage` → 55.6 and False/True; old report without it → None/None).
  - `tests/js/view-model.test.cjs` (node:test + node:assert): `progressSteps` all-pending / partial / skipped-counts-done; `friendlyNote` both phrases + unrelated → null; `summary` with full review, with old review lacking both fields (pct from `coverage_pct`, estimated true, no notes); `historyTag` for all five states.
  - `tests/test_view_model_js.py::test_view_model_node_tests` runs `node --test tests/js/` via `subprocess` and asserts return code 0 (skip with `pytest.skip` when `node` is not on PATH).
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_view_model_js.py tests/test_college_mode.py -k "view_model or keyword_match" -q` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — Expected: PASS; full suite green.
- [ ] **Step 5: Commit** `feat: summary fields and view-model for the new UI`.

### Task 4: New shell, visual system, and New resume view

**Files:**
- Modify: `static/index.html`, `static/app.css` (rewrite to the spec's system), `static/app.js` (routing + New resume view), `tests/test_webapp.py` (`test_static_shell_contract` dialog assertion → form assertion)
- Test: `tests/test_webapp.py`, `tests/test_college_mode.py`, `tests/test_fit_recovery_ui.py` (keep green)

**Interfaces:**
- Consumes: `ViewModel` (Task 3), loaded by `<script src="/view-model.js" defer>` before `app.js`.
- Produces:
  - Markup: top bar `<header class="topbar">` with brand, `<nav>` switch buttons `id="nav-new"` / `id="nav-history"` (history label includes count `id="history-count"`), running-job status link `id="topbar-running" hidden`, tracker `id="tracker"`, queue pause/resume `id="pause-btn"`, sign out `id="logout-btn"`. Views: `<main>` with `<section id="view-new">`, `<section id="view-job" hidden>`, `<section id="view-history" hidden>`.
  - `view-new`: two columns `.desk` → left `<form id="job-form">` (keeps ids `jd-text`, `jd-help`, `jd-error`, `company`, `role`, `suggest-details`, `skill-check`, `skill-chips`, `remembered-skills`, `remembered-chips`, `check-skills-btn`, `skip-check-btn`, `enqueue-status`, `clear-draft`), a `<details id="more-options">` "More options" holding provider fieldset, `college-mode`, `bridge-skills`, `research-company`, `no-pdf`; right `<div class="paper" aria-hidden="true">` blank page.
  - `app.js`: `route()` reads `location.hash` (`#new` default, `#job/<id>`, `#history`) and shows exactly one view; `go(hash)` sets the hash. Existing submit flow ends with `go("#job/" + id)` instead of closing a dialog; `openJobDialog/closeJobDialog` and the `new-job-dialog` element are removed.
- `test_static_shell_contract`: replace `<dialog class="new-job-dialog"` with `id="view-new"` and `id="job-form"`.

- [ ] **Step 1: Update/extend tests first:** `test_static_shell_contract` as above; new `test_shell_has_views_and_topbar` asserting the ids listed in Produces exist in `index.html`, `view-model.js` is loaded before `app.js`, and `app.css` contains `#F2F2F0`, `#0E7C55`, `Instrument Sans`, `Source Serif 4`.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_webapp.py -q` — Expected: FAIL on the new assertions.
- [ ] **Step 3: Implement** markup, CSS system (tokens as CSS variables on `:root`), routing, New resume view; keep the skill-check behaviour exactly as shipped.
- [ ] **Step 4: Run** full suite — Expected: PASS.
- [ ] **Step 5: Commit** `feat: new shell, visual system, and home screen`.

### Task 5: Job view (running and done)

**Files:**
- Modify: `static/index.html`, `static/app.css`, `static/app.js`
- Test: `tests/test_webapp.py`

**Interfaces:**
- Consumes: `ViewModel.progressSteps`, `friendlyNote`, `summary` (Task 3); `stageStatus` (existing, `app.js:124`); `/api/jobs/{id}/review` (now with `keyword_match_pct`, `all_stated_included`).
- Produces in `view-job`: left column with `id="job-title"`, progress track `id="job-track"` (5 segments), checklist `id="job-steps"`, elapsed `id="job-elapsed"`, note `id="job-note"`; done summary `id="job-summary"` (big pct `id="summary-pct"`, label "keyword match with the posting" or "estimated keyword match", green line `id="summary-all"`, notes list `id="summary-notes"`), buttons `id="download-pdf"` (green, links to the job's `resume.pdf` artifact) and `id="delete-job"` (red); right column `.paper` that "inks in" (CSS lines filled by step progress) while running and shows the PDF preview (existing preview iframe/object) when done. The existing fit-recovery card (`id="fit-recovery-card"`), bullet-review card, recovery dialogs, Resume run (`id="resume-job"`), Tailor again (`id="duplicate-job"`) stay, shown in the left column as the action when relevant. A `<details id="job-details">` "Details" holds the old Review, Files, and Log panels (keep their ids and behaviour).
- While any job runs, `id="topbar-running"` shows "<Company>: <current step label>" and links to `#job/<id>`; hidden otherwise.
- Unknown/deleted job id on `#job/<id>` → `go("#history")` with the note "That resume no longer exists." in `id="history-note"` (Review Focus 1).

- [ ] **Step 1: Write failing test** `test_job_view_markup` asserting the ids above exist and `app.js` contains `ViewModel.progressSteps`, `ViewModel.summary`, `"That resume no longer exists."`.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** full suite — Expected: PASS.
- [ ] **Step 5: Commit** `feat: running and done screens`.

### Task 6: History view

**Files:**
- Modify: `static/index.html`, `static/app.css`, `static/app.js`
- Test: `tests/test_webapp.py`

**Interfaces:**
- Consumes: `GET /api/jobs` (existing), `ViewModel.historyTag`.
- Produces: `view-history` with header `id="history-title"`, note `id="history-note"`, list `id="history-list"` (rows are `<button>`s opening `#job/<id>`, showing company, role, date, tag), `id="select-btn"` ("Select"). Replaces the old job rail and its filters (search box + status filter may stay above the list if they still work).

- [ ] **Step 1: Write failing test** `test_history_markup` (ids exist; `app.js` contains `ViewModel.historyTag`).
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** full suite — Expected: PASS.
- [ ] **Step 5: Commit** `feat: history list`.

### Task 7: Delete flow

**Files:**
- Modify: `static/index.html`, `static/app.css`, `static/app.js`
- Test: `tests/test_webapp.py`

**Interfaces:**
- Consumes: `GET /api/cleanup`, `POST /api/cleanup` (Task 2).
- Produces: select mode on `view-history` (header becomes "N selected" + `id="select-cancel"`; checkbox per row; `id="select-all"` "Select all finished (N)"; `id="select-legacy"` "Old command-line folders (N)" shown only when legacy exists; running/queued rows disabled with "Running, can't delete"); `id="delete-selected"` red "Delete N resumes" (disabled at 0); confirm `<dialog id="delete-dialog">` listing items, the sentence "Removes each one's PDF, its copy in your PDF library, its report, and its saved job description. This can't be undone.", "Frees about <size>." and buttons Cancel / Delete; toast `id="toast" role="status"` "Deleted N resumes. <size> freed." (plus "Skipped: …" when `skipped` is non-empty, Review Focus 3). Done-screen `id="delete-job"` uses the same dialog with one item and then `go("#history")` (Review Focus 2). Selection resets after each delete.

- [ ] **Step 1: Write failing test** `test_delete_flow_markup` (ids exist; dialog copy present; `app.js` contains `"/api/cleanup"`).
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** full suite — Expected: PASS.
- [ ] **Step 5: Commit** `feat: select and delete old resumes`.

### Task 8: Browser smoke test (no Gemini quota)

**Files:**
- Create: `scripts/ui_smoke_server.py` (serves the app with `tests.conftest.FakePipe` on `127.0.0.1:8765`, temp dirs, a seeded legacy folder and two finished jobs), `scripts/ui_smoke.md` (the checklist below)

- [ ] **Step 1:** Start `scripts/ui_smoke_server.py`; with the Playwright tools at 1440px and 390px: paste a JD → Check skills → tick a chip → Tailor resume → watch the job view reach done → summary and Download visible → History lists jobs, no legacy rows → Select → select all + old folders → Delete → confirm → toast and list update → open a deleted `#job/<id>` → History note (Review Focus 1, 2, 5).
- [ ] **Step 2:** Save screenshots of New resume, Job (running), Job (done), History, Delete confirm at both widths under `.playwright-mcp/ui-refresh/`; compare against the mockups; fix and re-run until they match the spec's look.
- [ ] **Step 3: Commit** the two script files: `chore: UI smoke server and checklist`.
