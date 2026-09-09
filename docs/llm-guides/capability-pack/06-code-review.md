# 06 — Code Review

For reviewing a PR, a diff, or your own work before handing it over. Findings must be
verified, ranked, and actionable — a review that lists 30 nitpicks and misses the data
loss bug is worse than no review.

## Phase 1 — Understand before judging

1. Read the stated intent (PR description, task, commit messages).
2. Read the full diff once WITHOUT commenting — build the picture.
3. For any non-obvious hunk, open the surrounding file; diffs lie by omission.

## Phase 2 — Hunt, in severity order

Spend effort top-down; stop writing style notes if you haven't finished the top tiers.

**Tier 1 — Correctness (must find):**
- Logic inverted/off-by-one; wrong operator (`<` vs `<=`, `and` vs `or`)
- Null/None/undefined paths; empty-collection paths
- Error swallowing: `except: pass`, `.catch(() => {})`, ignored return codes,
  fallback values that hide failure (silent-failure hunt — every catch block answers
  "what does the user see when this fires?")
- Race conditions, unawaited async, resource leaks (unclosed files/connections)
- Behavior change to existing callers (grep the callers — don't trust the diff)

**Tier 2 — Security:** injection (SQL/shell/path), secrets in code, missing authz
check on new endpoints, unvalidated external input. (Full pass: guide 09.)

**Tier 3 — Tests:** do tests cover the new behavior and its edges (guide 04)?
Would they fail if the implementation were wrong? Any test deleted/weakened to pass?

**Tier 4 — Design:** duplication of existing helpers, wrong layer, needless
complexity, API awkward for the next caller.

**Tier 5 — Style:** only where it changes meaning or violates written project rules.
Formatter-territory nits: skip entirely.

## Phase 3 — Verify each finding

Before reporting, attack your own finding: re-read the code — is the "bug" actually
handled upstream? Can you name concrete inputs that trigger it? Findings you can't
back with a failure scenario get labeled "possible — unconfirmed" or dropped.

## Report format

One line per finding, ranked most-severe first:

```
path/file.py:42 — [critical] expiry check uses < not <=; token valid 1s past expiry.
  Trigger: token with exp == now. Fix: use <=.
path/api.ts:88 — [moderate] catch block returns [] on DB error; outage looks like
  empty history to user. Fix: rethrow or surface error state.
```

Severity: critical (data loss/security/crash) · major (wrong behavior, real inputs) ·
moderate (edge-case wrong / silent failure) · minor (design/clarity). No praise
padding, no "consider maybe possibly" hedging — state the defect and the fix.

## Receiving review (the mirror rules)

Feedback on your code: verify each point against the code before acting — reviewers
are sometimes wrong. Implement what's right, push back with evidence on what isn't.
Never blind-apply, never performatively agree ("Great catch!" then no fix).
