# 16 — Codebase Onboarding

Mapping an unfamiliar repo before touching it. 20 minutes of mapping prevents hours
of wrong-place edits. Output is a state file, so the map survives the session.

## The mapping protocol (in order)

1. **Read the front matter:** `README.md`, `CLAUDE.md`/`AGENTS.md`,
   `CONTRIBUTING.md`. Note: what the project IS, commands (build/test/run), stated
   conventions.
2. **Read the manifest:** `package.json` / `pyproject.toml` / `go.mod` — framework,
   key deps, scripts. The scripts section is a table of contents of what the project
   does.
3. **Skim the shape:**
   ```bash
   find . -maxdepth 2 -type d | grep -vE "node_modules|\.git|__pycache__|\.venv|dist" | sort
   git log --oneline -15        # active areas, commit style
   git shortlog -sn | head -5   # who works here (style authority)
   ```
4. **Find the entry point** (`main.py`, `app.py`, `index.ts`, `src/main.*`, the
   framework's convention) and read it fully — wiring, middleware, startup order.
5. **Trace ONE representative flow end-to-end.** Pick one route/command/screen; follow
   it: entry → handler → service/logic → data layer → response. This one trace teaches
   the architecture more than reading ten files in isolation.
6. **Read two tests.** Tests are executable documentation — they show the intended
   public API, fixture patterns, and how the project wants behavior expressed.
7. **Locate the config/env story:** `.env.example`, settings module, how secrets and
   environments differ.

## Write the map — `CODEBASE_MAP.md` (or scratch equivalent)

```markdown
# Map: <repo>
- Purpose: <one sentence>
- Stack: <framework, db, key libs>
- Commands: build=<…> test=<…> run=<…>
- Layout: <dir → responsibility, one line each>
- Flow traced: <route> → <files touched, in order>
- Conventions: <naming, error handling, test style — as OBSERVED, not assumed>
- Sharp edges: <drift, dead dirs, surprises, TODOs found>
- Open questions: <things not yet understood>
```

Working in the repo again later (or handing to another model) → read the map first,
verify commands still work, update what changed.

## Rules

- **No edits before the map exists.** The protocol IS the prerequisite for guide 01's
  per-edit checks — 01 is per-file; this is whole-repo, once.
- Answer questions from code you've READ, not from what the framework "usually" does.
  Every unverified assumption goes in Open questions, not in the map body.
- Big repo? Map only the subsystem you'll touch + its neighbors; note the boundary.
- Don't judge while mapping. "This is weird" goes in Sharp edges; refactoring
  proposals come later, with context (guide 08).

## Output contract

Map file written · one flow traced end-to-end (files listed) · test+build commands
RUN once to confirm they work (guide 05 — a map with untested commands is folklore).
