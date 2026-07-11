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
| Bootstrap | `bootstrap_master.py` | One-time: PDF → master.json via the hiring-agent extraction pipeline (documented as optional; imports hiring-agent from sibling path or reuses its extraction code copied in) |
| Config | `.env` / `.env.example`, `prompt.py` | Same shape as hiring-agent: `LLM_PROVIDER`, `DEFAULT_MODEL=gemini-3.1-flash-lite`, `GEMINI_API_KEY`; model-parameter + provider maps |
| Tests | `tests/` + `pytest.ini` | Unit (mocked): retry plumbing reused smoke, template rendering assertions (non-vacuous — assert distinctive instruction/example content), renderer escaping, scorer-loop control flow. Integration (`-m integration`, live gemini-3.1-flash-lite): JD parse on a real JD, one full tailor pass on a fixture master+JD, truth-floor spot-check (fixture master lacking a JD must-have → assert not fabricated into work history) |

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
