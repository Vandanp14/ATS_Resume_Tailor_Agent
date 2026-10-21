# Resume Flow, Model Routing, and Skill Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every AI call get the right context, put the user's strongest real content on the page with literal JD keywords, add a pre-run skill check whose confirmed skills become facts, and route Gemini models by job type.

**Architecture:** Changes stay inside the existing pipeline (`resume_tailor/pipeline.py` + `pipeline_core.py` + `keyword_coverage.py`). Confirmed skills are stored in `master.json` as an ordinary skill group, so the existing fact index, requirement map, and skills validation treat them as facts with no special path; only the per-bullet technology-provenance check needs an exemption. The skill check runs the pipeline's first two stages ahead of the job and hands their checkpoints to the job through the existing resume mechanism.

**Tech Stack:** Python 3.13, Pydantic v2, FastAPI, google-genai, Jinja2 prompts, vanilla JS front end (`static/`), pytest (`.venv/bin/python -m pytest`).

**Spec:** `docs/superpowers/specs/2026-10-21-resume-flow-and-skill-check-design.md`

## Global Constraints

- Local-only app; ship = merge to main.
- Do not touch: calibration examples in `prompts/templates/_bullet_guide_rules.jinja` (including the "50 ms SLA" example), the five rotating bullet shapes, or warn-only style/metric checks.
- No extra AI calls per run. The JD parse is never repeated. (See "Deviation" in Task 8: the requirement-map re-run the spec allowed is not needed.)
- Every model call keeps going through `PrivacyGuard` (`resume_tailor/pipeline.py:392`).
- One-page output stays (`fit_to_one_page`).
- The AI never adds a skill the user did not confirm; a skill is never asked twice.
- Checkpoint resume, bullet-review pause, and fit-recovery pause keep working.
- Model RPM for models the spec omits: conservative default `10`, overridable in `.env`.
- Run the full suite after every task: `.venv/bin/python -m pytest -q` must stay green, except for tests a task explicitly updates.

## Review Focus

1. **Answer persistence across reruns:** a skill answered on one job must not reappear as a chip on the next job with the same or different JD (normalize case and aliases: "postgres" vs "PostgreSQL"). Test in Task 9.
2. **Master write while a job runs:** saving answers rewrites `master.json` while a queued job may be reading it; the write must be atomic (temp file + `os.replace`) so a job never reads a half-written file. Test in Task 7.
3. **Skill check on an old/expired check id:** creating a job with a `skill_check_id` whose directory is gone, or whose JD text differs, must still run (no reuse), not fail. Test in Task 10.
4. **No current role:** a master whose every work entry has an end date must still select and order correctly (most recent first) and not crash on missing/partial dates (`"2024"`, `None`). Test in Task 5.
5. **Umbrella lists the splitter misreads:** "experience with tools such as Git" (one item) or "including but not limited to" must produce clean terms, never empty strings or fragments like "or Google Cloud". Test in Task 4.

---

### Task 1: Probe which models the key can call

**Files:**
- Create: `scripts/probe_models.py`
- Modify: `~/.claude/projects/-Users-vandanpatel-Desktop-ATS-Resume-Tailor-Agent/memory/gemini-key-model-availability.md` (results)

**Interfaces:**
- Produces: probe results used to fill defaults in Task 2 (which chain members exist; the real Gemma 4 model id, if any).

- [ ] **Step 1: Write `scripts/probe_models.py`** — `main() -> int`: list models via `client.models.list()`, print any id containing `gemma`; then for each of `gemini-3.8-flash, gemini-3.7-flash, gemini-3.6-flash, gemini-3.5-flash, gemini-3.5-flash-lite, gemini-3.1-flash-lite, gemini-2.5-pro, gemini-2.5-flash` send `"Reply with OK."` with `max_output_tokens=5` and print `model: OK | <status code> <first 80 chars of error>`. Reads `GEMINI_API_KEY` from `.env` via `prompt.py`.
- [ ] **Step 2: Ask the user before running it** (it spends ~10 requests of their quota). Run: `.venv/bin/python scripts/probe_models.py`. Expected: one line per model.
- [ ] **Step 3: Record results** in the memory file (date 2026-10-21, per-model outcome, Gemma id). If a model in Task 2's chains fails with 404/403, drop it from that chain's default; if Gemma has no usable id, drop it from the fix chain.
- [ ] **Step 4: Commit** `scripts/probe_models.py` — `chore: add Gemini model probe script`.

### Task 2: Three model chains and per-model RPM in config

