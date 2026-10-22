# College Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A per-run "College posting" switch that targets each posted minimum/preferred qualification line, checks coverage in code, flags unsupported lines, allows two pages, and adds a summary.

**Architecture:** Built on `feat/resume-flow-skill-check` (literal JD terms, skill check, current-role ordering, model chains). One flag, `college_mode`, flows web/CLI → `TailorPipeline` → prompts, selection caps, page limit, render. Qualification lines ride existing calls: the JD parse returns them, interpersonal lines join the requirement map as `qualification` items that the existing evidence-plan call targets, and coverage is checked in code from bullet provenance. The summary is the only new AI call.

**Tech Stack:** Python 3.13, Pydantic v2, Jinja2 prompts, LaTeX via tectonic, FastAPI, vanilla JS, pytest (`.venv/bin/python -m pytest -q`).

**Spec:** `docs/superpowers/specs/2026-10-21-college-mode-design.md`

## Global Constraints

- With `college_mode` off, behaviour and output are unchanged (big-company mode). Existing tests stay green untouched.
- At most one extra AI call per run, only in college mode (the summary stage).
- Unsupported qualification lines are flagged, never reworded into a match; flags never block rendering.
- Years shown on the page are real work experience only, whole years with "+" ("2+ years"), never rounded up. Substitution only changes a flag's status.
- Substitution: 30 semester / 45 quarter credits = 1 year, completed credits only, only when the posting allows it.
- Up to two pages in college mode; one page otherwise.
- PDF text must stay cleanly extractable (same template family).

## Review Focus

1. **Postings with no qualification headings** (a college posting that lists requirements in prose): the parse returns empty line lists; college mode must still run (two pages, summary) with no flags and no crash. Test in Task 2.
2. **Dates the experience counter misreads** ("2024", missing start, "Present", future end date): months must never go negative or count future months. Test in Task 3.
3. **A line that is both degree and experience** ("Bachelor's degree and two years of experience, or equivalent combination"): classified once, not double-counted; substitution guard applies. Test in Task 3.
4. **Summary that names a number not computed** ("3 years"): rejected and replaced by the code fallback, never shipped. Test in Task 7.
5. **Fit recovery and bullet review in college mode:** a paused job resumed later must still fit to two pages, not one. Test in Task 6.

---

### Task 1: The `college_mode` switch end to end

**Files:**
- Modify: `resume_tailor/pipeline.py` (`TailorPipeline.__init__` gains `college_mode: bool = False`; stored as `self.college_mode`; included in `_checkpoint_store` options), `resume_tailor/checkpoints.py` (`stage_fingerprint` JD-only stages include only a `college_mode` option when truthy), `resume_tailor/web/models.py` (`CreateJobRequest`, `JobOptions`, `QueuePayload`, `SkillCheckRequest` gain `college_mode: bool = False`; `job_fingerprint` appends it only when true), `resume_tailor/web/jobs.py` (pass through in `enqueue`, `_run_job`, `run_skill_check`), `resume_tailor/web/app.py` (create_job fingerprint options), `resume_tailor/cli.py` + `resume_tailor/batch.py` (`--college` flag), `static/index.html` + `static/app.js` (checkbox `id="college-mode"` in Advanced options labelled "College posting" / "Two pages, qualification checklist, summary."; included in `currentDraft`, `fillDraft`, and the skill-check body)
- Test: `tests/test_college_mode.py` (new), `tests/test_webapp.py`, `tests/test_checkpoints.py`

**Interfaces:**
- Produces: `TailorPipeline(..., college_mode: bool = False)`; `JobOptions.college_mode`; `--college` CLI flag; checkpoint fingerprints for `jd_parse` differ between modes, all other answer/JD rules unchanged.

- [ ] Step 1: Failing tests — `test_college_flag_reaches_pipeline` (web `create_job(..., college_mode=True)` → FakePipe receives `college_mode=True`; record kwargs on the fake class); `test_jd_parse_fingerprint_depends_on_college_mode`; `test_job_fingerprint_unchanged_when_off` (fingerprint of a request without the flag equals the pre-change value computed from the same seed tuple); `test_index_has_college_toggle`.
- [ ] Step 2: Run — FAIL.
- [ ] Step 3: Implement.
- [ ] Step 4: Run new tests + full suite — PASS.
- [ ] Step 5: Commit `feat: college posting switch`.

