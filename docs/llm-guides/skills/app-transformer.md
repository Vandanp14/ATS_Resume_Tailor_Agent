<!-- Source: vandan-llm-toolkit skills/app-transformer/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# App Transformer

Turn a mid-tier app into a top-tier one through six phases. This skill is written so
the **output quality does not depend on the model running it**: every phase has exact
values, copy-paste code, an output contract, and a verification gate. Follow it
literally. Do not improvise taste — the taste is already encoded here.

Taste source of truth: the `vandan-ui-system` skill. If it is available, its reference
files override any conflict. If it is not available, this skill is standalone — every
value you need is in the phase files.

Upstream source of truth: the `design-research-pipeline` skill. This skill is the **back
half** of a two-part pipeline — it starts once a written design brief exists. If a
`docs/design-brief.md` (and its `DESIGN_PLAN.md`) is present, Phase 1 reads the brief's
decided token architecture, phased P1/P2/P3 plan, do-not-regress list, and "What we are NOT
doing" list *instead of* inventing taste: map the brief's phases onto `TRANSFORM_PLAN.md`,
fold its NOT-doing list into the hard bans below, and never re-decide anything the brief
already settled. If no brief exists and the ask is "build me a premium X" from scratch, run
`design-research-pipeline` first to produce one; if that skill is unavailable, proceed
standalone from Phase 1.

## Operating rules (read first, apply always)

1. **One phase at a time, in order.** Finish a phase's output contract before starting
   the next. If you are a smaller model or context is tight, do exactly one phase per
   session — each phase file is self-contained.
2. **Never skip Phase 1 (audit) or Phase 6 (verify).**
3. **Copy values verbatim.** When a phase file gives a hex, radius, timing, or class
   string, use it exactly. Do not substitute "similar" values.
4. **Restructure, don't recolor.** If you only changed colors, the transformation
   failed. Layout, hierarchy, components, and states must change.
5. **Preserve behavior.** This is a visual/structural transformation. All existing
   functionality, routes, data flow, and tests must still work after every phase.
   Run the project's build/tests after each phase; fix breakage before moving on.
6. **Write the plan file.** Phase 1 produces `TRANSFORM_PLAN.md` in the repo root
   (or the project's docs dir). Every later phase reads it and checks off its items.
   This is how a weaker model — or a fresh session — resumes without losing state.

## The six phases

Read the phase file right before executing it. Do not read all six upfront.

| Phase | File | Produces |
|---|---|---|
| 1. Audit | [references/phase-1-audit.md](references/phase-1-audit.md) | `TRANSFORM_PLAN.md`: stack, product mode, slop inventory, file list |
| 2. Tokens & type | [references/phase-2-tokens.md](references/phase-2-tokens.md) | Design tokens, fonts, Tailwind/CSS theme wired in |
| 3. Structure | [references/phase-3-structure.md](references/phase-3-structure.md) | App shell, navigation, layout hierarchy rebuilt |
| 4. Components | [references/phase-4-components.md](references/phase-4-components.md) | Every generic component replaced with a system component |
| 5. Polish | [references/phase-5-polish.md](references/phase-5-polish.md) | States, motion, accessibility, copy pass |
| 6. Verify | [references/phase-6-verify.md](references/phase-6-verify.md) | Scored rubric ≥ threshold, screenshots, sign-off |

Order note: tokens (2) come before structure (3) so every structural edit already uses
final values — this prevents the double-rewrite that weaker models fall into.

## Product mode (set once in Phase 1)

| Mode | Products | Density / radius |
|---|---|---|
| Native Matte | finance, fitness, habit, personal dashboards, mobile-first | compact rows, cards 24–32px |
| Precision Tool | dev/AI/productivity tools, admin, extensions | tight grids, cards 12–16px |
| Editorial Premium | portfolios, personal/brand pages | spacious, typographic |
| Dense Enterprise | CRMs, ops/internal data tools | table-first, compact |
| Product Marketing | landing/launch pages | compact hero, real UI early |

## Hard bans (enforced in every phase)

Purple/blue gradient backgrounds · gradient text · glassmorphism as design language ·
neon/cyber glow · fake 3D blobs · stock illustrations · emoji decoration · sparkle/
brain/robot logos · icons beside every heading · repeated 3-column feature-card grids ·
default Inter look · unstyled shadcn/Tailwind defaults (`rounded-lg border bg-card p-6
shadow-sm`) · buzzword copy ("unlock", "supercharge", "seamlessly", "AI-powered
platform") · desktop tables squeezed onto mobile · giant spinners · placeholder-only
labels on important fields.

If you find one, remove it. When in doubt, delete decoration.

## For orchestrating models (Claude Code, capable agents)

You may run phases 2–5 with subagents (one phase each, sequential) — give each subagent
the phase file path plus `TRANSFORM_PLAN.md`. Verify the output contract yourself
between phases. Never parallelize phases; they are order-dependent.

## For a project that wants this permanently

Copy [templates/CLAUDE-md-ui-standards.md](templates/CLAUDE-md-ui-standards.md) into
the project's `CLAUDE.md` (or AGENTS.md) so every future session — any model, any
harness — holds the standard without this skill loaded.