**Files:**
- Modify: `prompt.py:82-88` (chain lists), add RPM table; `resume_tailor/config.py` (`resolve_chains`); `resume_tailor/web/jobs.py:907-918` (`_model_kwargs`); `resume_tailor/cli.py` (wherever `resolve_chains` is consumed); `.env.example`
- Test: `tests/test_model_routing.py` (new)

**Interfaces:**
- Produces (in `prompt.py`):
  - `PLANNING_MODELS` default `"gemini-3.8-flash,gemini-3.5-flash,gemini-3.5-flash-lite"`
  - `WRITING_MODELS = _model_list("WRITING_MODELS", "gemini-3.7-flash,gemini-3.6-flash,gemini-3.5-flash-lite")`
  - `FIX_MODELS = _model_list("FIX_MODELS", "gemini-3.5-flash-lite,gemini-3.1-flash-lite,<gemma id from Task 1 or omitted>")`
  - `MODEL_RPM: dict[str, int]` = `{"gemini-3.8-flash": 10, "gemini-3.5-flash-lite": 15, "gemini-2.5-flash": 10, "gemini-2.5-pro": 5}` plus the Gemma id at 15 if present; overrides parsed from env `MODEL_RPM="model=rpm,model=rpm"`.
  - `DEFAULT_MODEL_RPM = 10`
  - `def model_rpm(model: str | None) -> int` — table, else `DEFAULT_MODEL_RPM`.
- Produces (in `resume_tailor/config.py`):
  - `@dataclass(frozen=True) class ModelChains: model: str; planning: tuple[str, ...]; writing: tuple[str, ...]; fixes: tuple[str, ...]; fallback: tuple[str, ...]`
  - `def resolve_chains(mode: ProviderMode | str = ProviderMode.GEMINI, freellm_model: str | None = None) -> ModelChains` — `gemini`: `(DEFAULT_MODEL, PLANNING_MODELS, WRITING_MODELS, FIX_MODELS, FALLBACK_MODELS)`; `freellm`: proxy model, all chains `()`; `freellm_gemini`: proxy prepended to planning, writing, fixes; `gemini_freellm`: proxy appended to planning, writing, fixes, fallback.
  - `jobs._model_kwargs` returns `{"model", "planning_models", "writing_models", "fix_models", "fallback_models"}` for non-gemini modes; gemini keeps `{"model": self.model}`.

