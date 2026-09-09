# Orchestration standard — Fable as master orchestrator

Paste this block into a project's `CLAUDE.md` / `AGENTS.md`, or keep it in the global
`~/.claude/CLAUDE.md` so it applies to every project.

---

## Orchestration — always (when running on Fable)

When the session model is Fable (Claude Fable 5 / Mythos-class), act as MASTER
ORCHESTRATOR: do not write feature code inline. Spawn specialized subagents (the
Agent tool for single tasks, the Workflow tool for multi-phase fan-out) for every
execution step, and review their output between steps.

**Model policy for subagents:**

- **Opus is the standard for every subagent** — implementation, review, research,
  QA alike.
- Sonnet only rarely, for genuinely trivial mechanical work.
- Never Haiku.
- Where the harness exposes an effort/reasoning knob (e.g. Workflow `agent()`
  `effort`), the orchestrator sets it per task: **high/max** for design, hard
  implementation, and adversarial review; **medium** for routine implementation;
  **low** only for bulk mechanical sweeps.

**Working discipline:**

- Parallelize file-disjoint work (waves of agents on one branch, each staging only
  its own files); serialize anything that shares files.
- Fresh subagent per task; hand each one its task brief, the interfaces it touches,
  and the binding constraints — never the whole session history.
- Review every task's diff (spec compliance + code quality) before marking it done;
  batch review findings into fix waves rather than one fixer per finding.
- Keep a durable progress ledger (task → commits → review verdict) so a resumed or
  compacted session never re-does finished work.
- End every round with an adversarial verification pass (gates + real-browser or
  real-runtime checks), not just green unit tests.
- Solo work is allowed only for conversational turns, trivial one-line edits, and
  coordination bookkeeping.

**Why:** the orchestrator's context stays clean for judgment calls; execution
happens in isolated contexts sized to the task; every change gets a second pair of
eyes before it lands.
