# 11 — Environment & Setup Troubleshooting

Rule: **when code that "should work" doesn't, suspect the environment before the
logic.** "Works on my machine" is an environment diff, and environment diffs are
enumerable.

## First 60 seconds — identify what's actually running

```bash
which python && python --version     # or: which node && node -v
pip -V                               # shows WHICH site-packages pip targets
echo $VIRTUAL_ENV                    # venv actually active?
git rev-parse --short HEAD           # the commit you THINK you're testing?
git status --short                   # uncommitted changes affecting behavior?
```

Most "impossible" behavior = running a different binary, a different venv, a stale
build, or a different commit than assumed.

## The clean-room protocol

When installed state is suspect, rebuild it from the lockfile — don't hand-patch:

```bash
# Python
rm -rf .venv && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# Node
rm -rf node_modules && npm ci        # ci, not install — respects lockfile exactly
```

Then re-run the failing thing. Fixed → installed state had drifted; done. Still
broken → it's real; go to guide 03.

## Common diffs to enumerate (local vs CI vs prod, or you vs teammate)

- Language/runtime version (`.python-version`, `.nvmrc`, engines field — respect them)
- Lockfile vs manifest drift: `pip freeze | diff - requirements.txt` mentality;
  `npm ls <pkg>` for the version actually resolved
- Env vars: missing `.env` values (compare `.env.example`), different values in CI
- OS differences: case-sensitive filesystems (Linux CI vs macOS), path separators,
  line endings
- Services: DB/redis version, empty vs seeded database, port conflicts
  (`lsof -i :8000` to find who holds the port)
- Stale artifacts: build caches, `__pycache__`, old dist/ — clean before concluding
- Timezone/locale of the machine (see guide 17)

## Fix hygiene

- Fix the project files, not your machine: pin the version, update the lockfile,
  add the env var to `.env.example`, document the required service. A fix that lives
  only in your shell history dies with the session.
- New env var introduced → add to `.env.example` (placeholder value, never real
  secret) + mention in README/setup docs, same commit.

## Bans

- `sudo pip install` / global installs to fix a project problem
- Editing files inside `site-packages` / `node_modules` (lost on next install)
- "Fixing" version conflicts by deleting the lockfile
- Concluding "flaky" without one clean-room rebuild

## Output contract

Report states: what was actually running (binary+version+commit), the diff found,
the project-file fix committed. Not "reinstalled and it works now" with no cause.