- [ ] **Step 1: Write failing tests** in `tests/test_model_routing.py`:
  - `test_gemini_mode_has_three_chains`: `c = resolve_chains("gemini")`; `assert c.writing[0] == "gemini-3.7-flash"` and `c.planning[0] == "gemini-3.8-flash"` and `c.fixes[0] == "gemini-3.5-flash-lite"` (with env unset via `monkeypatch.delenv`; reload `prompt` + `resume_tailor.config` with `importlib.reload`).
  - `test_mixed_modes_place_proxy`: `resolve_chains("freellm_gemini", "auto").writing[0] == "freellm/auto"`; `resolve_chains("gemini_freellm", "auto").writing[-1] == "freellm/auto"`; `resolve_chains("freellm", "auto").writing == ()`.
  - `test_model_rpm_defaults_and_overrides`: `model_rpm("gemini-3.7-flash") == 10`; `model_rpm("gemini-3.5-flash-lite") == 15`; with `MODEL_RPM="gemini-3.7-flash=20"` after reload, `model_rpm("gemini-3.7-flash") == 20`.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_model_routing.py -v` — Expected: FAIL (`ModelChains`/`WRITING_MODELS` undefined).
- [ ] **Step 3: Implement** the produced names; update callers of the old 3-tuple `resolve_chains` (`grep -rn resolve_chains resume_tailor tests`); document `WRITING_MODELS`, `FIX_MODELS`, `MODEL_RPM` in `.env.example`.
- [ ] **Step 4: Run** the new tests and full suite. Expected: PASS.
- [ ] **Step 5: Commit** — `feat: writing and fix model chains with per-model RPM`.

### Task 3: Pipeline routes stages to chains; per-model pacing

**Files:**
- Modify: `resume_tailor/pipeline.py:155-176` (template sets), `:370-430` (`__init__`), `:455-460` (`_chain_for`); `resume_tailor/runtime.py:98-123` (`RatePacer`)
- Test: `tests/test_model_routing.py`

**Interfaces:**
- Consumes: `WRITING_MODELS`, `FIX_MODELS`, `model_rpm` (Task 2).
- Produces:
  - `WRITING_TEMPLATES = frozenset({"jd_parse", "tailor_skills", "tailor_work", "tailor_projects"})`, `FIX_TEMPLATES = frozenset({"concise_bullet", "regenerate_bullet", "audit_concision"})` in `pipeline.py`.
  - `TailorPipeline.__init__(..., writing_models: Sequence[str] | None = None, fix_models: Sequence[str] | None = None)`; attributes `self.writing_chain`, `self.fix_chain` built like `planning_chain` (`_dedupe([*writing_models, *self.default_chain])`), defaults from config only when `chains_enabled`. `planning_only_models` becomes every model in planning/writing/fix chains not in `default_chain`.
  - `_chain_for(template_name) -> tuple[str, ...]`: planning → `planning_chain`, writing → `writing_chain`, fixes → `fix_chain`, else `default_chain`.
  - `RatePacer(min_interval: float, tracker=None, interval_for: Callable[[str | None], float] | None = None)`; `wait(model)` uses `interval_for(model)` when given, else `min_interval`. Pipeline passes `interval_for=lambda m: 60.0 / model_rpm(m) if call_interval > 0 else 0.0`.

- [ ] **Step 1: Write failing tests:**
  - `test_rewrite_templates_use_writing_chain`: build `TailorPipeline(model="gemini-3.1-flash-lite", provider=<stub with supports_model_chain = True>, planning_models=["p1"], writing_models=["w1"], fix_models=["f1"], fallback_models=["fb"])`; assert `_chain_for("tailor_work")[0] == "w1"`, `_chain_for("concise_bullet")[0] == "f1"`, `_chain_for("select_work")[0] == "p1"`, `_chain_for("research_company_stack")[0] == "gemini-3.1-flash-lite"`, and each chain ends with `("gemini-3.1-flash-lite", "fb")`.
  - `test_pacer_uses_per_model_interval`: `RatePacer(4.5, interval_for={"a": 6.0, "b": 0.0}.get)` with `time.sleep` and `time.monotonic` monkeypatched; two `wait("a")` calls sleep ≈6.0; two `wait("b")` calls never sleep.
- [ ] **Step 2: Run** them — Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces; `PLANNING_MAX_OUTPUT_TOKENS` and planning timeout logic unchanged.
- [ ] **Step 4: Run** new tests + full suite — Expected: PASS.
- [ ] **Step 5: Commit** — `feat: route stages to reasoning, writing, and fix chains`.

### Task 4: Literal JD terms from umbrella lists

**Files:**
- Modify: `prompts/templates/jd_parse.jinja` (rule + worked example); `keyword_coverage.py` (new function after `sanitize_jd_profile`, `:534`); `resume_tailor/pipeline.py:1302` (call it)
- Test: `tests/test_requirement_coverage.py`

**Interfaces:**
- Produces: `def expand_example_lists(jd: JDProfile) -> tuple[JDProfile, list[str]]` in `keyword_coverage.py`. Returns the expanded profile and the list of added terms. For each keyword whose `evidence_span` contains a marker (`such as`, `e.g.`, `e.g.,`, `including`, `including but not limited to`, `like`) followed by a list, or a parenthesised list after the term, split the list on `,`, ` or `, ` and `, `/`; strip `etc.`, articles, and trailing punctuation; drop empty items and items longer than 4 words. Each item that is not already a keyword (by `normalize_term`) becomes `KeywordWeight(term=item, weight=umbrella.weight, aliases=[], category=umbrella.category, evidence_span=umbrella.evidence_span)`. Items inherit the umbrella's list membership (added to `must_have_skills` / `nice_to_have_skills` where the umbrella is). The umbrella is removed from those lists and its keyword weight set to `1`.
- Pipeline: call right after `sanitize_jd_profile`; `tracker.detail("Expanded JD lists: " + ", ".join(added))` when non-empty.

- [ ] **Step 1: Write failing tests** (use the real HCLTech spans):
  - `test_cloud_platforms_such_as_expands`: umbrella `"Cloud Platforms"` (nice-to-have, weight 2, category `platform`, span `"cloud platforms such as AWS, Azure, or Google Cloud"`) → `nice_to_have_skills` contains `"AWS"`, `"Azure"`, `"Google Cloud"` and not `"Cloud Platforms"`; the `"Cloud Platforms"` keyword weight is `1`; added == `["AWS", "Azure", "Google Cloud"]`.
  - `test_single_item_and_but_not_limited_to`: span `"tools such as Git"` → adds `["Git"]`; span `"including but not limited to Jira, Confluence"` → adds `["Jira", "Confluence"]`; no added term is empty or starts with `"or "`/`"and "`.
  - `test_no_marker_is_unchanged`: span `"React.js"` → profile equal to input, added `[]`.
  - `test_existing_keyword_not_duplicated`: `"AWS"` already a keyword → not added twice.
- [ ] **Step 2: Run** — Expected: FAIL (`expand_example_lists` undefined).
- [ ] **Step 3: Implement** `expand_example_lists`; add the prompt rule to `jd_parse.jinja` RULES: "When the posting names concrete examples of a category (\"such as A, B, or C\", \"e.g.\", \"including\"), list each example as its own keyword with its own evidence span; the category label may stay only as a weight-1 keyword." Add one worked-example line showing `"cloud platforms such as AWS or Azure"` → `AWS`, `Azure`.
- [ ] **Step 4: Run** tests + full suite — Expected: PASS.
- [ ] **Step 5: Commit** — `feat: expand umbrella JD terms into literal keywords`.

### Task 5: Current role always selected and listed first

**Files:**
- Modify: `pipeline_core.py:417-511` (`choose_selected`), add helpers near it; `resume_tailor/pipeline.py:1418-1437` (pass `pin_current=True` for work)
- Test: `tests/test_tailor.py` (update `test_selector_requires_exact_count_and_orders_by_relevance` at `:268` for work ordering)

**Interfaces:**
- Produces in `pipeline_core.py`:
  - `def is_current(entry: Mapping) -> bool` — `endDate` missing/`None`/`""`, or `casefold()` in `{"present", "current", "now"}`.
  - `def current_role_id(evidence: Sequence[dict]) -> str | None` — first current entry's `source_id`; if none, the entry with the latest `endDate` (compare as zero-padded `YYYY-MM`; `"2024"` → `"2024-00"`; missing dates sort last).
  - `def chronological(entries: Sequence[dict]) -> list[dict]` — current entries first, then by `endDate` desc, then `startDate` desc, using the same date key.
  - `choose_selected(..., pin_current: bool = False)` — when true, `current_role_id(evidence)` is picked first (before the greedy loop, its cover added to `covered`), and the final list is `chronological(...)` instead of the relevance sort. Projects call without the flag (behaviour unchanged).

- [ ] **Step 1: Write failing tests** in `tests/test_tailor.py`:
  - `test_current_role_is_pinned_even_when_least_relevant`: three candidates where the current role (`endDate=None`) has relevance 10 and others 90, 80, 70 with cap 3 of 4 → current is selected and is element `[0]`; remaining order is reverse chronological.
  - `test_no_current_role_uses_most_recent`: all entries have end dates incl. one `"2024"` and one missing `startDate` → no exception; most recent `endDate` is first.
  - Update the `:268` test's expected work order to chronological.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement**; pass `pin_current=True` through `_select` for `select_work` only (add a `pin_current: bool = False` kwarg to `TailorPipeline._select`).
- [ ] **Step 4: Run** tests + full suite — Expected: PASS.
- [ ] **Step 5: Commit** — `feat: always include current role and order work chronologically`.

### Task 6: Work bullet budget by strength

**Files:**
- Modify: `pipeline_core.py:48` (replace `WORK_BULLET_COUNTS`), `:513-517` (`work_bullet_targets`)
- Test: `tests/test_tailor.py` (update assertion at `:287`)

**Interfaces:**
- Produces: `WORK_BULLET_BUDGET = 10`, `MIN_WORK_BULLETS = 2`, `MAX_WORK_BULLETS = 5`; `def work_bullet_targets(sources: Sequence[dict]) -> dict[str, int]` (same signature; all three existing callers keep working). Strength of an entry = `selection_relevance` (default 0) + `10 * len(selection_covered_requirement_ids)`. Each entry's cap = `min(MAX_WORK_BULLETS, number of highlight facts in source_facts)`, floor `min(MIN_WORK_BULLETS, cap)`. Start every entry at its floor; hand out the remaining budget one bullet at a time to the entry with the highest `strength / allocated` that is below its cap (ties: earlier in `sources`). Then if a current entry (`is_current`) has fewer bullets than another entry, move bullets from the largest other entry until it is ≥ every other (respecting caps). Total may be < 10 only when caps make 10 impossible.

- [ ] **Step 1: Write failing tests:**
  - `test_current_role_gets_at_least_as_many_bullets`: current entry with 14 highlights, relevance 40, 1 covered id; two others with 8 highlights, relevance 90, 3 covered ids → current count ≥ each other; total 10.
  - `test_caps_respect_available_highlights`: an entry with 3 highlights never gets > 3; total = sum of caps when caps < 10.
  - Update `:287` to assert the new totals/relationships rather than `{4,3,3}` literals.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run** tests + full suite — Expected: PASS.
- [ ] **Step 5: Commit** — `feat: distribute work bullets by evidence strength`.

### Task 7: Store skill answers in the master resume

**Files:**
- Create: `resume_tailor/skill_answers.py`
- Modify: `models.py:143-156` (`JSONResume`), `resume_tailor/pipeline.py:1394-1395` (tech-requirement exemption)
- Test: `tests/test_skill_check.py` (new)

**Interfaces:**
- Produces in `models.py`: `CONFIRMED_SKILL_GROUP = "Confirmed Skills"`; `class SkillCheckAnswers(BaseModel): declined: list[str] = Field(default_factory=list)`; `JSONResume.skill_check: SkillCheckAnswers | None = None`.
- Produces in `resume_tailor/skill_answers.py`:
  - `def confirmed_terms(master: JSONResume) -> list[str]` — keywords of the skill group named `CONFIRMED_SKILL_GROUP`.
  - `def answered_keys(master: JSONResume) -> set[str]` — `normalize_term` of confirmed + declined + every keyword in every other skill group.
  - `def apply_answers(master: JSONResume, confirmed: Sequence[str], declined: Sequence[str]) -> JSONResume` — returns a copy; confirmed terms appended to the confirmed group (created if absent, de-duplicated by `normalize_term`), removed from declined; declined terms appended to `skill_check.declined`, removed from the confirmed group.
  - `def replace_answers(master, confirmed, declined) -> JSONResume` — sets both lists exactly (for the edit row).
  - `def save_master(master: JSONResume, path: Path) -> None` — `model_dump_json(indent=2, exclude_none=True)` to `path.with_suffix(".json.tmp")` then `os.replace`.
- Pipeline: `tech_requirements = tuple(t for t in supported_tech_requirements(requirements) if normalize_term(t[0]) not in {normalize_term(c) for c in confirmed_terms(master)})`, so a bullet may name a confirmed skill without citing a fact that names it. (Confirmed skills are skill facts already via `skill_evidence`, so they are `direct` in the requirement map and never in `forbidden_terms`; `validate_skills` allows them via `master.skills`.)

- [ ] **Step 1: Write failing tests** in `tests/test_skill_check.py`:
  - `test_apply_answers_round_trip`: start with master containing skills group `Languages: [Python]`; `apply_answers(m, ["Figma", "figma"], ["Siteimprove"])` → confirmed group `["Figma"]`, `skill_check.declined == ["Siteimprove"]`; `apply_answers(that, ["Siteimprove"], [])` moves it to confirmed; `answered_keys` contains `normalize_term("python")`, `"figma"`, `"siteimprove"` keys.
  - `test_save_master_is_atomic`: monkeypatch `os.replace` to record calls; `save_master` writes only the `.json.tmp` file then replaces; reloading with `load_master` returns equal data.
  - `test_confirmed_skill_is_direct_and_allowed_in_bullet`: build facts with `master_fact_index` for a master whose confirmed group has `"Figma"` and a JD keyword `"Figma"` (category `tool`); `requirement_map(jd, facts)` marks it `direct`; `forbidden_claim_terms` excludes it; the pipeline's exempted `tech_requirements` excludes it (call a small helper `bullet_tech_requirements(requirements, master)` you add to `skill_answers.py` and use in the pipeline).
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement**; confirm `PrivacyGuard.protect` and `load_master` accept the new field (`.venv/bin/python -m pytest tests/test_privacy.py -q`).
- [ ] **Step 4: Run** tests + full suite — Expected: PASS.
- [ ] **Step 5: Commit** — `feat: store confirmed and declined skills in master`.

### Task 8: Stage-scoped checkpoint keys

**Files:**
- Modify: `resume_tailor/checkpoints.py` (`run_fingerprint`, `CheckpointStore`), `resume_tailor/pipeline.py:1274-1283`, `:1295-1301`, `:1369-1383`
- Test: `tests/test_checkpoints.py`

**Deviation from spec (to flag to the user):** the requirement map is computed in code (`requirement_map`, regex over facts); only the proxy plan is an AI call. After answers are saved, recomputing the map in code marks confirmed skills `direct`, and the saved proxy plan only needs entries for still-missing terms dropped. That gives the re-run's result for confirmed terms with zero extra calls, so no re-run is made.

**Interfaces:**
- Produces:
  - `CHECKPOINT_VERSION = 2`.
  - `def stage_fingerprint(stage: str, *, master_json: str, jd_text: str, **options: object) -> str` — for `"jd_parse"` hashes only version + `jd_text` + options; for `"requirement_map"` hashes version + `master_json` with the `CONFIRMED_SKILL_GROUP` group and `skill_check` removed + `jd_text` + options; every other stage hashes the full master as today.
  - `CheckpointStore(out_dir, fingerprint_for: Callable[[str], str])` — `load/save/has` use `fingerprint_for(name)`.
  - Requirement-map checkpoint stores only `{"proxy_plan": ...}`; restore recomputes `requirement_map(jd, facts)` from current facts, drops proxies whose requirement is now `direct`, then applies `attach_proxies`.

- [ ] **Step 1: Write failing tests** in `tests/test_checkpoints.py`:
  - `test_jd_parse_checkpoint_survives_master_change`: save `jd_parse` under master A, load under master B with same JD → hit.
  - `test_requirement_map_survives_only_answer_changes`: adding a confirmed skill → hit; editing a work highlight → miss.
  - `test_restored_map_marks_confirmed_skill_direct`: saved proxy plan has a proxy for `"Figma"`; after confirming `"Figma"`, restored requirements show `"Figma"` `direct` with no proxy fields.
  - `test_old_version_checkpoint_ignored`: a version-1 file → miss.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement**; update existing `CheckpointStore(...)` call sites and tests that construct it.
- [ ] **Step 4: Run** tests + full suite — Expected: PASS.
- [ ] **Step 5: Commit** — `feat: stage-scoped checkpoint fingerprints`.

### Task 9: `check_skills` in the pipeline

**Files:**
- Modify: `resume_tailor/pipeline.py` (new method; extract the parse + requirement-map block of `run()` (`:1295-1415`) into `_prepare_requirements(master, jd_text) -> PreparedRequirements` used by both)
- Modify: `models.py` (response model)
- Test: `tests/test_skill_check.py`

**Interfaces:**
- Produces:
  - `class SkillChip(BaseModel): term: str; status: Literal["proxy", "missing"]; evidence_span: str | None; close_to: list[str]` (proxy terms when status is `proxy`).
  - `class SkillCheckResult(BaseModel): chips: list[SkillChip]; remembered_confirmed: list[str]; remembered_declined: list[str]`.
  - `TailorPipeline.check_skills(master: JSONResume, jd_text: str, out_dir: Path) -> SkillCheckResult` — runs preflight-free parse + `expand_example_lists` + requirement map with checkpoints saved in `out_dir/checkpoints`; chips = requirements with status `missing`/`proxy`, `category in TECH_CATEGORIES`, `normalize_term(term) not in answered_keys(master)`, de-duplicated; no chips for `soft_skill`, `responsibility`, `domain_skill`, `methodology`, `other`.
  - `@dataclass class PreparedRequirements: jd: JDProfile; jd_json: str; evidence: dict[str, list[dict]]; facts: dict[str, dict]; requirements: list[dict]; proxy_plan: RequirementProxyPlan` in `pipeline.py`. `_prepare_requirements` owns the `PARSE_JD` and `MAP_REQUIREMENTS` tracker stages and their checkpoints; company research stays in `run()` between them only when enabled (pass a `between: Callable[[JDProfile], None] | None` hook).
  - `run()` behaviour unchanged apart from calling `_prepare_requirements`.

- [ ] **Step 1: Write failing tests** with the stub-provider pattern from `tests/test_tailor.py` (canned `jd_parse` and `plan_requirement_coverage` responses):
  - `test_check_skills_returns_only_unanswered_tech_gaps`: JD names Figma (tool, missing), Siteimprove (tool, missing, already declined), "communication" (soft_skill), React (direct) → chips `["Figma"]`; `remembered_declined == ["Siteimprove"]`.
  - `test_check_then_run_makes_no_repeat_parse_call`: call `check_skills`, copy its `checkpoints/` into a run dir, `apply_answers` to confirm Figma, `run(..., resume=True)` → the stub records exactly one `jd_parse` and one `plan_requirement_coverage` call across both.
  - `test_alias_answer_suppresses_chip`: declined `"postgres"` suppresses a `"PostgreSQL"` chip.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement**.
- [ ] **Step 4: Run** tests + full suite — Expected: PASS.
- [ ] **Step 5: Commit** — `feat: pre-run skill check from parse and requirement map`.

### Task 10: Web endpoints for the skill check

**Files:**
- Modify: `resume_tailor/web/app.py` (routes, near `:372`), `resume_tailor/web/models.py:68-121` (`CreateJobRequest`, `QueuePayload`), `resume_tailor/web/jobs.py:547-606` (`enqueue`)
- Test: `tests/test_webapp.py`

**Interfaces:**
- Produces:
  - `POST /api/skill-check` body `SkillCheckRequest {jd_text: str, provider_mode: ProviderModeName = "gemini", freellm_model: str | None}` → `200 {check_id: str, chips: [...], remembered_confirmed: [...], remembered_declined: [...]}`. Runs `pipeline.check_skills` via `asyncio.to_thread` in `state_dir/skill_checks/<check_id>/`, with `load_master(master_path)` fresh and the shared scheduler provider. Stores `jd_sha256` in `state_dir/skill_checks/<check_id>/check.json`.
  - `POST /api/skill-check/{check_id}/answers` body `{confirmed: list[str], declined: list[str]}` → applies `apply_answers` to a fresh `load_master`, `save_master`, returns `204`.
  - `GET /api/skill-answers` → `{confirmed, declined}`; `PUT /api/skill-answers` same body → `replace_answers` + `save_master`, `204`.
  - `CreateJobRequest.skill_check_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")`; `QueuePayload` gains nothing new except `resume` set to `True` when checkpoints were copied.
  - `enqueue`: when `skill_check_id` is set, the check dir exists, and its `jd_sha256` matches the request's JD, copy `checkpoints/*.json` into the job directory and set `payload.resume = True`; otherwise proceed as a normal run.
  - Answer writes and job master reads share one `threading.Lock` on the registry (`registry.master_lock`).

