# 25 — Reread the Ask (Close the Loop)

Rule: **no completion claim until every clause of the original request maps to evidence.**
Guide 05 asks "does the code run correctly?"; this guide asks the other question weak
models fail — "did I answer THE question, all of it, and nothing but it?" Passing tests
on the wrong task is still a failure.

## The failures this deletes

- Solves 2 of 3 requested changes, declares the whole task done.
- Silently drops a constraint from the prompt ("without adding a dependency").
- Answers a subtly different, easier question because it anchored on its own restatement.
- Adds unrequested scope while missing the actual requested change.

## The procedure — run before any "done"

```
1. QUOTE the original request verbatim. Copy the user's exact words back into your
   report. Do NOT paraphrase — paraphrase is where the drift already happened.
2. DECOMPOSE into a numbered requirement list. One line per atomic ask. Split
   compound sentences ("do X and Y" = two items). Add every negative constraint and
   "do NOT" clause as its own numbered item — bans count as requirements.
3. MAP each item to concrete evidence: the file+line, the command output, the exact
   behavior that satisfies it. No evidence = not satisfied.
4. MARK each item: MET / PARTIAL / UNMET. Round DOWN, never up. "Mostly done" = PARTIAL.
5. SCOPE-DRIFT CHECK: for everything you changed, find the requirement it serves. Any
   change with no matching item is added scope — flag it explicitly, do not smuggle it.
6. If any item is PARTIAL or UNMET, you are NOT done. Report the gap or close it.
```

## Hard bans

| Never do this | Do this instead |
|---|---|
| Restate the ask "in your own words" then work from the restatement | Work from the verbatim quote |
| Collapse "X and Y and Z" into "the task" | Number X, Y, Z as separate items |
| Ignore negative constraints ("no new deps", "don't touch file A") | List each ban as a numbered requirement |
| Round PARTIAL up to done | Mark PARTIAL, name what's missing |
| Ship extra changes because they seemed helpful | Flag added scope in the report, or drop it |
| "I think that covers it" | Show the item→evidence table |

## Reading the ask honestly

- A constraint stated once is as binding as the main task. "Quick fix, but keep the API
  unchanged" — the second clause is requirement #2, not a footnote.
- Vague verbs hide sub-asks: "clean up" often means format AND remove dead code AND
  rename. If ambiguous, list your interpretation as an item so the user can correct it.
- If you cannot satisfy an item (blocked, impossible, out of scope), say so explicitly:
  "Item 3 UNMET — cannot X because Y." Silence on a dropped item is the failure.

## Output contract

Final report contains a numbered requirement list (positive AND negative clauses), each
item marked MET / PARTIAL / UNMET with its evidence, and a scope-drift line naming any
change that served no listed requirement. One PARTIAL or UNMET item = not done.
