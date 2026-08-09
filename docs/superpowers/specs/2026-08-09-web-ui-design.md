# ATS Resume Tailor Agent — Web UI Design Spec

**Date:** 2026-08-09
**Status:** Approved (plan approved verbally; spec written before implementation)
**Repo:** `/Users/vandanpatel/Desktop/ATS_Resume_Tailor_Agent`
**Predecessor spec:** `docs/superpowers/specs/2026-07-11-resume-tailor-design.md` — the tailoring pipeline this UI wraps. Its contracts are the source of truth for pipeline behavior; this spec only defines the web layer around it.

## Product

A local single-page web app that replaces the file-creation + terminal steps of the current flow: paste a job description into a textarea, click **Tailor resume**, watch the pipeline run live stage-by-stage, and preview/download the PDF, LaTeX, tailored JSON, and match report — all without touching `jds/`, the CLI, or the filesystem directly.

The tailoring core is **unchanged**: `TailorPipeline.run(master, jd_text, out_dir, no_pdf, job)` already accepts raw JD text, and the existing `ProgressReporter` protocol in `resume_tailor/progress.py` already emits typed per-stage events. This spec defines the adapter layer (job runner, SSE reporter, score subprocess) and one static frontend page. Zero modification to `tailor.py`, `resume_tailor/pipeline.py`, `resume_tailor/stages.py`, `resume_tailor/assembly.py`, `resume_tailor/evidence.py`, `resume_tailor/rendering.py`, or `resume_tailor/llm.py`.

## Architecture

```
webapp.py (entry: .venv/bin/python webapp.py)
 ├── FastAPI + uvicorn                     (new deps: fastapi, uvicorn)
 ├── Job runner                           worker thread invoking TailorPipeline.run()
 │    └── in-memory job registry          {job_id: state, event buffer, thread}
 ├── SSEProgressReporter                  resume_tailor/web/reporter.py
 │                                        implements ProgressReporter protocol →
 │                                        per-job event deque; SSE replays on reconnect
 ├── Score orchestrator                   subprocess → resume_tailor/web/score_cli.py
 │                                        (per-job variant of score_outputs.py module-swap)
 └── static/                              index.html + app.js + app.css (no Node/build step)
```

Key seams reused from the existing codebase, unchanged:

| Existing piece | How the web layer consumes it |
|---|---|
| `TailorPipeline.run(master, jd_text, out_dir, no_pdf, job)` | called directly in a worker thread with the pasted text |
| `ProgressReporter` protocol (`emit(ProgressEvent)`, `close()`) | implemented by `SSEProgressReporter` — stages/retries/warnings/details flow to the browser verbatim |
| `Stage` enum (14 stages) | drives the UI stepper rows |
| `load_master` (`.runtime`) | master loading in the server process |
| `output/<job-slug>/` artifact layout | unchanged — keeps `score_outputs.py`, `tailor.py batch`, and existing tooling compatible with UI-produced runs |

## Job lifecycle

1. `POST /api/jobs` with `{jd_text, name?, bridge_skills?, no_pdf?}`.
2. Server derives `job_id = <slug>-<4 hex of sha1(jd_text)>`; slug = user `name` if given, else the first meaningful line of the JD (first ~40 chars), else `job`. Colliding runs re-run into the same dir (like `--force`).
3. Out dir: `output/<job_id>/`.
4. One job runs at a time; a second `POST` while a run is active returns `409 conflict` with the active job id. This respects Gemini pacing and avoids token thrash.
5. Worker thread runs the pipeline with `job = JobContext(job_id, output_dir=out_dir)`, `no_pdf` passed through.
6. Events are appended to the job's deque; SSE streams them; final event is `JOB_COMPLETED` / `JOB_FAILED`. A completed run writes `.done` exactly as CLI runs.
7. Failed runs keep `diagnostic_report.json` (pipeline behavior already) and the UI surfaces the terminal failure line from the failed job event.

## API contract