### Task 2: Qualification lines in the JD parse

**Files:**
- Modify: `models.py` (new `QualificationLine`, `JDProfile.minimum_qualifications/preferred_qualifications`), `prompts/templates/jd_parse.jinja` (college section under `{% if college_mode %}`), `resume_tailor/pipeline.py` (`_parse_jd` passes `college_mode`), `keyword_coverage.py` (`sanitize_jd_profile` drops lines whose `text` is not in the posting)
- Test: `tests/test_college_mode.py`

**Interfaces:**
- Produces in `models.py`:
  - `QualificationType = Literal["experience_length", "degree", "technical", "interpersonal", "other"]`
  - `class QualificationLine(StrictModel): text: str = Field(min_length=1); type: QualificationType; years: float | None = None; domain: str | None = None; named_terms: list[str] = Field(default_factory=list)` (`named_terms`: tools and standards named in the line, e.g. "Section 508", "ADA", "Cascade CMS").
  - `JDProfile.minimum_qualifications: list[QualificationLine] = Field(default_factory=list)`, `preferred_qualifications: list[QualificationLine] = Field(default_factory=list)`, `allows_substitution: bool = False`, `substitution_phrase: str | None = None`.
- Prompt (college only): "List every line under minimum/required qualifications and preferred qualifications verbatim as `text`, one per line, with its `type`; for `experience_length` give `years` and `domain` ('web development/programming'); put tools and standards the line names in `named_terms`. A line naming both a degree and years of experience is `degree` with `years` and `domain` set. Set `allows_substitution` when the posting allows education to substitute for experience ('equivalent combination of education and experience', 'education may substitute', 'in lieu of') and copy that phrase into `substitution_phrase`. When the posting has no qualification headings, return empty lists."
- Technical `named_terms` are also emitted as keywords (existing rules), so they flow into the requirement map and skill check.

- [ ] Step 1: Failing tests — `test_college_parse_prompt_asks_for_lines` (rendered `jd_parse` messages contain "minimum_qualifications" only when `college_mode=True`); `test_sanitize_drops_invented_lines` (a line whose `text` is not in the posting is removed, real SUU line kept); `test_no_headings_is_fine` (JDProfile with empty lists validates; old checkpoints without the fields still validate).
- [ ] Step 2: Run — FAIL. Step 3: Implement. Step 4: PASS + suite. Step 5: Commit `feat: parse qualification lines in college mode`.

### Task 3: Experience, degree, and substitution in code

**Files:**
- Create: `resume_tailor/qualifications.py`
- Modify: `models.py` (`Education.credits_completed: int | None = None`, `Education.credit_system: Literal["semester", "quarter"] = "semester"`)
- Test: `tests/test_qualifications.py` (new)

**Interfaces:**
- Produces in `resume_tailor/qualifications.py`:
  - `def months_between(start: str | None, end: str | None, today: date) -> int` — `YYYY-MM` or `YYYY` (→ month 01 for start, 12 for end); `end` None/"Present" → `today`; future end clamps to `today`; never negative; missing start → 0.
  - `def role_matches_domain(work: Work, domain: str | None) -> bool` — tokens of `domain` split on `/ , and` and spaces, minus `{"experience","recent","related","field","of","in","the","or"}`; match when the first 5 letters of any token prefix a word in `position` or any highlight (case-insensitive). `domain` None → every role with a position matches.
  - `def experience_months(master: JSONResume, domain: str | None, today: date) -> int` — union of matching roles' month ranges (overlaps once).
  - `def years_label(months: int) -> str` — `"2+ years"` for 28, `"2 years"` for 24, `"1 year"` for 12, `"less than 1 year"` below 12.
  - `def substitution_years(education: Sequence[Education]) -> float` — completed credits / 30 (semester) or / 45 (quarter), summed.
  - `@dataclass class QualificationStatus: text: str; type: str; status: Literal["covered", "covered_with_substitution", "unsupported", "supported_not_on_page"]; reason: str; fact_ids: list[str]`
  - `def assess_experience(line, master, jd, today) -> QualificationStatus` — covered when `experience_months / 12 >= line.years`; else when `jd.allows_substitution` and work years + `substitution_years` ≥ `line.years` and the same posting has no `degree` line that the education is needed for → `covered_with_substitution`; a `degree` line in the same posting → `unsupported` with reason "covered only with substitution; your degree is used for the degree line"; else `unsupported` with reason "posting asks N years; master shows X years Y months of <domain>".
  - `def assess_degree(line, master, jd, today) -> QualificationStatus` — a bachelor's line matches education whose `studyType` contains bachelor/BS/B.S./BA; an `endDate` after `today` is accepted only when the line or posting says "imminent", "expected", "anticipated", or "completion" (case-insensitive), else unsupported "degree expected <Mon YYYY>; posting asks for a completed degree". A `degree` line with `years` is also checked by `assess_experience`, and the worse status wins.

