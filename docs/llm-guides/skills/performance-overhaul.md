<!-- Source: vandan-llm-toolkit skills/performance-overhaul/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# Performance Overhaul

Turn a vague "make it fast" into measured, proven wins through five phases. This skill is
written so the **output does not depend on the model running it**: every phase has a
canonical threshold, copy-paste code, an output contract, and a gate. The user has no
performance taste and will not supply any — the taste is encoded here. Do not improvise it
and never answer "use your judgment"; follow the phases literally.

This is the **deep pipeline**. For a fast single-pass tune-up, use capability guide
`guides/capability-pack/10-performance-pass.md` instead. Reach for this skill when the ask
is a full audit, spans multiple pages, or must be proven against a budget. For the N+1 depth
invoked in Phase 4, defer to the `integration-glue` skill
(`references/data-and-events.md`) when it is available.

## Operating rules (read first, apply always)

1. **One phase at a time, in order.** Finish a phase's output contract before starting the
   next. Each phase file is self-contained — a smaller model can do exactly one per session.
2. **Never skip Phase 1 (MEASURE) or Phase 5 (PROVE).** A change without a before-number
   and an after-number did not happen.
3. **Copy values verbatim.** When a phase file gives a threshold, header, attribute, or
   snippet, use it exactly. Do not substitute "similar" values.
4. **Fix the biggest number first.** Order fixes by measured cost, not by what is easy.
5. **Preserve behavior.** All routes, features, data, and tests must still pass after every
   phase. Run the project's build and tests after each phase; fix breakage before moving on.
6. **Write the plan file.** Phase 1 produces `PERF_PLAN.md` in the repo root (or the docs
   dir). Every later phase reads it and checks off its items. This is how a fresh session —
   or a weaker model — resumes without losing state.

## The five phases

Read the phase file right before executing it. Do not read all three upfront.

| Phase | File | Produces |
|---|---|---|
| 1. MEASURE | [references/measure.md](references/measure.md) | `PERF_PLAN.md`: per-page baseline table (field + lab) |
| 2. QUICK WINS | [references/quick-wins.md](references/quick-wins.md) | Images, fonts, third-party scripts fixed |
| 3. BUNDLE DIET | [references/bundle-and-runtime.md](references/bundle-and-runtime.md) | Splits, dynamic imports, dependency decisions |
| 4. RUNTIME | [references/bundle-and-runtime.md](references/bundle-and-runtime.md) | N+1, caching headers, INP/long-task, CLS reservations |
| 5. PROVE | re-run [references/measure.md](references/measure.md) | Numbers-vs-baseline table, budget gate, sign-off |

Order note: quick wins (2) come before the bundle diet (3) because they are cheap, reversible,
and often move LCP/CLS enough to re-prioritize the rest. Runtime (4) comes last among fixes
because INP and N+1 work is the most invasive.

## Core Web Vitals — canonical thresholds (copy verbatim)

Assessed at the **75th percentile** of real visits, mobile and desktop segmented separately.
A page passes only if all three are "good" at p75.

| Metric | Good | Needs improvement | Poor |
|---|---|---|---|
| LCP (loading) | ≤ 2.5 s | 2.5 s – 4.0 s | > 4.0 s |
| INP (responsiveness) | ≤ 200 ms | > 200 ms and ≤ 500 ms | > 500 ms |
| CLS (visual stability) | ≤ 0.1 | 0.1 – 0.25 | > 0.25 |

Pass rule: ≥ 75% of visits must be "good" for each metric. INP is the stable Core Web Vital
(it replaced FID in March 2024). These three are the only Core Web Vitals.

## Performance budgets — starting defaults (tune, do not worship)

These are **team-set starting budgets**, not an external standard — set the real budget from
your own Phase 1 baseline, then only tighten. Per page, on mobile, compressed/transferred:

| Budget | Starting default |
|---|---|
| JavaScript (transferred) | ≤ 170 KB |
| Total image weight | ≤ 500 KB |
| Total requests | ≤ 50 |
| LCP hero image | ≤ 200 KB |

If a page's baseline already beats a default, ratchet the budget down to the baseline so the
project cannot regress into the slack.

## Hard bans (enforced in every phase)

- **No optimization without a baseline number first.** If `PERF_PLAN.md` has no recorded
  before-number for the thing you are touching, stop and measure it (Phase 1).
- **Never lazy-load the LCP / above-the-fold image.** `loading="lazy"` on the hero delays the
  very metric you are fixing. Give the LCP image `fetchpriority="high"` instead.
- **Never remove functionality to hit a budget silently.** Dropping a feature, route, or data
  to shrink a number is only allowed if it is written in `PERF_PLAN.md` and the user agreed.
- **Never claim a win from a lab score alone.** Lab (Lighthouse) is diagnostic; the pass/fail
  verdict is field data (CrUX) at p75. Report both.
- **Never ship on a regression you cannot explain.** Phase 5 fails if any metric got worse
  and the plan file does not state why it is acceptable.

## PROVE gate (Phase 5 output contract)

Re-run the exact Phase 1 measurement procedure and append to `PERF_PLAN.md` a table with one
row per page: metric, baseline, current, delta, budget, pass/fail. Ship only when **every
budgeted metric is within budget OR every remaining miss has a written, accepted reason**, no
tracked metric regressed unexplained, and the build and tests pass. Otherwise return to the
phase that owns the failing metric. State field and lab numbers separately; the verdict is field.

## For orchestrating models (Claude Code, capable agents)

You may run phases 2–4 with subagents (one phase each, sequential) — give each subagent the
phase file path plus `PERF_PLAN.md`. Verify the output contract yourself between phases. Never
parallelize phases; a later phase's baseline is the previous phase's output. Phases 1 and 5
share one procedure (measure) — run 5 against the exact 1 conditions or the deltas are noise.
