# Voice De-Robotization Plan — prompt changes mapped to QA findings

Source: `resume-qa-findings-report.md`. Every row below names the file to edit,
the exact instruction currently causing the pattern, and the replacement rule.

## Where the robotic voice actually comes from

Three instructions do most of the damage, and they are all doing exactly what
they were told to do:

1. `prompts/templates/_bullet_guide_rules.jinja` → "Bullet Templates" lists 7
   templates that are all the same `[Verb] [object] [prepositional clause]`
   shape. The model picks one per bullet and every bullet lands on the same
   rhythm. Cause of finding #1.
2. `prompts/templates/plan_evidence.jinja` → "It must contain an exact-looking
   number, not a range and not words such as approximately/about/roughly."
   This *manufactures* the false-precision, no-baseline stats. Cause of #2.
3. `prompts/templates/_bullet_rules.jinja` → "Open every bullet with a strong
   past-tense action verb… Never begin a bullet with an article or a noun
   phrase." Forces verb-first on 100% of bullets, which is the single biggest
   contributor to the uniform cadence. Reinforces #1.

Everything else is an additive rule on top of these.

---

## High priority

### F1 — Identical bullet template across a role
**Files:** `_bullet_guide_rules.jinja`, `_bullet_rules.jinja`, `_holistic_rules.jinja`, `pipeline_core.py`

- `_bullet_guide_rules.jinja`: replace the "Bullet Templates" block. Keep at
  most 3 templates, add 3 structurally different ones (leading constraint
  clause, leading problem statement, two-clause contrast), and add the hard
  rule: **no two consecutive bullets in one role may use the same structure,
  and no structure may be used more than twice in the whole resume.**
- `_bullet_rules.jinja`: soften the verb-first mandate to *"Most bullets open
  with a past-tense action verb. At least one bullet per role must open
  differently — with the constraint, the problem, or the system being worked
  on. Never open with 'I', 'We', 'My', or 'Our'."*
- Add to `_work_rules.jinja`: **at least one bullet per role must be built
  around a decision, tradeoff, or obstacle and carry no metric at all.**
- `_holistic_rules.jinja` + `holistic_review.jinja` style list: add "three or
  more bullets in one section sharing the same clause structure" as a
  recommendation-level finding (alongside the existing same-opening-verb check).
- `pipeline_core.py::scan_bullet_style`: add a shape fingerprint per bullet
  (opening POS + presence/position of a trailing participial clause such as
  `, enabling …` / `, establishing …` / `, reducing …`) and warn when ≥3
  bullets in a section share it. The trailing `-ing` result-clause is the
  single most visible tell in the reviewed PDF; count it explicitly.

### F2 — False precision, no baseline, self-congratulatory absolutes
**Files:** `plan_evidence.jinja`, `_truth_floor.jinja`, `_bullet_rules.jinja`, `pipeline_core.py`

- `plan_evidence.jinja` — rewrite the inferred-metric rule. New wording:
  *"An inferred metric must state or imply its baseline: `X of Y`, `from A to
  B`, `against a Z threshold`, or `N out of M`. A bare percentage or a bare
  count with no denominator is not acceptable. Do not produce more than one
  decimal place unless the source fact itself carries that precision — prefer
  a round number the candidate can defend arithmetically."*
- `plan_evidence.jinja` schema: add a required `baseline` field to
  `inferred_impact` so the plan cannot skip it, and validate it non-empty.
- `_truth_floor.jinja`: extend the point-estimate clause with the same
  baseline requirement so it is not contradicted by the truth floor.
- New banned-qualifier list (add to `_bullet_guide_rules.jinja` "Do not" and
  as a lint list in `pipeline_core.py`): `zero`, `no tuning required`,
  `no issues`, `always`, `never fails`, `flawless`, `seamless`, `effortless`,
  `100% uptime`, `perfect`, `fully automated end-to-end`.
- `pipeline_core.py`: add `scan_metric_quality()` — warn on a percentage or
  count with no baseline token in the same bullet, on >1 decimal place, and on
  any banned qualifier.

### F3 — Jargon stacking with no concrete referent
**Files:** `_bullet_guide_rules.jinja`, `_resume_core_rules.jinja`

- Add to "Do not": *"Do not use a multi-word technical noun phrase that is not
  a standard, googleable industry term (e.g. 'SQL dual-identifier engine',
  'agentic AI integration across internal manufacturing systems'). Name the
  literal artifact — the endpoint, the table, the script, the query, the
  service — before or instead of the abstract label."*
- Add to "Final Bullet Test": *"A reader outside the candidate's team can
  picture the literal thing that was built or changed."*
- Paste the report's worked example pairs (before → target shape) into
  `_bullet_guide_rules.jinja` under a new `### Calibration examples` heading.
  These are the highest-leverage single change: the model matches shown prose
  far more reliably than it obeys abstract prohibitions.

### F4 — Verb intensity mismatched to scope
**Files:** `_action_verbs.jinja`, `pipeline_core.py`

- `_action_verbs.jinja` "Verb Restrictions": convert to a scope ladder, adding
  an explicit size gate per tier:
  - *Architected / Spearheaded / Orchestrated / Pioneered* — a system-level
    design decision the candidate made that shaped how other components work.
    Not usable for a handful of endpoints, one script, or one feature.
  - *Designed / Led / Owned* — a component boundary or a workstream.
  - *Built / Added / Wrote / Implemented / Extended* — default. Use unless the
    tier above is clearly earned.
- Add: *"When two verbs would both be truthful, pick the narrower one."*
- `pipeline_core.py`: extend `RESTRICTED_VERBS` scanning past the first word —
  currently only the bullet's opening token is checked, so
  "Architected **and deployed** …" and mid-sentence uses escape entirely.

