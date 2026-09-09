# 07 — Git Safety

Git is the undo button that makes everything else recoverable. Weak models lose work
by committing garbage, working on main, or running destructive commands casually.

## Session start

```bash
git status && git branch --show-current && git log --oneline -5
```

- Uncommitted changes you didn't make → STOP. Ask, or work around them. Never
  stash/reset someone else's work.
- On main/master and about to make changes → branch first:
  ```bash
  git checkout -b feat/<short-name>
  ```

## Commit discipline

- **One logical change per commit.** Refactor + feature + fix = three commits.
  Reviewable diff > big-bang diff.
- Commit when tests pass, before starting the next risky step — each green commit is a
  checkpoint you can return to.
- Stage explicitly: `git add <paths>`. Never `git add -A` / `git add .` without running
  `git status` first — that's how secrets, `.env`, build junk, and debug files leak in.
- Before committing, review what you're about to commit:
  ```bash
  git diff --staged
  ```
  Found debug prints / commented-out code / unrelated formatting → unstage and clean.

## Message format

```
type(scope): what changed, imperative, ≤50 chars

Body only when the WHY isn't obvious from the diff.
```

Types: feat, fix, refactor, test, docs, chore, perf. Message states what+why — never
"fix bug", "updates", "wip", "changes".

## Destructive commands — the gate

These require an explicit human instruction, verbatim, this session:

```
git push --force / --force-with-lease   git reset --hard
git checkout -- <file> (discards work)  git clean -fd
git rebase (rewriting pushed history)   git stash drop / clear
git branch -D                           rm -rf anything
```

Before ANY of them, even when instructed: run `git status` + `git log --oneline -3`,
confirm what will be destroyed matches what the human described. Mismatch → stop and
report, don't proceed.

Safe alternatives first: revert instead of reset (`git revert <sha>` keeps history) ·
new branch instead of rewriting · `git stash` instead of discarding (and say so).

## Recovery moves

```bash
git reflog                    # find any lost commit — nothing committed is ever gone
git checkout <sha> -- <file>  # restore one file from any point
git revert <sha>              # undo a commit without rewriting history
git bisect start              # binary-search which commit broke it
```

Broke something and unsure how → reflog BEFORE attempting creative fixes.

## Push/PR rules

- Push and open PRs only when asked.
- Never push directly to main when a PR flow exists.
- PR description: what + why + how verified (evidence per guide 05), not a file list.