- [ ] **Step 1: Write failing tests** using `webapp_factory` + `fake_factory` from `tests/conftest.py` (extend `FakePipe` with a `check_skills` returning canned chips):
  - `test_skill_check_returns_chips_and_id`.
  - `test_answers_endpoint_updates_master_file`: `master.json` in `tmp_path` gains the confirmed group and `skill_check.declined`.
  - `test_put_skill_answers_replaces_lists`.
  - `test_job_with_skill_check_copies_checkpoints_and_resumes`: payload persisted with `resume=True`, checkpoint files present in job dir.
  - `test_job_with_missing_or_mismatched_check_runs_normally`: unknown id and different JD → job queued, `resume` false, no error.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement**; keep host/origin guard and auth applying to the new routes (they are under `/api/`).
- [ ] **Step 4: Run** tests + full suite — Expected: PASS.
- [ ] **Step 5: Commit** — `feat: skill-check and skill-answer endpoints`.

### Task 11: Skill-check UI (layout B)

**Files:**
- Modify: `static/index.html` (new-job form), `static/app.js` (form submit flow), `static/app.css` (chip styles using existing tokens `--accent`, `--accent-soft`, `--accent-strong`, `--bg-soft`)
- Test: `tests/test_webapp.py` (static markup presence) + manual check