---

## Medium priority

### F5 — Multiple precise counts per bullet
**Files:** `_project_rules.jinja`, `_bullet_rules.jinja`, `pipeline_core.py`

- Add: *"At most one quantified claim per bullet. When a count does not by
  itself demonstrate difficulty, coverage, or reliability (route counts, table
  counts, file counts, line counts), drop it and state what the system does."*
- `pipeline_core.py`: warn when a bullet contains ≥2 numeric tokens that are
  not part of a single baseline pair (`X of Y`, `from A to B`).

### F6 — Skills section misses technologies used in the experience text
**Files:** `_skills_rules.jinja`, `tailor_skills.jinja`, `pipeline_core.py`

This one is a **code change, not only a prompt change.**
`pipeline_core.py::validate_skills` builds `allowed` from
`master.skills[*].keywords` plus JD keywords only — so a technology named only
inside a work highlight is *rejected* if the model surfaces it. The prompt is
obeying a contract that makes the finding unfixable by wording alone.

- `pipeline_core.py`: add a `technologies_in_experience(master)` extractor
  (project `technologies` arrays + capitalized/known-tech tokens in work and
  project highlight text) and union it into `allowed`.
- `tailor_skills.jinja`: pass that set in as a new
  `<<<TECHNOLOGIES_NAMED_IN_EXPERIENCE>>>` block and instruct: *"Every
  technology named anywhere in the experience or project text must appear in
  the skills section verbatim. A tool that exists only inside a bullet clause
  is invisible to keyword matching."*
- `_skills_rules.jinja`: add *"Rank concrete named technologies above generic
  process categories. Include process/method categories (OOP, SDLC, code
  reviews, version control, Agile) only after every named technology is placed,
  and never as a leading group."*

### F7 — Real sourced metric for a role goes unused while a metric is invented elsewhere
**File:** `plan_evidence.jinja`

- Add rule: *"When a destination's allocated facts contain a verified number,
  at least one of that destination's bullets must carry it. Do not create an
  inferred metric for any destination while a verified metric available to that
  same destination is unused."*
- Strengthen the existing weak "Prefer verified metrics already present in
  source facts" into that hard constraint, and validate it in
  `pipeline_core.py` at plan-validation time (warn, not block).

---

## Low priority

### F8 — Overlapping date ranges with no qualifier
**Files:** `render.py` / `pipeline_core.py` (not a prompt change)

Dates are protected fields restored by code, so the model cannot fix this.
Add a post-assembly step: when two work entries' ranges overlap, append a short
qualifier to the shorter/lower-relevance entry's date string (e.g.
`part-time, concurrent`). Derive the qualifier from the master when it states
employment type; otherwise use the neutral `concurrent`.

---

## Suggested edit order

1. F2 + F4 + F3 wording (prompt-only, highest visible payoff).
2. Calibration examples block (F3) — biggest behavioral lever per line of prompt.
3. F1 template rewrite + verb-first softening.
4. F6 code change (`allowed` set) then its prompt half.
5. F5, F7.
6. F8 render-side qualifier.
7. `pipeline_core.py` lint additions last, so they measure the new prompts
   rather than the old ones.

## Verification

Re-run the pipeline against the same JD that produced `CTG_Vandan_Patel_Resume.pdf`
and diff against the report's eight patterns. The lint additions
(`scan_bullet_style`, `scan_metric_quality`) give a countable pass/fail signal
per pattern; findings #1, #2, #4, #5 all become machine-checkable.

---

## Status — all eight findings shipped

| # | Finding | Landed in | Commit |
|---|---------|-----------|--------|
| 1 | Identical bullet template | `_bullet_guide_rules` (5 distinct structures + hard rules), `_bullet_rules` (verb-first softened), `_work_rules` (one metric-free decision bullet per role) | `ab59a64` |
| 2 | False precision, no baseline | `ImpactInference.baseline` required; `_validate_inference` rejects unbaselined, decimal-precise, and absolute-qualifier claims; `plan_evidence` + `_truth_floor` rewritten | `945c88c` |
| 3 | Jargon with no referent | `_bullet_guide_rules` prohibition + Final Bullet Test + three worked before/after calibration examples | `ab59a64` |
| 4 | Verb intensity vs scope | `_action_verbs` Verb Restrictions rebuilt as a three-tier scope ladder | `ab59a64` |
| 5 | Count stacking | `_bullet_rules`, `_project_rules`, `_bullet_guide_rules` one-claim cap | `ab59a64` |
| 6 | Skills missing bullet-only technologies | `technologies_in_experience()` widens `validate_skills`' allowed set; `tailor_skills` gets the mined list; `_skills_rules` demotes process categories | `0888f36` |
| 7 | Verified metric unused | `plan_evidence` hard-orders verified metrics ahead of inferred ones per destination | `945c88c` |
| 8 | Overlapping dates | `render._concurrent_role_indices` appends "(concurrent)" to the shorter overlapping role | `532c651` |

Machine-checkable coverage added in `64cd68a`: `scan_bullet_style` now catches
restricted verbs anywhere in the sentence (not just the opening token, which is
how the report's own "architected and deployed" example slipped through) and
repeated trailing participial result clauses; `scan_metric_quality` covers
findings #2 and #5. Both are warn-only and report through the existing tracker.

Findings #1, #3, and the "every bullet ends in a statistic" half of #7 remain
partly judgment calls — those are enforced by prompt and audited by the
holistic reviewer, which gained matching checks.

**Not yet verified against a real run.** The test suite (162 tests) covers the
contracts and the linters; the next step is regenerating a resume from the same
JD that produced `CTG_Vandan_Patel_Resume.pdf` and reading the output against
the report's eight rows.