- [ ] Step 1: Failing tests using the real master shape (Facilities 2024-04→2026-04, Fanatics 2026-06→Present, Data Analyst 2025-08→2025-12, Help Desk 2023-02→2023-05) with `today=date(2026, 10, 21)`:
  - `test_web_development_months_union`: domain "web development/programming" → `experience_months == 28`; `years_label(28) == "2+ years"`.
  - `test_months_never_negative_or_future`: `months_between("2027-01", None, today) == 0`; `months_between("2024", "2024", today) == 11`; `months_between(None, "2025-01", today) == 0`; future end clamps.
  - `test_two_years_line_is_covered` / `test_three_years_line_is_flagged_with_reason` (reason contains "2 years 4 months").
  - `test_substitution_only_when_posting_allows` (90 completed semester credits = 3.0 years; covered_with_substitution only when `allows_substitution`).
  - `test_degree_plus_years_line_not_double_counted` (Review Focus 3).
  - `test_expected_degree_needs_imminent_wording`.
- [ ] Step 2: Run — FAIL. Step 3: Implement. Step 4: PASS + suite. Step 5: Commit `feat: compute experience, degree, and substitution for qualification lines`.

### Task 4: Qualification lines in the requirement map and evidence plan

**Files:**
- Modify: `keyword_coverage.py` (new `qualification_requirements`), `resume_tailor/pipeline.py` (college mode appends them to `requirements` after the map; `prompt_requirement_map` shows them), `prompts/templates/plan_evidence.jinja` (college block), `pipeline_core.py` (`proxy`/`forbidden` helpers ignore status `qualification`)
- Test: `tests/test_college_mode.py`

**Interfaces:**
- Produces: `def qualification_requirements(jd: JDProfile, start_index: int) -> list[dict]` — one item per `interpersonal`/`other` line (min and preferred): `{"id": f"Q{n}", "term": line.text, "requirement_type": "minimum_qualification" | "preferred_qualification", "weight": 6 | 3, "importance": 6 | 3, "category": "qualification", "variants": [], "status": "qualification", "matched_fact_ids": []}`.
- Selection: these ids enter `choose_selected`'s coverage greedy through the evidence planner's `matched_requirements`; their weight 6 makes entries covering minimum lines win.
- `plan_evidence.jinja` (college only): "Requirements with status `qualification` are posting qualification lines. Assign at least one bullet whose source fact shows each minimum qualification, citing that requirement id in `matched_requirements`; keep the fact's own wording; never claim a qualification no fact shows."

- [ ] Step 1: Failing tests — `test_interpersonal_lines_become_qualification_requirements` (SUU "Requires ability to work cordially with other University personnel." → `Q1`, weight 6, status `qualification`); `test_qualification_items_never_forbidden_or_proxied` (`forbidden_claim_terms`, `priority_proxies`, `missing_requirements` ignore them); `test_plan_prompt_mentions_qualification_only_in_college_mode`.
- [ ] Step 2: FAIL. Step 3: Implement. Step 4: PASS + suite. Step 5: Commit `feat: target qualification lines in evidence planning`.

