# 14 — Dependency Management

Every dependency is code you now ship but don't control. Adding one is an
architectural decision; upgrading one is a change like any other — it gets the full
verify treatment.

## Adding a dependency

Gate questions, in order — all must pass:

1. **Does the project already solve this?** Grep first (guide 01). Second date-lib /
   second HTTP client / second state manager = defect.
2. **Is it stdlib-trivial?** <30 lines of stdlib code (leftPad-class, simple debounce,
   one regex) → write it, don't install it.
3. **Is it alive and sane?** Check: last release date, weekly downloads, open-issue
   pattern, license compatible with project, transitive dependency count
   (`npm info <pkg>`, PyPI page). Abandoned or 200-dep-tree → find alternative.
4. **User approval.** Don't add dependencies without being asked or asking —
   especially in someone else's codebase.

Install correctly: exact/pinned version per project convention, manifest AND lockfile
updated in the same commit, dev vs prod dependency placed correctly
(`--save-dev` / dev extras).

## Upgrading

- **One dependency per commit.** Bump-everything commits are undebuggable — when the
  suite breaks, you can't tell which bump did it.
- Patch/minor: upgrade → full test suite → commit (`chore(deps): bump X 1.2→1.4`).
- **Major: read the changelog/migration guide FIRST.** List the breaking changes that
  touch your usage (grep your imports of it), apply the migration, then test.
  No changelog read = no major bump.
- Framework majors (React/Next/Django…): use the official codemod/upgrade tool if one
  exists; that's what it's for.
- After any bump: lockfile diff reviewed — unexpected transitive jumps are where
  surprises (and supply-chain attacks) live.

## Security response

```bash
npm audit --omit=dev   # or: pip-audit
```

- Critical/high in a DIRECT dependency: upgrade now, targeted.
- In a transitive dep: prefer upgrading the direct parent; overrides/resolutions
  pinning only as a stopgap, with a comment + tracking note.
- Ignore-list an advisory only with a written reason ("dev-only tool, not shipped").

## Removing

Removal is an upgrade too: grep usage → zero hits → uninstall → manifest+lockfile in
one commit → suite green. Dead dependencies still cost audit surface and install time.

## Bans

- Editing lockfiles by hand.
- Deleting the lockfile to "fix" a conflict (resolve it properly or regenerate and
  REVIEW the diff).
- `npm install` in CI (use `npm ci`); unpinned versions in requirements.
- Copying a library's source into the repo to dodge the decision (vendoring is a real
  choice with a written reason, not a shortcut).

## Output contract

Each dependency change: its own commit · manifest+lockfile consistent · suite green
after (guide 05) · majors list the breaking changes handled · audit clean or risks
written down.
