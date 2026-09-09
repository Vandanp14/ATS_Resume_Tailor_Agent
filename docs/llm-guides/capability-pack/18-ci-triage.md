# 18 — CI / Red Pipeline Triage

Rule: **a red pipeline is a reproduction, not an obstacle.** Retry-until-green,
commenting out the test, and force-merging are the three banned "fixes" — each turns
a visible failure into an invisible one.

## Triage order

### 1. Read the actual failure

Open the failing job's log, read from the END (failures print last). Identify the
first REAL error — not the cascade after it. Quote it verbatim. Which step failed:
install? build? lint? test? deploy? Each has different suspects.

### 2. Classify: my change, the environment, or flake?

```bash
# Did it fail on the exact code you pushed?
git log --oneline origin/main..HEAD
# Is main also red? → not your change; broken base or environment.
```

- Main red too → fix/escalate main first; don't debug your branch against a broken base.
- Only your branch red → your change until proven otherwise.

### 3. Reproduce locally, same commit, same command

Copy the EXACT command from the CI config (`.github/workflows/*.yml` etc.), run it on
the same commit locally:

```bash
git stash && git checkout <ci-sha>
<exact CI command>
```

- Reproduces → normal debugging, guide 03. Done here.
- Doesn't reproduce → environment diff; go to 4.

### 4. Enumerate the CI-vs-local diff (guide 11's list, CI edition)

Usual culprits, in frequency order:
- Version skew: CI's runtime/deps vs yours (`node -v`, lockfile respected? CI uses
  `npm ci`?)
- Missing env var/secret in CI config
- Case-sensitive filesystem: `import ./Utils` works on macOS, dies on Linux
- Test-order dependence: CI runs full suite/parallel; you ran one file. Reproduce:
  run the full suite, or randomize order (`pytest -p randomly` / `--random-order`)
- Stale CI cache: bust it once (most CIs: bump the cache key)
- Timezone/locale: CI is UTC, your machine isn't (guide 17)
- Timing: slower CI machine exposes real races and short timeouts

### 5. Flaky test protocol

Same test passes and fails with no code change = flaky. It's a real bug in the test
(or a race in the code) with a random reproduction rate.

1. Confirm: re-run the job ONCE. Twice-red = not flaky, it's real.
2. Never leave it silently retried. Either fix now (usual causes: unawaited async,
   shared state between tests, time/order dependence, network reliance — guide 04
   determinism rules), or quarantine visibly: skip-with-ticket
   (`@pytest.mark.skip(reason="flaky, #123")`), tracked, not forgotten.
3. A suite people expect to be re-run is a suite nobody trusts — flake debt
   compounds; pay it early.

### 6. Fix forward or revert

Fix is clear and small → fix. Not clear and the branch blocks others → revert first
(`git revert`, guide 07), debug without the pipeline burning. Reverting is not
failure; it's restoring the base everyone builds on.

## Bans

- Re-running until green as the "fix" (allowed exactly once, as a flake DIAGNOSTIC)
- Deleting/commenting/`.skip`-ing a failing test to merge (without the quarantine
  protocol above)
- `--no-verify`, force-merge over red required checks
- "Fixing" by loosening the assertion until it passes (that's deleting the test with
  extra steps)

## Output contract

Report: the first real error quoted · classification (change/env/flake) with
evidence · local reproduction attempted with the exact CI command · the fix, or the
revert, or the quarantine ticket. Pipeline green at the end (guide 05: show it).
