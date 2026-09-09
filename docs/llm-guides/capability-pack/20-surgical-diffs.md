# 20 — Surgical Diffs

Rule: **change the fewest lines that satisfy the ask; leave every other byte identical.**
Weak models rewrite a 200-line file to change 3 lines, reflow the imports, and restyle
the code to their own taste — burying the real change in noise no reviewer can trust.
This guide deletes that habit.

## The smallest-diff contract

1. **Edit in place.** Locate the exact lines that must change and change only those.
   Never regenerate a whole file to alter part of it.
2. **Unrelated lines stay byte-identical.** Same indentation, same quotes, same blank
   lines, same comment text, same import order — even where you dislike them.
3. **No drive-by reformatting.** Do not reorder imports, switch quote style, re-wrap
   lines, normalize whitespace, or "tidy" anything the task did not name.
4. **One logical change per edit.** No "while I'm here" fixes, renames, or refactors
   riding along. They get their own edit, or their own task.
5. **Keep the hunk reviewable.** A human should see the diff and understand the whole
   change in seconds. If the diff is mostly untouched code re-emitted, you failed.

## Hard-ban list — never do these inside a task edit

- Rewriting a file end-to-end to change a subset of it.
- Reordering, deduplicating, or reformatting imports you didn't need to touch.
- Changing quote style, indentation width, or line-wrapping of existing code.
- Re-indenting or whitespace-normalizing untouched regions.
- Deleting or rephrasing comments, docstrings, or dead branches you didn't touch.
- Adding unrequested features, logging, type hints, or "improvements."
- Renaming variables/functions outside the lines the task requires.

If a formatter or auto-fixer would do any of the above on save, **turn it off** or
stage only the intended hunks. A tool's reflow is still your diff.

## When a real rewrite is justified

Rewrites are legal only when the task *is* the rewrite — never as a side effect. Allowed:

- The task explicitly says "rewrite / port / replace file X."
- The change touches the majority of lines anyway (e.g., new algorithm for the whole
  function), so a targeted edit would be more confusing than a clean replacement.

**Isolate it:** make the rewrite its own commit/edit with nothing else in it. State in
your report "this is a full rewrite of X because Y." Preserve every behavior, comment,
and public signature the task didn't call out for change. A rewrite is not a license to
restyle — it is a like-for-like replacement plus the one intended change.

## Locating before editing

Read the target region fully before touching it (see guide 01). Match the exact
existing text — indentation and all — so your edit lands only where intended. If you
can't see the surrounding lines, you can't guarantee you left them alone; read first.

## Pre-submit self-check

Before you present any edit, run this and answer honestly:

```
1. View the diff:  git diff  (or your tool's diff view).
2. For EVERY changed line, ask: is this line required by the task?
3. Any line that is not — revert it to byte-identical original.
4. Confirm: imports, quotes, whitespace, comments outside the change = untouched.
5. Confirm: exactly one logical change is present. More? Split into separate edits.
```

## Output contract

The diff contains only lines the task required, plus their minimal surrounding context.
Every unrelated line is byte-for-byte unchanged. No reordered imports, no restyling, no
drive-by fixes. If a full rewrite was used, it is isolated in its own edit and labeled
as such in the report.
