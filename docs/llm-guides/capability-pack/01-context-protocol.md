# 01 — Context Protocol

Rule: **never write to a file you haven't read, never add a pattern you haven't seen.**
Most weak-model damage comes from editing blind. This protocol prevents it.

## Before any edit

1. **Read the instructions file.** `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md`,
   `README.md` — whichever exist. Project rules override your defaults, always.
2. **Read the target file top to bottom** (or the full region for big files).
   Note: imports style, naming convention, error-handling pattern, comment density.
3. **Find a sibling.** Locate one existing file that does something similar to what
   you're about to write. Your new code must look like it was written by the same
   person. Copy its structure, not just its ideas.
4. **Grep before inventing.** Before writing any helper/util/type, search for an
   existing one:
   ```bash
   grep -rn "functionName\|ConceptName" --include="*.ts" --include="*.py" src/ | head -20
   ```
   Found one → use it. Duplicating an existing helper is a defect.
5. **Trace one caller.** Find who calls the code you're changing
   (`grep -rn "myFunction(" .`). Changing a signature/behavior without reading callers
   breaks them silently.

## Convention matching rules

- Same import ordering, same quote style, same indent as the file you're in — even if
  you prefer otherwise. Formatters/linters in the repo win over everything.
- Match comment density. If the file has few comments, don't add narration comments.
  Never write comments explaining what you changed ("// now handles null") — comments
  describe the code, not your edit.
- Use the project's existing libraries. Do not add a dependency without being asked.
- New file? Only when no existing file is the right home. Match neighboring file
  naming (`user_service.py` next to `auth_service.py`, not `UserSvc.py`).

## Scope discipline

- Touch only what the task requires. No drive-by refactors, no reformatting untouched
  lines, no "improving" adjacent code. Diff noise hides real changes and breaks review.
- If you notice a real problem outside scope, write it down (state file or final
  report) instead of fixing it now.

## Output contract

Before your first edit you can answer, from evidence not guesswork:
- What are the project's rules? (file read)
- What does the sibling pattern look like? (file read)
- Does my helper already exist? (grep run)
- Who calls what I'm changing? (grep run)

Can't answer one → go back and look. Never proceed on assumption.
