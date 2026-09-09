# 02 — Feature Workflow

Building any feature: five phases, in order, with a state file. One phase per session
is fine — the state file carries you.

## Phase 0 — Spec (before any code)

Answer in writing, in `FEATURE_PLAN.md` at repo root:

```markdown
# Feature: <name>

## What
<2-4 sentences: what the user can do after this ships that they couldn't before>

## Out of scope
<explicit list — things you will NOT build. Empty list = scope not thought through>

## Acceptance checks
1. <concrete, runnable check: "POST /api/x with y returns 201 and creates row">
2. …

## Touched files (planned)
- path — why

## Phases
- [ ] 1 Plan reviewed against codebase
- [ ] 2 Tests written (failing)
- [ ] 3 Implementation (tests passing)
- [ ] 4 Integration verified end-to-end
- [ ] 5 Review + cleanup
```

Vague requirement? Pick the simplest reasonable interpretation, write it in the spec
explicitly, flag it in your report. Never build on an unstated interpretation.

## Phase 1 — Plan against reality

Run guide 01 (context protocol) for every planned file. Correct the plan: existing
helpers found, actual patterns to follow, real file locations. Update `FEATURE_PLAN.md`.

## Phase 2 — Failing tests first

Write tests for the acceptance checks. Run them. **They must fail** — a new test that
passes before implementation tests nothing. Record the failure output in the plan file.
Details: guide 04.

## Phase 3 — Implement to green

Smallest code that passes the tests. One acceptance check at a time; run the test suite
after each. Don't build ahead of the tests (YAGNI). Match conventions (guide 01).

## Phase 4 — End-to-end verification

Unit tests green ≠ feature works. Exercise the real flow: start the app, hit the
endpoint / click the flow / run the command. Record the actual output in the plan file.
Details: guide 05.

## Phase 5 — Review + cleanup

Self-review the diff with guide 06. Delete: debug prints, commented-out code, unused
imports, narration comments. Commit per guide 07.

## Rules

- Phases in order. No implementation before a written spec; no "done" before Phase 4
  evidence.
- Check off each phase in `FEATURE_PLAN.md` as it completes — that's the resume point
  after any context loss.
- Feature too big for one plan (multiple independent subsystems)? Split into separate
  `FEATURE_PLAN.md` cycles, build one at a time.
- Blocked mid-phase? Write the blocker into the plan file before stopping.