### Task 5: Coverage check and flags

**Files:**
- Modify: `resume_tailor/qualifications.py` (`qualification_coverage`), `resume_tailor/pipeline.py` (run after holistic-review edits, after bullet-review resume, after fit; written to `match_report.json` as `qualification_coverage`; each non-covered row also a `tracker.warn`), `resume_tailor/bullet_review.py` + `resume_tailor/fit_recovery.py` (recompute after their re-render), `static/app.js` (Review tab section "Qualifications" listing rows with status and reason)
- Test: `tests/test_college_mode.py`

**Interfaces:**
- Produces: `def qualification_coverage(final_resume: ScoredResume, plain: JSONResume, jd: JDProfile, master: JSONResume, plan: EvidencePlan, requirements: Sequence[dict], today: date) -> list[dict]` — one row per min and preferred line: `{"text", "type", "required": bool, "status", "reason"}`.
  - `experience_length`/`degree`: Task 3 assessors, then the page must show the figure or degree (literal check against `plain`: the summary's years label, or the degree on the education line); else `supported_not_on_page`.
  - `technical`: every `named_terms` item that is a requirement must be `direct` and mentioned on the page (bullets, skills, summary); confirmed skills count. Missing in master → `unsupported` "not in your resume (tick it in the skill check if you know it)".
  - `interpersonal`/`other`: covered when a rendered bullet's `source_ids` intersect the fact ids of evidence-plan assignments whose `matched_requirements` include the line's `Q` id; supported but cut → `supported_not_on_page`; no assignment → `unsupported` "no fact shows this".
- Pipeline: never blocks rendering; `pipeline_status` unchanged.

- [ ] Step 1: Failing tests — `test_suu_lines_covered_or_flagged` (fixture SUU profile + real-shaped master + hand-built plan: cordially-with-personnel covered via Facilities "Collaborated directly with field staff" fact; Section 508 unsupported until confirmed, covered after confirming and the bullet/skill shows it); `test_cut_bullet_reports_supported_not_on_page`; `test_report_contains_rows_and_does_not_block` (stub run in college mode exits 0 with `qualification_coverage` in the report).
- [ ] Step 2: FAIL. Step 3: Implement. Step 4: PASS + suite. Step 5: Commit `feat: qualification coverage check and flags`.

### Task 6: Two pages and more content

**Files:**
- Modify: `render.py` (`fit_to_one_page(..., max_pages: int = 1)`; loop returns when `pages <= max_pages`; messages say "N-page fit"), `resume_tailor/fit_recovery.py` (`FitRecoveryBundle.max_pages: int = 1`, `page_count` validated `> max_pages`, `_recommend`/`apply_fit_recovery` compare with `max_pages`), `resume_tailor/bullet_review.py` (persisted bundle carries `max_pages`; its fit call passes it), `resume_tailor/runtime.py` (`COLLEGE_MAX_SELECTED_WORK = 5`, `COLLEGE_MAX_SELECTED_PROJECTS = 4`, `COLLEGE_MAX_PAGES = 2`), `pipeline_core.py` (`work_bullet_targets(sources, budget: int = WORK_BULLET_BUDGET)`; `COLLEGE_WORK_BULLET_BUDGET = 16`), `resume_tailor/pipeline.py` (caps, budget, and `max_pages` by mode)
- Test: `tests/test_render.py`, `tests/test_fit_recovery.py`, `tests/test_college_mode.py`

**Interfaces:**
- Produces: `fit_to_one_page(scored_resume, out_dir, page_counter=None, max_iterations=100, progress_callback=None, exhaustion_handler=None, max_pages: int = 1)`; `FitRecoveryBundle.max_pages`; `work_bullet_targets(sources, budget=...)`.

- [ ] Step 1: Failing tests — `test_fit_accepts_two_pages_when_allowed` (counter returns 2 → no trim with `max_pages=2`; trims with default); `test_fit_recovery_bundle_respects_max_pages` (bundle with `max_pages=2, page_count=3` valid; `page_count=2` invalid); `test_resumed_bullet_review_keeps_two_page_limit` (Review Focus 5); `test_college_selects_more_entries` (stub run in college mode selects 5 work entries when 5 exist, budget 16).
- [ ] Step 2: FAIL. Step 3: Implement. Step 4: PASS + suite (existing one-page tests untouched). Step 5: Commit `feat: two-page budget in college mode`.

### Task 7: Summary section

**Files:**
- Create: `prompts/templates/write_summary.jinja`
- Modify: `models.py` (`SummaryDraft(StrictModel): text: str = Field(min_length=20, max_length=400); source_fact_ids: list[str]`), `resume_tailor/pipeline.py` (`WRITING_TEMPLATES` gains `write_summary`; stage after holistic review, college only; result set as `basics.summary` of the final resume), `resume_tailor/progress.py` (`Stage.WRITE_SUMMARY = "Write summary"`), `templates/latex/jakes.tex.jinja` (Summary section after the header when `summary`), `render.py` (`build_context` adds `summary`; `_education_ctx` adds "N credits completed" to the score slot when `credits_completed` is set and there is room: `"{score} · N credits completed"` or just the credits)
- Test: `tests/test_college_mode.py`, `tests/test_render.py`

**Interfaces:**
- Produces: `def validate_summary(draft: SummaryDraft, title: str, years_label: str, fact_index: Mapping[str, dict]) -> list[str]` (problems) — must contain the posting title (case-insensitive) and, if it states any number of years, exactly `years_label`; every number must appear in `years_label` or in a cited fact; every cited id must exist; ≤ 60 words.
- `def fallback_summary(title: str, years_label: str, domain: str | None, covered: Sequence[str]) -> str` — `f"{title} candidate with {years_label} of {domain or 'software'} experience across {', '.join(covered[:3])}."` (covered = the first covered qualification phrases, shortened to ≤ 6 words each).
- Big-company mode: `basics.summary` stays `None` in the final resume (it already is), so the template prints nothing.

- [ ] Step 1: Failing tests — `test_summary_rejects_uncomputed_years` (Review Focus 4: draft "…with 3 years…" against label "2+ years" → problem; pipeline uses fallback); `test_summary_must_name_title`; `test_fallback_summary_text` (exact string for SUU: "UX/UI Developer candidate with 2+ years of web development/programming experience across …"); `test_template_renders_summary_only_when_set` (`render_tex` with/without `basics.summary`); `test_credits_render_in_education_line`.
- [ ] Step 2: FAIL. Step 3: Implement. Step 4: PASS + suite. Step 5: Commit `feat: college-mode summary section`.

### Task 8: College chips for named standards

**Files:**
- Modify: `resume_tailor/pipeline.py` (`check_skills`: in college mode also offers `named_terms` of qualification lines that no master fact mentions and that are unanswered), `static/app.js` (no change beyond Task 1's flag)
- Test: `tests/test_skill_check.py`

**Interfaces:**
- Consumes: `QualificationLine.named_terms` (Task 2), `answered_keys`, `term_variants`.
- Produces: chips with `status="missing"` for e.g. "Section 508", "ADA"; confirmed terms become skill facts (existing Confirmed Skills group).

- [ ] Step 1: Failing test `test_college_check_offers_standards_from_lines` (SUU-shaped profile with line naming "Section 508" and "ADA" → both chips in college mode, absent otherwise; answered terms suppressed).
- [ ] Step 2: FAIL. Step 3: Implement. Step 4: PASS + suite. Step 5: Commit `feat: offer qualification standards in the skill check`.

### Task 9: End-to-end verification (live)

**Files:** none.

- [ ] Step 1: Ask the user first (spends Gemini quota). Run the SUU posting (`jds/uiux_developer_utah_university.txt`) with the switch on and off, and the Fordham posting with the switch on.
- [ ] Step 2: Check: every SUU minimum line is covered or flagged with a reason; "Two years recent web development/programming experience" shows "2+ years" in the summary; Section 508/ADA chip offered; output ≤ 2 pages; summary names "UX/UI Developer"; switch-off output matches big-company mode; Fordham tool gaps come through chips.
- [ ] Step 3: Report numbers to the user.