**Interfaces:**
- Consumes: Task 10 endpoints.
- Behaviour (from the approved B mockup, `.superpowers/brainstorm/*/content/skill-check.html`):
  - New-job form primary button reads **Check skills**. On click: `POST /api/skill-check`; show progress text "Checking skills…" on the button; on success, if `chips` is empty, immediately submit the job (`POST /api/jobs` with `skill_check_id`); otherwise render the panel "Do you know these? (N not in your resume)" with toggle chips (`<button aria-pressed>`), helper text "Tap to toggle. Saved to master resume.", and the button changes to **Tailor resume**.
  - **Tailor resume**: `POST /api/skill-check/{id}/answers` (pressed → confirmed, unpressed → declined), then `POST /api/jobs` with `skill_check_id`.
  - Below the chips, a collapsed `<details>` "Remembered skills" listing `remembered_confirmed` (pressed) and `remembered_declined` (unpressed) as the same chips; changing one calls `PUT /api/skill-answers` with the full lists.
  - Error state: if the check fails, show the API error text and a **Tailor without checking** button that submits the job without `skill_check_id`.
  - Editing the JD textarea after a check discards the panel and restores **Check skills**.

- [ ] **Step 1: Write a failing test** `test_index_has_skill_check_controls`: `GET /` HTML contains `id="check-skills-btn"`, `id="skill-chips"`, `id="remembered-skills"`.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** markup, JS, CSS.
- [ ] **Step 4: Run** test + full suite — Expected: PASS. Manual: start app per `START_LOCAL.txt`, paste the Fordham JD, confirm chips appear, tick Figma, run; next check on the same JD shows no chips and "Remembered skills" lists Figma pressed.
- [ ] **Step 5: Commit** — `feat: skill-check chips on the new-job form`.

