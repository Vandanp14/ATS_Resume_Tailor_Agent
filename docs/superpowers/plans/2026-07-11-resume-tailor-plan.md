# ATS Resume Tailor Agent — Implementation Plan

> Executed via orchestrated Opus subagents in dependency waves. Spec: `docs/superpowers/specs/2026-07-11-resume-tailor-design.md` — every task's implementer reads the spec first; it is the source of truth for contracts.

**Repo:** `/Users/vandanpatel/Desktop/ATS_Resume_Tailor_Agent` (git initialized, spec committed)
**Plumbing source:** `/Users/vandanpatel/Desktop/hackerank_ats/hiring-agent`, branch `prompt-llm-reliability` at commit `9a78528` or later (hardened state — retry helper w/ provider-error catch, Gemini schema converter w/ dict/class dispatch, max_output_tokens cap)
**Model:** `gemini-3.1-flash-lite` via same `GEMINI_API_KEY` (copy `.env` from hiring-agent; `.env` gitignored)

## Global constraints
- Weak-model reliability everywhere: every LLM call through `call_llm_with_retry` with a Pydantic response model; every template carries a worked example and explicit null rules; no template may instruct output of fields absent from its response model (the candidate_name lesson).
- Truth floor from spec §Content policy is non-negotiable and lives ONCE in `_tailoring_rules.jinja`.
- Tests must be non-vacuous: assert distinctive content, not substrings satisfiable by unrelated boilerplate (lesson from hiring-agent review).
- Scoped `git add` by exact path always.

## Wave 1 — Foundation (single agent, blocks everything)

### Task A: plumbing copy + new schemas + repo scaffolding
**Create:** `llm_utils.py`, `models.py`, `prompts/template_manager.py`, `prompt.py`, `requirements.txt`, `pytest.ini`, `.gitignore`, `.env.example`, `.env` (copied, never committed), `tests/__init__.py`, `tests/test_plumbing_smoke.py`, `tests/test_models.py`
- Copy from hiring-agent verbatim (adjusting imports only): `llm_utils.py` whole; `models.py` — JSON Resume models (Location, Profile, Basics, Work, Education, Skill, Project, Award, JSONResume), provider classes (OllamaProvider, GeminiProvider incl. `_pydantic_to_gemini_schema` + helpers + max_output_tokens), drop hiring-agent-only models (EvaluationData/Scores/ProjectSelection*/GitHub*); `prompts/template_manager.py` (template dict emptied — Wave 2 fills it); `prompt.py` (model maps + env).
- New Pydantic models in `models.py`: `JDProfile{role:str, seniority:Optional[str], domain:Optional[str], must_have_skills:List[str], nice_to_have_skills:List[str], keywords:List[KeywordWeight{term:str, weight:int 1-5}]}`; `TailoredSummary{summary:str}`; relevance-carrying wrappers per spec §One-page auto-fit: `TailoredSkills{skills:List[ScoredSkill]}` (ScoredSkill = Skill + `relevance:int 0-100`), `TailoredWork{work:List[ScoredWork]}` (ScoredWork = Work + `relevance:int` + per-bullet `highlights:List[ScoredBullet{text:str, relevance:int}]`), `TailoredProjects{projects:List[ScoredProject]}` (Project + `relevance:int`); `MatchReport{coverage_pct:float 0-100, missing_must_haves:List[str], weak_sections:List[str], truth_violations:List[TruthViolation{section:str, claim:str, reason:str}], notes:Optional[str]}`. Plus `strip_relevance()` helpers converting Scored* back to plain JSON Resume models for rendering/output.
- `.gitignore`: `.env`, `__pycache__/`, `.pytest_cache/`, `out/`, `*.pdf`, `.superpowers/` — do NOT ignore `test_*.py` (hiring-agent footgun lesson).
- Tests: smoke `call_llm_with_retry` with mocked provider (success/retry/failure); every new model round-trips a valid fixture dict and rejects an invalid one.
- Commit per logical unit.

## Wave 2 — Parallel (3 agents, file-disjoint, all read spec + Wave 1 code)

### Task B: prompt templates
**Create:** `prompts/templates/_tailoring_rules.jinja`, `jd_parse.jinja`, `tailor_summary.jinja`, `tailor_skills.jinja`, `tailor_work.jinja`, `tailor_projects.jinja`, `match_score.jinja`, `system_message.jinja`; register all in `template_manager.py`; `tests/test_templates.py`
- `_tailoring_rules.jinja`: truth floor (spec §Content policy verbatim intent) + ATS-rubric pressure rules (spec §ATS-rubric optimization item 1) — stated once, included by all tailor_* and match_score templates.
- Each template: role framing, the shared include, exact output JSON structure matching its Wave-1 Pydantic model, 1 worked example (realistic input excerpt → exact correct JSON), explicit "missing → null, never placeholder" rule.
- `tailor_work.jinja` is the hardest: shows master work entries + JDProfile → selected/reworded bullets mirroring JD keywords, preserving employer/title/dates verbatim, no invented metrics — worked example must demonstrate a rewrite that adds JD keywords WITHOUT adding facts.
- `match_score.jinja`: tailored resume + JDProfile + master resume → MatchReport; worked example includes one truth-violation detection.
- Tests: non-vacuous — assert each template renders with fixture context, contains its distinctive instruction sentences and worked-example markers, includes the shared partial exactly once, output-structure block matches the Pydantic field names (parse the example JSON in the template and validate it against the actual model class).

