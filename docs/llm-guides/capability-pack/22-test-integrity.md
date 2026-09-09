# 22 — Test Integrity

Rule: **never make the bar green by weakening it.** A failing test is a signal that
code is wrong — not that the test is in your way. Extends [04-tdd-testing.md](04-tdd-testing.md)
(how to write tests) and [05-verification-before-done.md](05-verification-before-done.md)
(prove it passes) with the one thing they don't spell out: the fix must earn the green.

## Hard-ban list — never, to make a test pass

- **Never loosen an assertion.** `toBe(5)` → `toBeTruthy()`, `assertEqual(x, 5)` →
  `assertTrue(x)`, exact match → regex/`contains` — all banned as a way to go green.
- **Never delete, `.skip()`, `xit`, comment out, or `@pytest.mark.skip` a failing test.**
- **Never edit the expected value to match the current output** unless you have proof
  the current output is correct (see evidence rule below).
- **Never wrap failing code in try/catch (or `pass`, `rescue nil`, empty `.catch()`)
  to swallow the error** so the test stops throwing.
- **Never widen a type, add a special-case, or mock away the real code path** to dodge
  the failure.

If your change makes a test pass without making the *behavior* correct, it is banned.

## The only allowed flow on a red test

1. **Read the failure verbatim.** Expected vs. actual, and the assertion line. Quote it.
2. **Decide who is wrong — the code or the test.** Default assumption: **the code.**
3. **If the code is wrong:** fix the cause per [03-systematic-debugging.md](03-systematic-debugging.md).
   Do not touch the test's assertions. Re-run; it goes green because behavior is now right.
4. **If the test is wrong:** it is only "wrong" when the *expected value itself* is
   incorrect (spec changed, typo in fixture, test asserts a bug). Changing it requires
   written justification + evidence (next section). Otherwise, go back to step 3.
5. **Re-run the single test, then the full suite.** Both green, no new reds.

## Changing an expectation — evidence required

You may edit an expected value ONLY with a comment recording all three:

```
// EXPECTATION CHANGED: was toBe(4), now toBe(5)
// WHY: spec PR #812 redefined tax rounding to round-half-up
// EVIDENCE: 4.5 → 5 per spec table row 3; hand-computed 3 cases, all match
```

No source-of-truth (spec, ticket, docs, a hand computation you show) = no change.
"The code outputs 5 now" is **not** evidence — that is matching the test to the bug.

## Assertion-strength rules

- Assert the **specific value**, not mere truthiness. `expect(total).toBe(42)`, never
  `toBeTruthy()`. A test that can't fail on a wrong-but-non-empty value tests nothing.
- Assert the **whole relevant shape** — full object/array, not just `.length`.
- Assert **error type + message**, not just "it threw".
- A green test after your change must still **fail if you revert the fix.** If it
  passes both ways, the test is worthless — strengthen it.

## Pre-commit self-audit — run on every touched test

```
[ ] No assertion was weakened (grep your diff for toBeTruthy, assertTrue, skip, xit).
[ ] No test deleted/skipped/commented to go green.
[ ] Every changed expected value has a WHY + EVIDENCE comment.
[ ] No try/catch or empty catch added around code-under-test to hide a throw.
[ ] Each touched test still FAILS when the fix is reverted (verify once).
[ ] Full suite green this session, exit code seen (per guide 05).
```

## Output contract

Report, per touched test: what failed, whether code or test was wrong, the fix (or the
WHY+EVIDENCE for a changed expectation), and the suite result. Any expectation change
without cited evidence is a defect — treat it as unfinished work, not done.