| Endpoint | Method | Behavior |
|---|---|---|
| `/` | GET | serves the single-page app from `static/` |
| `/api/jobs` | POST | `{jd_text, name?, bridge_skills?, no_pdf?}` → `201 {job_id}`; 409 if a job is already running; 422 if `jd_text` empty |
| `/api/jobs` | GET | list of known jobs (status, elapsed, output paths) — history view |
| `/api/jobs/{id}/events` | GET | Server-Sent Events stream; replays buffered events for the job then live events; 15s comment heartbeats (`:keepalive`); 404 for unknown id |
| `/api/jobs/{id}` | GET | job status: state (queued/running/completed/failed), elapsed, artifact list (`resume.pdf`, `resume.tex`, `tailored.json`, `match_report.json`, `ats_score.json`) |
| `/api/jobs/{id}/files/{name}` | GET | artifact download; path is resolved inside `output/<job_id>/` only (no traversal) |
| `/api/jobs/{id}/score` | POST | spawns `score_cli.py` subprocess for this one job; SSEs scorecard events; writes `output/<job_id>/ats_score.json` |
| `/` (static) | GET | the app shell |

### SSE event schema

Each event is `data: <json>` on its own line, `id: <n>` monotonic per job, `event:` name from `ProgressEventKind`:

```json
{
  "kind": "stage_started",
  "stage": "Rewrite work",
  "message": null,
  "elapsed_seconds": 12.4,
  "attempt": 1,
  "max_attempts": 2,
  "job": "sap-9f2a",
  "verbose_only": false
}
```

Mapping is 1:1 with `ProgressEvent` (progress.py). The client renders stage rows from `STAGE_STARTED`/`STAGE_COMPLETED`, throws inline under `STAGE_RETRY`/`STAGE_WARNING`, prints `STAGE_DETAIL` in the expandable per-stage log, and ends on `JOB_COMPLETED`/`JOB_FAILED`. Scorecard runs reuse the same stream with a `score` prefix in the message.

## Score & match (hiring-agent rubric)

- `POST /api/jobs/{id}/score` runs a one-shot subprocess: `.venv/bin/python -m resume_tailor.web.score_cli <job_id> --master master.json --out-dir output --hiring-agent-path <sibling checkout> [--call-interval N]`.
- The subprocess isolates the sibling hiring-agent's module collisions: it snapshots/evicts `sys.modules` entries for `models`, `llm_utils`, `prompt`, `prompts*`, `chdir` into the checkout, imports its evaluator fresh, scores the one tailored.json, and restores everything in a `finally` — the exact mechanics of `score_outputs.py`, per-job. Nothing is swapped inside the long-lived server process.
- Result: `output/<job_id>/ats_score.json` (category scores, bonus, deductions, total) and SSE `scorecard` events for live bars.
- The sibling path defaults to `~/Desktop/hackerank_ats/hiring-agent` (same default as `score_outputs.py`); overridable via `--hiring-agent-path` on `webapp.py`.

## UI page (single, dark, per vandan-ui-system)

Art direction: local tool that looks like Linear/Vercel — canvas `#050506`, elevated surfaces `#121214`/`#1A1A1E`/`#232328`, white-alpha borders, one accent for the primary action and live state, bold non-Inter display type, tabular-nums timings, zero AI-slop patterns. Motion per `motion-craft.md`; `prefers-reduced-motion` respected; full loading/empty/error states.

Screen anatomy (two columns on desktop, single stack below ~900px):

```
 Top bar   · app name · master identity (name/email from master.json) · server status ·
           · bridge-skills toggle · model badge

 Left      Paste & Run
 ┌ Paste JD (monospace textarea, autosize, paste-friendly) ────────────────┐
 │ Job name (optional)   [x] Bridge skills   [x] Skip PDF                   │
 └────────────────────────────────────────────────────────────────────────┘
           [ Tailor resume ]      (primary; idle/pending/disabled states;
                                    meta: ~N LLM calls · est. time)

 Right     Live pipeline (14-stage stepper)
           ✓ Parse job description   2.1s      (checked + elapsed)
           ▶ Select work               …      (running spinner + live log)
           ↻ retry lines / ⚠ warnings inline
           [ expandable per-stage detail log ]
           ↓ on completion →
           Results card: embedded PDF preview (or plain-text preview if
                          skip-PDF) · download chips (pdf · tex · tailored.json
                          · match_report.json) · match-report facts (roles+
                          relevance, matched requirements, inferred metrics,
                          truth-violation warnings)
           Scorecard card (after Score & match): category bars
                          (OpenSrc/SelfProj/Prod/TechSkl) · bonus · deductions
                          · total · [Score & match] button

 Footer      Recent runs (from output/) · status dot · click to reopen
```

Interaction details:

