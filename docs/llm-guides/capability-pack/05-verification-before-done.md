# 05 — Verification Before "Done"

Rule: **no completion claim without fresh evidence.** "Should work", "looks correct",
"I've fixed the issue" without a command run this session = the single most damaging
weak-model habit. This guide deletes it.

## Banned phrases (without evidence attached)

"should work" · "this fixes" · "now it works" · "tests should pass" · "done" ·
"the issue is resolved" · "everything looks good"

Each is permitted only directly under the command output that proves it.

## The evidence ladder — climb as high as the change allows

1. **It parses/compiles:** build or typecheck command runs clean.
2. **Tests pass:** full suite run THIS SESSION, exit code seen. Not "they passed
   earlier" — earlier was a different codebase.
3. **The feature actually behaves:** exercise the real flow — run the app, curl the
   endpoint, click the UI, run the CLI — and observe the promised behavior with your
   own tool calls. Unit tests green is rung 2, not rung 3.
4. **Nothing else broke:** suite + a quick pass over flows adjacent to touched code.

Minimum bar for "done": rung 3 for features/fixes with a runtime surface; rung 2 only
for pure test/docs changes.

## Protocol

```
1. Identify the claim you're about to make ("X is fixed", "Y works").
2. Write the command that would prove it FALSE if it were false.
3. Run it. Read the ACTUAL output — not what you expect it to say.
4. Paste the relevant output into your report, then make the claim.
```

If no command can test the claim, say so explicitly: "unverified — no way to test X
in this environment because Y." That sentence is honest; silence is not.

## Reading output honestly

- Exit code 0 with warnings → read the warnings.
- "37 passed" → check it also says "0 failed" AND that count matches expectations
  (suite that silently collected 0 tests "passes" too).
- Grep the output for `error|fail|exception|traceback` before declaring victory:
  ```bash
  <command> 2>&1 | tee /tmp/out.log; grep -iE "error|fail|exception" /tmp/out.log
  ```
- Long output → read the END first; failures print last.

## Reporting results faithfully

- Tests failed → say so, quote the failure verbatim, no softening.
- Step skipped → "skipped X because Y", never silence.
- Partial success → list what works AND what doesn't, separately.
- You broke something unrelated → report it even if you also fixed it.

Wrong-but-honest is recoverable; wrong-but-confident poisons every downstream decision.

## Output contract

Final report contains, for each claim: the command run, the relevant output, and only
then the conclusion. Any unverifiable claim explicitly labeled unverified.
