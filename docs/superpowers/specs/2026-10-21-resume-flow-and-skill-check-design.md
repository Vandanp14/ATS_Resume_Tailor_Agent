# Resume flow, model routing, and skill check: design

Date: 2026-10-21
Status: draft, pending approval

## Why

The user applies to big companies and is getting almost no online assessments
(OAs) or screen passes, even though the resume content reads well. At those
companies software reads the resume first: ranking tools (Workday HiredScore,
Eightfold and similar) score title, skills, and experience against the posting,
and recruiters skim the top third of the page for a few seconds. Rejections
arrive at mixed times: same day (likely application-form knockouts, out of
scope), 2-3 days (ranker or recruiter, in scope), weeks later (bulk close-out).

A review of 48 saved runs found that the pipeline loses or hides the user's own
strongest content before it reaches the page, and that runs are slow (47 s to
21 min) mostly from free-tier 503/429 waits. This project fixes the flow so every
AI call has the right context and the page uses the best of what the master
resume has, routes Gemini models sensibly, and adds a skill-check step so the
user can confirm skills the master resume does not list.

## Goals

1. The job-description parse yields the literal terms recruiters and rankers
   search for, so real matches stop being treated as gaps.
2. The current role is always on the page, listed first, and gets bullets in
   proportion to its strength, not its relevance rank.
3. Before a run, the user can tick skills the posting names that the master
   resume lacks; ticked skills become usable facts, in Skills and in bullets.
4. Gemini models are routed by job type, using each model's independent limits,
   with the strongest available model writing the bullets.
5. Each AI call in the chain receives the context it needs and no duplicate
   context; independent calls run in parallel.

## Non-goals

- College / higher-ed mode (two pages, qualification-line matching, cover
  letter). Separate project after this one; needs template changes.
