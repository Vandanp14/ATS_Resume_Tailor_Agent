# ATS Resume Tailor Agent — Design Spec

**Date:** 2026-07-11
**Status:** Approved (verbal design approval; spec pending user review)
**Repo:** `/Users/vandanpatel/Desktop/ATS_Resume_Tailor_Agent` (new, standalone)
**Target model:** `gemini-3.1-flash-lite` (primary), same `.env` pattern as hiring-agent. Design must stay weak-model-reliable: schema-constrained decoding, retry-on-invalid-output, few-shot templates throughout.

## Product

Takes one hand-maintained **master resume** (JSON Resume format) plus a **job description** (plain text file) and produces a tailored, ATS-optimized resume as JSON + Jake's-Resume-style LaTeX → PDF, with a JD-match coverage report and bounded auto-iteration.

## Content policy (hard constraint, enforced in prompts and scorer)

- **Allowed:** aggressive rewriting of bullets into JD language; keyword mirroring; reordering/selecting the most relevant projects, bullets, and skills; inferring/generalizing adjacent skills from genuinely present experience (e.g. "used React" → "frontend frameworks including React ecosystem").
- **Forbidden (truth floor):** inventing employers, job titles, employment dates, degrees, certifications, projects, or metrics/numbers not present in the master. Every tailored fact must be traceable to the master resume. Templates must state this explicitly; the scorer flags any tailored content without a master-resume source as a violation, and violations block rendering.

## Architecture (mirrors hiring-agent's compartmentalized per-section pattern)

```
master.json + jd.txt
   │
   ▼
[1] JD parser ── 1 LLM call ──► JDProfile (Pydantic)
   │
   ▼
[2] Per-section tailors (1 LLM call each, independent):
      summary • skills • work • projects   (education = passthrough, no LLM)
   │
   ▼
[3] Assembler ──► tailored JSONResume (Pydantic-validated)
   │
   ▼
[4] Scorer ── 1 LLM call ──► MatchReport (coverage %, missing must-haves,
   │                          weak sections, truth-floor violations)
   ▼
[5] Iterate: coverage < threshold (default 80%) → re-run ONLY weak sections
    with gap feedback appended. Max 2 total passes. Truth violations always
    trigger a re-run of the offending section with the violation named.
   │
   ▼
[6] Renderer: JSONResume → Jake's-style LaTeX (Jinja-filled .tex) → PDF via tectonic
```

## Components

| Component | File | Contract |
|---|---|---|
| Plumbing (copied from hiring-agent, post-hardening state) | `llm_utils.py`, provider layer of `models.py` | `call_llm_with_retry(provider, model, messages, response_model, options, max_retries)`; Gemini schema converter (`_pydantic_to_gemini_schema`); `LLMExtractionError`; `initialize_llm_provider` with gemini-prefix validation; `max_output_tokens` safety cap |
| Schemas | `models.py` | JSON Resume models (copied), plus new: `JDProfile` (role, seniority, domain, must_have_skills, nice_to_have_skills, weighted keywords), `TailoredSection` wrappers per section, `MatchReport` (coverage_pct, missing_must_haves, weak_sections, truth_violations) |
| Templates | `prompts/templates/*.jinja` + `template_manager.py` (copied) | `jd_parse.jinja`, `tailor_summary.jinja`, `tailor_skills.jinja`, `tailor_work.jinja`, `tailor_projects.jinja`, `match_score.jinja`, shared `_tailoring_rules.jinja` partial (content policy stated once). Every template: worked example (input→output), explicit null rules, hiring-agent few-shot conventions |
| Orchestrator | `tailor.py` | CLI: `python tailor.py master.json jd.txt -o out/ [--threshold 80] [--max-passes 2] [--no-pdf]`. Writes `out/tailored.json`, `out/resume.tex`, `out/resume.pdf`, `out/match_report.json` |
| Renderer | `render.py` + `templates/latex/jakes.tex.jinja` | Jinja2 fills Jake's-Resume-style template (custom Jinja delimiters `\VAR{}`/`\BLOCK{}` to avoid LaTeX brace collisions); LaTeX-escapes all user text (`&`, `%`, `$`, `#`, `_`, `~`, `^`, `\`); compiles via `tectonic` (self-contained, auto-downloads packages); `--no-pdf` skips compile for machines without tectonic |
| Bootstrap | `bootstrap_master.py` | One-time: PDF → master.json. Imports the hiring-agent checkout via `sys.path` insertion of a `--hiring-agent-path` argument (default `~/Desktop/hackerank_ats/hiring-agent`) and calls its `PDFHandler.extract_json_from_pdf`. Optional utility — not part of the tailoring pipeline, no code copied for it |
| Config | `.env` / `.env.example`, `prompt.py` | Same shape as hiring-agent: `LLM_PROVIDER`, `DEFAULT_MODEL=gemini-3.1-flash-lite`, `GEMINI_API_KEY`; model-parameter + provider maps |
| Tests | `tests/` + `pytest.ini` | Unit (mocked): retry plumbing reused smoke, template rendering assertions (non-vacuous — assert distinctive instruction/example content), renderer escaping, scorer-loop control flow. Integration (`-m integration`, live gemini-3.1-flash-lite): JD parse on a real JD, one full tailor pass on a fixture master+JD, truth-floor spot-check (fixture master lacking a JD must-have → assert not fabricated into work history) |