### Task 12: Per-model metering in the web scheduler

**Files:**
- Modify: `resume_tailor/web/scheduler.py` (`UsageRecord`, `GeminiScheduler.wait`, `_next_allowed_under_lock`, persistence), `llm_utils.py:112-120, :207, :529-562` (attempt callback gets the model)
- Test: `tests/test_web_scheduler.py`

**Interfaces:**
- Consumes: `model_rpm` (Task 2).
- Produces:
  - `UsageRecord.model: str | None = None` (persisted; old records without it load as `None` and count toward a shared `None` bucket).
  - `GeminiScheduler.wait(model: str | None = None) -> str` — limits evaluated over records of that model only; RPM = `model_rpm(model)` when `model` is given, else `max_per_minute`; TPM and RPD stay the configured values per model.
  - `ModelRouter`/`GeminiProvider` `attempt_callback: Callable[[str], str | None]` called as `attempt_callback(model)`.
  - `snapshot()` unchanged in shape (combined totals) so the quota UI keeps working.

- [ ] **Step 1: Write failing tests:**
  - `test_models_do_not_block_each_other`: with a fake clock, 10 `wait("gemini-3.8-flash")` calls inside one minute, then `wait("gemini-3.7-flash")` returns without sleeping.
  - `test_rpm_comes_from_model_table`: 15 `wait("gemini-3.5-flash-lite")` calls within a minute do not sleep; the 16th does.
  - `test_legacy_records_without_model_load`.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement**; update the `attempt_callback` call in `llm_utils.py:207` to pass `model`.
