<!-- Source: vandan-llm-toolkit skills/design-research-pipeline/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# Design Research Pipeline

The front half of a two-part pipeline. This skill turns "build me a premium X" into
decision-grade artifacts — genre recon, brand audit, design brief, and (after the build)
craft audit plus specialist review. The back half is the `app-transformer` skill, which starts
only once a written brief exists. Research and briefing happen here; building happens there.

The skill is written so the **output does not depend on the model running it**: every phase has
an output contract, a copy-paste template, and a mandatory ranked ending, so a weaker model that
fills the templates literally produces the same shape of artifact as a frontier one. The iron
rule: **no building before the brief is written.** Turn the vague ask into evidence, then a
decision, then a plan — in that order. Taste is discovered by research and frozen in the brief.


## Operating rules (read first, apply always)

1. **One phase at a time, in order.** Finish a phase's output contract before the next. Phase 1 writes `DESIGN_PLAN.md` at the repo root; every later phase checks its box, so any model resumes without losing state.
2. **Research ends in ranked transferable patterns — never a notes dump.** Every recon/audit artifact closes with a "Top N ... ranked by impact" list and a Sources block. Per-competitor prose that never resolves into a ranked, transferable list has failed, however thorough.
3. **Copy values verbatim, cite every source.** Extract exact hexes, tokens, durations, and quotes from live sites and compiled CSS — never "similar" or remembered values. Flag any unverifiable claim as *(unverified)*.
4. **The brief is the seam.** Phase 3 decides the direction and carries a phased plan, a do-not-regress list, and a "What we are NOT doing" list. It is the only artifact `app-transformer` needs. A thin brief yields a thin build.
5. **Do-not-regress discipline.** Every audit names what is already best-in-class; the brief carries that list forward; every later change preserves it. Naming strengths is scope protection, not politeness.
6. **Craft audit and specialist review are separate, later gates.** They run *after* a build, against the shipped result — never blended into pre-build research.


## The six phases

Read the template right before executing its phase. Do not read all templates upfront.

| Phase | Template (read right before its phase) | Produces (output contract) |
|---|---|---|
| 1. Genre recon | [templates/genre-recon.md](templates/genre-recon.md) — studying competitors | Per-competitor teardown at heading granularity → **Top N transferable patterns ranked by impact** → Sources |
| 2. Brand audit | [templates/brand-audit.md](templates/brand-audit.md) — extracting the current/adjacent brand | Current-system extraction (palette/type/logo/components/tone) · assets NOT to imitate · ranked candidate palettes · differentiation map · assessment |
| 3. Design brief | [templates/design-brief.md](templates/design-brief.md) — deciding the direction | Intent · token architecture · guardrails + contrast rules · do-not-regress list · phased P1/P2/P3 plan with S/M/L sizing · copy voice · **What we are NOT doing** · sequencing |
| 4. Build hand-off | (no template — the brief is the artifact) | Hand the brief to `app-transformer`; it writes `TRANSFORM_PLAN.md` and builds against the brief's P1/P2/P3 |
| 5. Craft audit | [templates/craft-audit.md](templates/craft-audit.md) — after a build, against shipped UI | **Top 15 issues ranked by severity** (S1/S2/S3) · "already good — do not regress" · screenshots + computed-contrast artifacts |
| 6. Specialist review | [templates/specialist-review.md](templates/specialist-review.md) — the final multi-lens gate | Executive summary · ship-blockers · technical + business findings by severity · strengths to preserve · prioritized top-10 actions · competitive scorecard |

The build's compressed inner loop — genre → tokens → frames → motion → checklist — belongs
to `app-transformer`; this skill decides *which* genre, *which* tokens, and *what not to do*
before that loop starts.


## Hard bans

- **No building, tokens, or component code before the Phase-3 brief exists.** Research first.
- **No notes-dump research** — an artifact with no ranked, transferable ending fails.
- **No invented or remembered values** — every hex/token/quote traces to a cited source or is flagged unverified.
- **No brief without a "What we are NOT doing" list and a do-not-regress list** — both are mandatory scope guards.
- **No skipping the brand audit's "assets NOT to imitate" section** — differentiation needs an explicit avoid-list.
- **No blending pre-build research with post-build audits.**
- **No decided palette in the brief without the ranked candidate options that produced it** — show the decision, not just the verdict.


## Canonical state file

Phase 1 writes this at the repo root, verbatim shape. Every phase checks its box on completion.

```markdown
# DESIGN_PLAN.md — <project>
Baseline: <commit / date> · Genre: <chosen genre> · Stack: <framework + CSS>

- [ ] Phase 1 — Genre recon        → docs/research/<genre>-recon.md
- [ ] Phase 2 — Brand audit         → docs/research/<current-brand>-audit.md
- [ ] Phase 3 — Design brief         → docs/design-brief.md
- [ ] Phase 4 — Build hand-off       → app-transformer reads the brief, writes TRANSFORM_PLAN.md
- [ ] Phase 5 — Craft audit           → docs/craft-audit.md
- [ ] Phase 6 — Specialist review     → docs/specialist-review.md
```

`DESIGN_PLAN.md` is upstream of `TRANSFORM_PLAN.md` (research/briefing vs. build) — both are
checkbox state files a weaker model uses to resume.


## Hand-off contract to app-transformer

Phase 4 is a clean seam. The brief hands `app-transformer` a decided direction so its
Phase-1 audit reads taste instead of inventing it:

- **Decided token architecture** — primitive ramp, semantic roles, the accent (single or per-item rotating system), radii, motion tokens — so its Phase 2 wires final values with no re-decision.
- **Phased plan (P1/P2/P3) with S/M/L sizing** — maps directly onto `TRANSFORM_PLAN.md` phases; the build never re-scopes.
- **Do-not-regress list** → the build's preserve-list, checked after every phase.
- **"What we are NOT doing" list** → the build's hard bans, on top of app-transformer's own.

If `app-transformer` is available it owns the build; this skill stops at the brief and
resumes at Phase 5. If not, hand the brief to whatever build agent runs next — same contract.


## Skill composition

If `vandan-ui-system` is available, its references own the canonical token/component values the
brief points at — cite them rather than re-deriving. If `app-transformer` is available, it owns
Phase 4's build. If neither is present, this skill is standalone: the templates carry every slot,
and the brief is self-contained for any downstream agent. Motion values, cubic-beziers, durations,
and gradient recipes are brand-neutral and portable; only palette identity is decided per project.


## Final audit — run before claiming the pipeline is done

1. Does `DESIGN_PLAN.md` exist with every completed phase checked?
2. Does every recon/audit artifact end in a ranked or severity-ordered list plus Sources, with all extracted values exact, cited, and unverified claims flagged?
3. Does the brief carry a decided token architecture, a phased plan with sizing, a do-not-regress list, and a "What we are NOT doing" list — and did the brand audit include an "assets NOT to imitate" list plus a differentiation map?
4. Was the build handed off only *after* the brief existed (no earlier code)?
5. Do the craft audit and specialist review judge the shipped result, each ending in their ranked structure?
6. Could a different model, reading only these artifacts, rebuild the same product? If not, the artifacts are underspecified — revise before claiming done.