## ATS-rubric optimization (added per user directive)

The tailored resume must maximize the score assigned by the **hiring-agent evaluator** (sibling project — its rubric is fully known: open_source ≤35, self_projects ≤30, production ≤25, technical_skills ≤10, bonus ≤20 incl. GSoC/portfolio/LinkedIn/startup lines, deductions for tutorial-grade projects, missing links, Hacktoberfest-only OSS). Two mechanisms:

1. **Baked-in (always on):** `_tailoring_rules.jinja` encodes the rubric as tailoring pressure — surface open-source contributions to other people's projects prominently; prefer complex/impactful projects over tutorial-grade ones; every selected project must carry its GitHub/live link from the master; surface startup/founder/early-stage and production experience; include portfolio + LinkedIn URLs when present in master; name GSoC/Outreachy-class programs explicitly and never conflate "Girl Script Summer of Code" with GSoC. All within the truth floor — the rubric shapes *selection and emphasis*, never fabrication.
2. **Live check (optional):** `--ats-score` flag runs the hiring-agent evaluator on the tailored resume via the same sibling-path import as bootstrap, printing its category scores next to the JD match report. Off by default (extra LLM calls).

## One-page auto-fit (added per user directive)

The final PDF must be exactly one page, fully automated:

1. **Relevance scoring at generation time:** every tailor stage emits a `relevance` score (0-100, JD-driven) per item — each work bullet, each project, each skill group. The whole master is considered; nothing is pre-truncated before scoring.
2. **Deterministic trim loop (no extra LLM calls):** render → count PDF pages (pypdf) → if >1 page, drop the lowest-relevance items in a fixed priority order — (a) work bullets beyond 2 per position, (b) whole projects beyond 2, (c) skill groups, (d) oldest low-relevance position's remaining bullets to 1, (e) whole lowest-relevance position — one item per iteration, re-render, repeat until 1 page (hard cap 25 iterations, then fail loudly).
3. Education is never trimmed. Header/contact never trimmed. Ties broken by recency (older goes first).
4. One-page enforcement requires `tectonic` (page count needs a real compile); with `--no-pdf` the fit loop is skipped and a warning is printed.

## Batch drop-folder mode + quota resilience (added per user directive)

Primary UX is a drop folder: put any number of `*.txt` JDs in `jds/`, run once, get per-JD output dirs.

1. **Batch CLI:** `python tailor.py batch [--jd-dir jds/] [--out-dir output/] [+ all single-run flags]` — processes every `*.txt` in `--jd-dir` sequentially (never parallel — respects Gemini rate limits), writing `output/<jd-filename-stem>/{tailored.json, resume.tex, resume.pdf, match_report.json}`.
2. **Idempotent resume-after-failure:** a JD dir containing a `.done` marker is skipped on re-run (`--force` re-does everything). A run killed mid-JD leaves no `.done` → that JD restarts cleanly next run.
3. **Quota handling:** provider-level backoff (copied from hiring-agent) absorbs transient 429s. If quota is truly exhausted (backoff retries exhausted → ResourceExhausted escapes), the batch runner catches it, prints exactly which JDs completed and which remain, and exits cleanly with: "Gemini quota exhausted — wait and re-run the same command; completed JDs will be skipped." Optional `--delay-seconds N` inserts a pause between JDs to stay under rate limits proactively.
4. Single-JD mode (`python tailor.py master.json jd.txt -o out/`) remains for one-offs.

## Key design decisions

1. **Education passthrough** — no LLM call; copied verbatim from master (nothing to tailor, eliminates a fabrication surface).
2. **Scorer owns truth enforcement** — cheaper than constraining generation alone; every pass cross-checks tailored content against master and reports violations with section+line pointers; violations force a targeted re-run (not a full restart), and if still present after max passes, the run fails loudly rather than rendering a fabricated resume.
3. **Bounded iteration** — max 2 passes total; re-runs are per-section (only weak/violating sections), keeping worst-case LLM calls at: 1 (JD) + 4 (sections) + 1 (score) + 4 (worst-case re-runs) + 1 (re-score) = 11.
4. **tectonic over TeX Live** — single binary, hermetic, CI-friendly; `--no-pdf` escape hatch.
5. **Copy plumbing, don't share a package** — user chose separate repo; a pip-installable shared lib is more structure than two sibling projects need. Copies are taken from hiring-agent's post-review hardened state (branch `prompt-llm-reliability`, commit 9a78528 or later).

## Non-goals

- JD URL scraping (paste-text only, per user choice)
- Multiple LaTeX templates (Jake's style only, v1)
- Cover letters, LinkedIn profiles, or any non-resume artifact
- Editing/maintaining the master resume beyond the one-time bootstrap script
- Caching layers (hiring-agent's dev-mode cache was a repeated bug source; runs here are cheap enough to skip caching in v1)

## Verification

1. `pytest -m "not integration"` green (mocked unit tests).
2. `pytest -m integration` against live `gemini-3.1-flash-lite`: JD parse validates, full tailor run produces schema-valid output with coverage report, truth-floor test passes.
3. Manual: one real master + one real JD end-to-end → PDF opens, is one page of sane Jake's-style output, no literal "None"/placeholder strings, no fabricated entries vs the master.
