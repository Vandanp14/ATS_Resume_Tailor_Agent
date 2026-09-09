# Capability Pack — index

Guides that give any LLM — including small/local/older models — the working discipline
of a frontier coding agent. Paste a guide into context (or reference it from CLAUDE.md /
AGENTS.md / a system prompt) and follow it literally.

## Why this works: the uplift pattern

Strong models differ from weak ones less in knowledge than in **discipline**: they
verify before claiming, read before writing, change one thing at a time, and recover
from being wrong. Discipline can be written down. Every guide here encodes it the same
seven ways:

1. **Deterministic phases** — numbered steps in fixed order; no step requires taste.
2. **Output contracts** — each phase ends with a named artifact ("this file exists",
   "this command prints X"). Either the contract is met or the phase isn't done.
3. **Verification gates** — evidence (command output, test run, screenshot) required
   before any "done/fixed/passing" claim. Claims without evidence are bugs.
4. **Resumable state files** — progress written to a `*_PLAN.md` in the repo, so a new
   session (or a different model) resumes without lost state.
5. **Copy-paste values** — exact commands, exact thresholds, exact templates.
   Improvisation is where weak models fail; remove the need for it.
6. **Hard-ban lists** — "never do X" is cheap to follow; nuanced judgment is not.
7. **One thing at a time** — one phase per session, one hypothesis per experiment,
   one logical change per commit. Small scope is the great equalizer.

## The guides

| # | Guide | Use when |
|---|---|---|
| 01 | [context-protocol.md](01-context-protocol.md) | Before ANY edit in an existing codebase |
| 02 | [feature-workflow.md](02-feature-workflow.md) | Building any feature, start to finish |
| 03 | [systematic-debugging.md](03-systematic-debugging.md) | Any bug, test failure, or unexpected behavior |
| 04 | [tdd-testing.md](04-tdd-testing.md) | Writing implementation code or tests |
| 05 | [verification-before-done.md](05-verification-before-done.md) | Before saying done/fixed/passing — always |
| 06 | [code-review.md](06-code-review.md) | Reviewing a diff, PR, or your own work |
| 07 | [git-safety.md](07-git-safety.md) | Commits, branches, anything destructive |
| 08 | [refactoring-safety.md](08-refactoring-safety.md) | Restructuring code without changing behavior |
| 09 | [security-pass.md](09-security-pass.md) | Before shipping anything network-facing |
| 10 | [performance-pass.md](10-performance-pass.md) | "It's slow" or pre-launch perf check |
| 11 | [environment-setup.md](11-environment-setup.md) | "Works on my machine", setup/venv/version hell |
| 12 | [api-design.md](12-api-design.md) | Adding or changing any endpoint |
| 13 | [database-migrations.md](13-database-migrations.md) | Any schema change or data backfill |
| 14 | [dependency-management.md](14-dependency-management.md) | Adding, upgrading, or auditing dependencies |
| 15 | [error-handling-logging.md](15-error-handling-logging.md) | Writing any catch block or logging strategy |
| 16 | [codebase-onboarding.md](16-codebase-onboarding.md) | First session in an unfamiliar repo |
| 17 | [data-correctness.md](17-data-correctness.md) | Code touching money, time, text, floats, or nulls |
| 18 | [ci-triage.md](18-ci-triage.md) | Red pipeline, flaky tests, "passes locally fails in CI" |
| 19 | [19-symbol-verification.md](19-symbol-verification.md) | Before writing any call/import/prop/token you haven't located |
| 20 | [20-surgical-diffs.md](20-surgical-diffs.md) | Any edit to an existing file |
| 21 | [21-blast-radius.md](21-blast-radius.md) | Changing any shared/exported symbol, schema, or contract |
| 22 | [22-test-integrity.md](22-test-integrity.md) | Any failing test you're tempted to make green |
| 23 | [23-calibration-and-evidence.md](23-calibration-and-evidence.md) | Making claims, or any state-changing/destructive command |
| 24 | [24-rationalization-red-flags.md](24-rationalization-red-flags.md) | You catch yourself saying "should work" / "probably fine" |
| 25 | [25-reread-the-ask.md](25-reread-the-ask.md) | Before declaring any task done |
| 26 | [26-research-protocol.md](26-research-protocol.md) | Any web/doc research task or research deliverable |

Related, same pattern, separate location: `app-transformer` skill (six-phase UI/product
transformation) and `vandan-ui-system` (UI taste system).

## How to deploy on a weak model

- **Minimum:** paste guide 01 + 05 into the system prompt. Those two alone remove the
  majority of weak-model failure modes (editing blind, claiming without checking).
- **Per task:** add the one guide matching the task. Don't paste all ten — context is
  the weak model's scarcest resource; one guide followed beats ten skimmed.
- **Per project:** copy this directory into the repo (`docs/llm-guides/capability-pack/`)
  and reference it from CLAUDE.md / AGENTS.md so every tool and model finds it.
- **Session hygiene for small models:** one phase per session; end every session by
  updating the state file; start every session by reading it.

## Backlog — future guides, same pattern

Not yet written; worth adding when needed: incident-response (prod triage order,
logs-first) · release-checklist (pre-deploy gate) · accessibility audit ·
data-pipeline verification · async/concurrency correctness (races, unawaited
promises, locks) · frontend state & data-fetch discipline · documentation/ADR
writing. Authoring conventions for new guides/skills live in `/CONTRIBUTING.md`;
the scored, fuller backlog lives in `/ROADMAP.md`.