- [ ] **Step 4: Run** tests + full suite — Expected: PASS.
- [ ] **Step 5: Commit** — `feat: per-model rate metering in web scheduler`.

### Task 13: Trim the holistic-review payload

**Files:**
- Modify: `resume_tailor/pipeline.py:1646-1704` (`holistic_review` context)
- Test: `tests/test_holistic_review.py`

**Interfaces:**
- Produces: `def review_master(master: JSONResume, selected: SelectedEvidence) -> JSONResume` in `pipeline_core.py` — copy of master with `work`/`projects` reduced to the selected source ids (in master order), all other sections kept. `holistic_review` passes `master_json=review_master(master, selected).model_dump_json(indent=2)`.

- [ ] **Step 1: Write failing test** `test_review_master_keeps_only_selected_entries`: master with 5 work and 15 projects, selection of 3 and 2 → result has 3 and 2, skills/education unchanged.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** and wire in.
- [ ] **Step 4: Run** tests + full suite — Expected: PASS.
- [ ] **Step 5: Commit** — `perf: send only selected entries to holistic review`.

### Task 14: End-to-end verification on saved postings

**Files:** none (manual runs; results summarised for the user)

- [ ] **Step 1: Ask the user before running** (uses API quota). Re-run the HCLTech JD (from `.resume-tailor/requests/e1787c60-49ae-4ffe-8c48-4b973c37f319.json`), the Fordham posting (paste from the user), and one big-company SWE posting from `.resume-tailor/requests/`.
- [ ] **Step 2: Check** for each, from `match_report.json` and `web_events.jsonl`:
  - HCLTech `keyword_coverage.computed_coverage_pct` > 25.0; `jd_profile.must_have_skills`/`nice_to_have_skills` contain concrete terms (e.g. `AWS`, not `Cloud Platforms`).
  - Fanatics is `work[0]` in `tailored.json` with ≥ as many highlights as any other entry.
  - Fordham chips include Figma / Adobe XD / Siteimprove / TERMINALFOUR; after ticking Figma, it appears in Skills and passes truth checks if used in a bullet; a second check on the same JD shows no chips.
  - Count of `jd_parse` + `plan_requirement_coverage` calls per job (stage events) ≤ before; total stage time not higher than the comparable pre-change run.
- [ ] **Step 3: Report** results to the user with the numbers.

---

## Not in this plan

- Running select work and select projects in parallel (spec §5): dropped per the spec's own fallback, because `ProgressTracker.stage` is a sequential context manager driving the web progress list; parallelising needs a stage-model change for ~10 s of gain. Revisit after Task 12 if runs are still slow.
- Reducing the STAR bullet schema size: left as a follow-up; the writing chain's stronger model is the first lever.
