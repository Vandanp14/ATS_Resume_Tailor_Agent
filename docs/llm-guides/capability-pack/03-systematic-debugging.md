# 03 — Systematic Debugging

Rule: **no fix before a reproduced failure and a confirmed cause.** Shotgun fixes
("maybe it's this") are how weak models burn sessions and break working code.

## The loop

### 1. Reproduce

Get the failure happening on demand — a command you can run repeatedly:

```bash
# examples
pytest tests/test_x.py::test_case -x   # failing test
curl -s localhost:8000/api/x | head    # failing endpoint
```

Can't reproduce → that IS the task now. Add logging, capture inputs, find the trigger.
Never "fix" what you can't reproduce; you can't verify the fix either.

Quote the exact error, verbatim. Read the WHOLE message including the last lines of
the stack trace — the answer is often literally printed.

### 2. Locate

Walk the stack trace to the deepest frame in YOUR code. Read that function fully.
Read what it calls. Find where reality diverges from expectation — add a print/log at
the suspect line and re-run the reproduction to see actual values:

```python
print(f"DEBUG: x={x!r} type={type(x)}", flush=True)
```

### 3. Hypothesize — ONE at a time

Write it down (scratch file or `DEBUG_LOG.md` if the hunt spans sessions):

```markdown
Hypothesis 1: <cause> — because <evidence>
Test: <what will prove/disprove it>
Result: <actual output>  → confirmed / refuted
```

Design the cheapest experiment that can REFUTE the hypothesis. Run it. Refuted →
next hypothesis, new entry. Never test two changes at once — a pass tells you nothing
about which one mattered.

### 4. Fix the cause, not the symptom

Symptom-fix smells (banned):
- wrapping the error in try/except-pass or a null check with no understanding of WHY
  the value is null
- retrying until it works
- widening a type / loosening a validation to make the error go away
- special-casing the failing input

If you can't explain in one sentence why the code was wrong, you haven't found the
cause. Keep looping.

### 5. Verify + protect

1. Run the reproduction from step 1 — must now pass.
2. Run the full test suite — must not have broken anything else.
3. Add a regression test that encodes the reproduction (fails without the fix).
4. Remove every debug print you added.

## Escalation rule

Three consecutive refuted hypotheses → stop guessing locally. Widen: re-read the error
from scratch, `git log -p --follow <file>` for recent changes to the area, check
versions/environment, question your assumption about what the code is SUPPOSED to do.
The bug is usually in an assumption, not in the line you're staring at.

## Output contract

Fix is done only when: reproduction passes · full suite passes · regression test added
· cause explainable in one sentence · debug artifacts removed.
