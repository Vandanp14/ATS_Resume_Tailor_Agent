<!-- Source: vandan-llm-toolkit skills/hunting-hidden-root-causes/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# Hunting Hidden Root Causes

**REQUIRED BACKGROUND:** superpowers:systematic-debugging (this specializes its Phase 1-2 for bugs where the defect hides outside the layer the report's wording points at).

## Overview

A report like "I did X, but Y never happened" names a *trigger*, not a *location*. The words used ("payload," "deploy," "sync," "permission") describe whichever component the reporter can see confirm success — not necessarily where the defect lives. Investigating only that named component, then stopping at the first plausible story there, is the single most common way this bug class gets missed repeatedly, across every domain.

## Report-vocabulary bias

Notice when the bug's wording is quietly steering you:
- "New **payload** not showing" → pulls toward backend ingestion. The defect can be in the *viewer* that never re-checks.
- "**Deploy** shipped but old version still serving" → pulls toward the build/CD pipeline. The defect can be a CDN/edge cache, or a load balancer still routing to an old instance.
- "**Config** updated, service still uses old value" → pulls toward the config store. The defect can be that the service caches config in memory and nothing signals a reload.
- "**Permission** revoked, access still works" → pulls toward the IAM/policy layer. The defect can be a session/token cache on the client, or a check-path that reads a stale local copy.
- "**Message** published, consumer didn't react" → pulls toward the producer. The defect can be the consumer's own dedup/offset state, or a swallowed ack.

Rule: name the layer the report points to, then deliberately look at least one hop past it before forming a hypothesis.

## The propagation triad

Any "A confirms, B should reflect it" system has (at least) three independent points of failure. Check all three — they aren't mutually exclusive:

| Layer | Question | Cross-domain examples |
|---|---|---|
| **Source gate** | Does the origin's write path *unconditionally* trigger propagation, or is it gated behind a condition that can be silently false for genuinely-new data (empty diff, a merge/dedup comparison that ties, a swallowed exception, an early return)? | A rebuild-trigger keyed on "did anything change" that computes "no" incorrectly; a CI job that only redeploys `if (files_changed)` and misjudges the diff; a queue consumer that acks before processing, masking a failure. |
| **Transport/cache** | Is there *any* intermediary — cache, CDN, proxy, service worker, read replica, materialized view, in-memory cache — that can return stale state with a healthy-looking response and no error? | A `NetworkFirst` service-worker cache; a read replica with lag; a CDN edge cache with a long TTL; a config library that only reads env vars at process start. |
| **Consumer re-check** | Does the observing side actually re-observe, or did it check once and never learn about the update? | A UI component that fetches once on mount and never refetches; a long-lived worker process holding a config snapshot; a browser tab open before a change landed. |

The consumer-re-check layer is the one most often skipped, because it's rarely named by the report's vocabulary and it lives furthest from where the "confirmed" event occurred. It's also usually the cheapest to confirm: a check-once bug reproduces 100% of the time, no flaky network or race condition required — prefer it when the mechanism fits, because it's the most falsifiable.

## Evidence, ranked

1. `git log --oneline -- <suspect file>`, then read the *full* diff of the most recent relevant commit — recency correlates with "this just started."
2. Any design/spec doc describing intended behavior, diffed against shipped code. A comment or doc contradicting the code (or the code contradicting its own comment) is a strong signal — but only if untested.
3. Existing tests for the suspected area, checked *before* calling something a bug. If a test already asserts the behavior, it's intentional — move on. The gap next to a well-tested case is where bugs actually hide.
4. Live/current state over local/long-idle state — say explicitly when you're relying on stale or unrepresentative data instead of drawing conclusions from it.
5. If a secret leaks through a log or tool result, don't use it to pull further live data — flag it separately and stay inside the access you were actually granted.

## Adversarial verification before reporting

Don't report your leading hypothesis as-is. Spawn independent checks with narrow, adversarial mandates, in parallel:
- One hunting a layer of the triad you didn't focus on.
- One trying specifically to *refute* your leading hypothesis.

Synthesize: keep only findings with concrete evidence (file:line, log line, commit hash), rate confidence per finding, and report every real bug found — not just the one that first seemed to fit. Two independent bugs coexisting near the same code is common, not a coincidence to explain away.

## Common mistake

Treating "source didn't propagate" and "consumer didn't re-check" as competing explanations for the same report. They're usually independent bugs that coexist — fix and report both if both are real.