### Task C: renderer
**Create:** `render.py`, `templates/latex/jakes.tex.jinja`, `tests/test_render.py`
- Jinja env with LaTeX-safe delimiters (`\VAR{...}`, `\BLOCK{...}`, comment `\#{...}`), full escaping function for `& % $ # _ { } ~ ^ \`, applied to every interpolated string.
- Jake's-Resume-style single-column template: header (name, phone, email, LinkedIn, GitHub, portfolio — omit null fields entirely, no empty separators), education, experience (bullets), projects (name + tech + link + bullets), skills (grouped lines). Handles missing sections gracefully (BLOCK-if guards).
- `render(resume: JSONResume, out_dir: Path, compile_pdf: bool) -> paths`: writes `.tex` always; compiles via `tectonic resume.tex` when `compile_pdf` (check binary present; actionable error naming `brew install tectonic` if missing).
- **One-page fit loop** (spec §One-page auto-fit): `fit_to_one_page(scored_resume, out_dir) -> JSONResume` — render, count pages via `pypdf` (add to requirements.txt), while pages>1 drop ONE lowest-relevance item per iteration in the spec's fixed priority order (bullets>2/position → projects>2 → skill groups → oldest low-relevance position's bullets to 1 → whole lowest position), never education/header, recency tiebreak, hard cap 25 iterations then raise. Takes the Scored* models (relevance fields) and returns the final trimmed plain JSONResume.
- Tests: escaping unit tests (each special char), null-field omission (no `- None`, no dangling separators — render a fixture with nulls and assert), `.tex` golden-content assertions; trim-order unit tests with a fake page-counter injected (no tectonic needed — assert exactly which item is dropped at each step of an oversized fixture); PDF compile + real page-count test marked `integration` (skipped without tectonic).

### Task D: bootstrap + README
**Create:** `bootstrap_master.py`, `README.md`, `examples/master.example.json`, `examples/jd.example.txt`
- `bootstrap_master.py` per spec: `--hiring-agent-path` (default `~/Desktop/hackerank_ats/hiring-agent`), sys.path insert, call `PDFHandler.extract_json_from_pdf`, write `master.json` pretty-printed; clear errors if path/venv wrong.
- `README.md`: what it does, content policy + truth floor stated plainly, setup (venv, requirements, `.env`, tectonic), usage examples for every CLI flag incl. `--ats-score`, architecture diagram (from spec), how to maintain `master.json`.
- Realistic example master (synthetic person) + example JD.

## Wave 3 — Orchestrator (single agent, depends on A+B; C needed only at import level)

### Task E: pipeline + CLI
**Create:** `tailor.py`, `tests/test_tailor.py`
- Pipeline per spec §Architecture: parse JD → 4 section tailors (education passthrough) → assemble scored resume → match-score → iterate weak/violating sections only (max 2 passes, threshold default 80) → `fit_to_one_page` (unless `--no-pdf`, then strip_relevance + warn) → final render via `render.py`.
- Truth violations: re-run offending section with violation appended to prompt; if violations persist after max passes → exit nonzero, no render, loud message.
- CLI: `python tailor.py master.json jd.txt -o out/ [--threshold 80] [--max-passes 2] [--no-pdf] [--ats-score]`. `--ats-score`: sibling-path import of hiring-agent `ResumeEvaluator`, evaluate `convert_json_resume_to_text` of tailored resume, print category scores.
- **Batch mode** (spec §Batch drop-folder): `python tailor.py batch [--jd-dir jds/] [--out-dir output/] [--delay-seconds N] [--force] [+ single-run flags]` — sequential over `*.txt`, per-JD output dir named by file stem, `.done` marker for idempotent skip, catch escaped `ResourceExhausted` at the batch loop → print completed/remaining JD lists + "wait and re-run; completed JDs will be skipped" → exit code 75 (EX_TEMPFAIL). Create `jds/` with a README placeholder in repo.
- Outputs per JD: `tailored.json`, `resume.tex`, `resume.pdf` (unless `--no-pdf`), `match_report.json`, `.done`.
- Tests (mocked `call_llm_with_retry` throughout): happy path single pass; low-coverage triggers exactly one targeted re-run of only weak sections; truth violation blocks render and exits nonzero; education passthrough byte-identical; batch: 3 fixture JDs → 3 output dirs, re-run skips `.done` dirs, mid-batch ResourceExhausted → clean exit 75 with correct completed/remaining lists, `--force` re-processes.

## Wave 4 — Live verification (single agent, depends on all)

### Task F: integration tests + one live end-to-end run
**Create:** `tests/test_integration_live.py` (marked `integration`)
- Live gemini-3.1-flash-lite: JD parse of `examples/jd.example.txt` validates `JDProfile`; full tailor run on example master+JD → schema-valid tailored resume, MatchReport sane (0≤coverage≤100), no placeholder strings, education byte-identical to master, all selected projects retain their master links.
- Truth-floor live test: JD demands a skill absent from master → assert no new employer/title/degree appears in tailored output vs master.
- One manual-equivalent run: full CLI incl. PDF compile; report actual coverage numbers and eyeball-check summary of the .tex output.

## Execution notes
- Every implementer: Opus, reads spec + this plan section + relevant existing code before writing; runs `.venv/bin/pytest -m "not integration" -q` before each commit; reports concisely with commit SHAs.
- Wave 2 agents work same-repo concurrently: scoped `git add` exact paths, retry on index.lock.
- Controller reviews diffs between waves; final whole-repo review after Wave 4.