- The Tailor button shows pending while a job is queued, disabled while one runs, and re-enables when the run finishes (success or failure); a new paste starts a fresh run.
- Stage rows: idle (dim, pending icon) → running (accent spinner) → done (check + duration). Retries and warnings render inline under the row, not silently in a log.
- Artifact chips are awaited server-side: they appear in the results card only when the job reports `artifacts` — the client polls `/api/jobs/{id}` after `JOB_COMPLETED` to fetch the final artifact list.
- Error surfaces: stage failure line + `diagnostic_report.json` chip; open log shows `schema_error`, attempt count, and parsed response preview.

## File changes (deliverables)

| Path | Kind | Note |
|---|---|---|
| `webapp.py` | new | FastAPI app + job runner + SSE + static serving + scoring hooks |
| `resume_tailor/web/__init__.py` | new | package marker |
| `resume_tailor/web/reporter.py` | new | `SSEProgressReporter` (ProgressReporter protocol impl, deque, replay) |
| `resume_tailor/web/score_cli.py` | new | per-job scoring subprocess (module-swap mechanics from `score_outputs.py`) |
| `static/index.html`, `static/app.js`, `static/app.css` | new | the UI (no build step) |
| `tests/test_webapp.py` | new | TestClient tests with stub reporter/provider — unit-level, no live LLM |
| `tests/test_web_score.py` | new | `score_cli` round-trip against a fixture `tailored.json` with a stubbed evaluator |
| `requirements.txt` | edit | append `fastapi`, `uvicorn` |
| `README.md` | edit | "Web App" section: install, run, endpoints, verification steps |
| `.gitignore` | no change | (verify `output/` and `__pycache__/` coverage) |

No modifications to `tailor.py`, `resume_tailor/{batch,cli,pipeline,progress,runtime}` modules; the new modules consume the existing public seams only.

## Design decisions

1. **FastAPI over stdlib `http.server`** — typed requests/pydantic responses match the repo's Pydantic discipline; SSE and static mounting are trivial; the two deps are pinned in `requirements.txt` like the rest. A stdlib fallback exists if you want to avoid deps, but it forfeits the typed contract.
2. **One job at a time (serialized worker)** — the pipeline is sequential and paced (`DEFAULT_CALL_INTERVAL`); parallel runs would thrash the model quota and muddle diagnostic output. 409s are surfaced in the UI as a "Run in progress" chip.
3. **Scoring as a subprocess** — the `sys.modules` churn of the hiring-agent evaluator must never run inside the uvicorn process; a one-shot `score_cli.py` child isolates it. Cost: one Python interpreter per score (seconds — negligible next to one LLM eval).
4. **Events replayable** — the per-job deque makes reconnecting and reopening a finished run cheap and idempotent; the UI re-renders the stepper from history on load.
5. **Output layout unchanged** — UI runs write the same `output/<slug>/{.done, tailored.json, match_report.json, resume.tex, resume.pdf}` shape, so batch, `score_outputs.py`, and any future tooling treat the app's jobs as first-class.
6. **No build step** — plain HTML/CSS/JS in `static/`; no Node, no bundler, keeps the repo pure-Python deployable.
7. **First action after approval**: write this very spec; implementation then works against it.

## Non-goals (v1)

- Mid-run cancel: a run cannot be interrupted once started (kill the server to abort; the next run re-clears partial artifacts via the pipeline's existing preflight). Documented as future work.
- Parallel jobs / queue visualization beyond a busy-indicator.
- Multi-master switching in the UI (run one `--master`; changing master restarts the server with a new flag).
- JD URL fetching, browser extension pasting, or clipboard auto-detect.
- Editing the master from the UI; the master stays a file.

## Verification

1. `pytest -m "not integration"` (repo-wide): existing suite + `test_webapp.py` + `test_web_score.py` green; the web tests must not hit the live LLM (stub provider + `NullProgressReporter`-like reporter).
2. Manual smoke (no network needed for the app, only for the pipeline itself):
   - `.venv/bin/python webapp.py` → open `http://localhost:8000`
   - Paste the contents of `jds/sap.txt` → Tailor → watch all 14 stages advance; pipeline completes to PDF (Tectonic installed: `/opt/homebrew/bin/tectonic`).
   - Results card shows PDF preview + chips; download `tailored.json` and `match_report.json` and diff against a CLI run of the same JD (identical structure).
   - Score & match → scorecard bars render; `output/sap*/ats_score.json` written.
   - History footer lists prior runs; reopening one shows its stage history and artifacts.
   - Non-Tectonic fallback: run with skip-PDF; plain-text preview renders; `.done` records `pdf: false`.
3. Artifact parity: a UI run's `output/<job_id>/` matches the CLI's file set exactly.