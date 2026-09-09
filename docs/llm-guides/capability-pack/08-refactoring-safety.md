# 08 — Refactoring Safety

Refactor = change structure, preserve behavior. The two failure modes: sneaking
behavior changes into "refactors", and breaking callers you never looked at.

## Preconditions — all three, or don't start

1. **Green baseline.** Full test suite passes NOW. Record the count:
   ```bash
   pytest -q 2>&1 | tail -3   # or the project's equivalent
   ```
   No tests covering the code you'll restructure → write characterization tests FIRST
   (tests that pin current behavior, even odd behavior — you're preserving, not fixing).
2. **Clean working tree.** Commit or stash everything else; the refactor diff must
   stand alone.
3. **Caller map.** Grep every usage of what you're moving/renaming/re-signaturing:
   ```bash
   grep -rn "oldName" --include="*.py" . | grep -v test | head -30
   ```
   Include: string references (routes, config keys, reflection), docs, tests.

## The loop — small steps, always green

Per step: one mechanical transformation → run tests → commit. Never batch.

Safe transformation sizes:
- Rename one symbol (all references in one commit)
- Extract one function/component
- Move one file (+ fix imports)
- Inline one needless indirection
- Replace one duplicated block with the shared helper

Ban list during refactor:
- "While I'm here" fixes — behavior bugs found mid-refactor go in a note, fixed in a
  separate commit AFTER, with their own test.
- Changing test assertions to make the refactor pass. Assertion needs changing =
  behavior changed = not a refactor. Stop and reassess.
- Rewriting a module from scratch and calling it a refactor. Rewrites need specs
  (guide 02), not this guide.

## Behavior-preservation checks

After each step and at the end:
- Full suite green, SAME test count as baseline (fewer collected tests = you broke
  discovery, not fixed code).
- Public API unchanged unless the rename WAS the task — then every caller updated in
  the same commit, verified by grep returning zero hits for the old name:
  ```bash
  grep -rn "oldName" . --include="*.py" --include="*.ts" | wc -l   # must be 0
  ```
- No new dependencies, no changed defaults, no reordered side effects.

## When it goes wrong

Tests red and the cause isn't obvious within a few minutes →
`git checkout .` back to the last green commit and take a smaller step. Reverting a
2-minute step is cheap; debugging a 40-minute tangle is not. That's why steps commit
individually.

## Output contract

Baseline test output recorded · every commit green · test count unchanged ·
grep-zero on removed names · behavior-change notes (if any) reported separately,
not smuggled in.