- Changing the inflation-leaning writing behaviour. The user explicitly keeps:
  calibration examples in `_bullet_guide_rules.jinja` (including the "50 ms
  SLA" example), the five rotating bullet shapes, and style/metric checks that
  warn but do not block. Do not touch these.
- Application-form knockout questions (sponsorship, grad date) — outside the app.
- Switching away from the existing LaTeX template. PDF text extraction was
  verified clean with pdfminer and MuPDF.

## Anti-goals (would make this a failure even if it works)

- The AI adding skills to the resume that the user never confirmed.
- Asking the user about the same skill twice.
- Extra AI calls per run beyond the current count, with one exception: when
  the user ticks at least one skill, the requirement map is re-run once so the
  model sees the confirmed skills (see §4). The JD parse is never repeated.
- Breaking checkpoint/resume of failed runs, privacy redaction, or the
  existing bullet-review and fit-recovery pauses.
- Slower typical runs.

## Constraints

- Local-only app; "ship" = merge to main.
- Gemini free tier on the user's key. The user's spec is
  `Gemini_Models_Spec.md` (repo root, untracked). It conflicts with a probe
  done 2026-10-01: that probe found `gemini-2.5-flash`/`-lite` return 404
  ("no longer available to new users") and `gemini-3.1-pro-preview` returns 429
  (no quota). The spec omits `gemini-3.5-flash` (currently in the planning
  chain) and gives no limits for 3.7-flash, 3.6-flash, 3.1-flash-lite.
- Free tier logs prompts; the existing privacy layer (`resume_tailor/privacy.py`)
  must keep covering every call, including new ones.
- One-page output stays (`fit_to_one_page`).

## Current flow (for reference)

`TailorPipeline.run` (`resume_tailor/pipeline.py:1259`): parse JD → (optional
company research) → map requirements → select work → select projects → plan
evidence → tailor skills → rewrite work → rewrite projects → assemble →
holistic review → validate edits → (bullet review pause) → render/fit → write.
Fixed shape: 3 jobs with 4/3/3 bullets by rank (`pipeline_core.py:48`,
`runtime.py:20-21`), 2 projects with 2 bullets. Planning stages
(`PLANNING_TEMPLATES`, `pipeline.py:157`) use `PLANNING_MODELS`
(3.8-flash, 3.5-flash); everything else, including the bullet rewrites, uses
`DEFAULT_MODEL=gemini-3.1-flash-lite`. Fixed 4.5 s gap between calls per model
(`runtime.py:18`).

## Design

### 1. Model routing

- **Re-probe first.** Before changing defaults, call each candidate model once
  with a tiny prompt on the user's key and record which answer. Candidates:
  3.8-flash, 3.7-flash, 3.6-flash, 3.5-flash, 3.5-flash-lite, 3.1-flash-lite,
  2.5-pro, 2.5-flash, Gemma 4. Update the memory note with results.
- **Three chains by job type** (final membership follows the probe):
  | Job | Stages | Chain (intended) |
  |---|---|---|
  | Reasoning | requirement map, select work, select projects, plan evidence, holistic review | 3.8-flash → 3.5-flash → 3.5-flash-lite |
  | Writing | JD parse, tailor skills, rewrite work, rewrite projects | 3.7-flash → 3.6-flash → 3.5-flash-lite |
  | Small fixes | concise/regenerate bullet, concision audit | 3.5-flash-lite → 3.1-flash-lite → Gemma 4 |
  Reasoning and writing deliberately sit on different primary models so they
  do not share a rate meter. 2.5-pro is excluded (50 RPD, likely 404). Gemma 4
  only where prompts fit its 8,192-token context.
- Configurable through `.env` the same way `PLANNING_MODELS` / `FALLBACK_MODELS`
  are today, with the new defaults in `prompt.py`.
- **Provider modes** (designer's call): the three chains apply to `gemini`
  mode. `freellm` mode keeps its single proxy model for every stage. The mixed
  modes (`freellm_gemini`, `gemini_freellm`) put the proxy model before or
  after each of the three Gemini chains, as `resolve_chains`
  (`resume_tailor/config.py`) does for two chains today.
- **Per-model pacing** from each model's RPM (e.g. 10 RPM → ~6 s, 15 RPM → ~4 s)
  instead of one fixed 4.5 s. Use the limits in `Gemini_Models_Spec.md` where
  given; for models it omits (3.7-flash, 3.6-flash, 3.1-flash-lite, 3.5-flash)
  use a conservative 10 RPM default, overridable in `.env`.
- **Web scheduler** (designer's call): `GeminiScheduler`
  (`resume_tailor/web/scheduler.py`) tracks RPM/TPM/RPD per model internally,
  since limits are per model. The quota display may stay one combined summary.
  If per-model metering turns out to be a large redesign, drop the
  parallel-selection item in §5 rather than overrun the scheduler.
- Existing fallback/cooldown/whole-chain-retry logic (`pipeline.py:560-690`)
  stays; it just receives the new chains.

### 2. Literal JD terms

Observed (HCLTech run): the parse produced umbrella labels — "Full Stack Java",
"Database Technologies", "Cloud Platforms", "Testing Frameworks" — from lines
like "cloud platforms such as AWS, Azure, or Google Cloud". The user's actual
Java/Spring Boot/AWS/SQL/Pytest were then treated as proxies, and the
deterministic coverage was 25%.

- When the posting names concrete examples ("such as A, B, or C", "e.g.",
  "including", parenthesised lists), each example becomes its own keyword with
  its own evidence span. The umbrella label may remain as a low-weight keyword.
- Must-have/nice-to-have lists contain the concrete terms, not the umbrella.
- Implement in the `jd_parse.jinja` prompt (rule plus a worked example) and,
  where cheap, a deterministic post-pass that splits "such as" lists from the
  evidence spans, so a weak model's miss is caught in code.

### 3. Current role first, bullets by strength

- The current role (no end date, or "Present") is always selected for work,
  regardless of model relevance. If there is none, the most recent role.
- Display order of work entries: current role first, then reverse
  chronological. Selection still decides *which* entries; it no longer decides
  their order.
- The total work-bullet budget stays at 10 (page fit), but it is distributed by
  each selected entry's strength (number and quality of relevant source facts,
  requirement coverage), not by position. The current role gets at least as
  many bullets as any other entry.
- The evidence plan (`plan_evidence`) receives the new per-entry targets, so
  the strongest Fanatics facts (first-ever API, shipped 3 features in 8 weeks,
  AWS SigV4) compete for slots instead of being crowded out.

### 4. Skill check (layout B, chosen by the user)

Flow in the web UI:

1. The user pastes a job description and presses **Check skills**.
2. The server runs JD parse and requirement map (the same two calls the run
   makes) and saves their results as the run's checkpoints, so the run reuses
   them instead of calling again.
3. The UI shows chips for concrete tool/technology terms from the posting that
   are not in the master resume and have not been answered before. No chips
   for degrees, years of experience, soft skills, or responsibilities.
4. The user taps the ones they know and presses **Tailor resume**.
5. Ticked terms are saved as confirmed skills; unticked terms are saved as
   "don't know". Neither is asked again. Both lists are editable later.
6. If nothing new needs asking, no chip panel appears; the button goes straight
   to tailoring.

Using confirmed skills:

- They are master-resume facts for every downstream stage: they appear in the
  Skills section and the AI may place them in work or project bullets where the
  bullet's work plausibly used them (user decision).
- The truth checks (`forbidden_claim_terms`, `scan_unsupported_technology`,
  `supported_tech_requirements`, requirement-map status) treat confirmed skills
  as supported, so bullets that use them are not rejected or stripped.
- "Don't know" terms remain unsupported, exactly as today.

Storage: in `master.json`, kept separate from the user's hand-written skill
groups so it is traceable which skills came from the check (a dedicated
"confirmed" group plus a "declined" list, or equivalent). The exact shape is
the builder's call, but it must validate against the strict models in
`models.py` and round-trip through privacy redaction.

CLI runs are unchanged: no prompt, but they do use previously confirmed skills.

Checkpoint reuse (designer's call, from builder check):

- The JD-parse result is reused as-is. Its checkpoint key must depend on the
  JD text (and options), not on the full master JSON, so saving confirmed
  skills into `master.json` does not invalidate it. Today `run_fingerprint`
  (`resume_tailor/checkpoints.py`, called at `pipeline.py:1275`) includes the
  full master; split the key per stage or exclude the confirmed/declined
  section from the fingerprint.
- Requirement map: reused when nothing was ticked. When one or more skills
  were ticked, re-run it once, so the model's coverage reasoning and proxy plan
  see the new skills. Do not patch the saved map in code.

Editing remembered answers (designer's call): a collapsible "Remembered
skills" row under the chips in the B panel lists confirmed and declined terms;
tapping one flips it. This needs a small endpoint that writes the
confirmed/declined section of `master.json`, and the web app must reload the
in-memory master (loaded once at `web/app.py:644`) after a write. Jobs already
queued keep the master they started with.

### 5. Flow correctness pass

Walk every AI call in `run()` and confirm each receives what it needs and
nothing duplicated:

- Confirmed skills reach JD-to-master mapping, selection, evidence planning,
  skills tailoring, and both rewrite stages.
- Selection and the evidence plan see the new ordering/budget rules.
- Holistic review currently receives the full master, the draft, the evidence
  plan, and the generated components (largest prompt, up to ~29k tokens).
  Remove duplicated material where the same facts are sent twice.
- Select work and select projects do not depend on each other: run them in
  parallel on the reasoning chain. Project rewrite batches may run in parallel
  if pacing allows.
- Retry-heavy stages (rewrite work/projects fail schema validation on weaker
  models: "Input should be a valid dictionary or instance of STARBullet") get
  the writing chain's stronger model first; schema size reduction is left to
  the builder if it is cheap and safe.

## Verification

Re-run the saved HCLTech (`e1787c60…`) and Fordham (`190680d4…`) job
descriptions plus one big-company SWE posting before and after:

- deterministic `keyword_coverage.computed_coverage_pct` rises for HCLTech;
  must-haves list concrete terms (Java, Spring Boot, AWS, SQL…);
- Fanatics present, listed first, with ≥ as many bullets as any other entry;
- skill-check chips appear for Fordham's Figma/Adobe XD/etc.; a ticked skill
  appears in Skills and passes truth checks when used in a bullet; an
  un-ticked skill is not asked again on the next run;
- number of AI calls per run does not increase; typical run time does not
  increase;
- existing test suite passes; checkpoint resume still works mid-run.

## Left to the builder

- Exact strength formula for the bullet budget.
- Exact storage shape for confirmed/declined skills in `master.json`.
- How the skill-check endpoint and the run share checkpoints (same job id or a
  pre-run id carried into the run).
- Whether to add the deterministic "such as" splitter or rely on the prompt.
- Holistic-review payload trimming details.
- UI styling, following the existing app (`static/app.css` tokens) and the
  B mockup in `.superpowers/brainstorm/`.
