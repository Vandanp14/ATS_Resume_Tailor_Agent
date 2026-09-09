# 10 — Performance Pass

Rule: **measure → fix the biggest thing → measure again.** Optimizing without numbers
is guessing; weak models guess wrong and complicate code for nothing.

## 1. Get a number first

Reproduce the slowness with a repeatable measurement:

```bash
# HTTP endpoint
time curl -s -o /dev/null -w "%{time_total}s\n" localhost:8000/api/slow

# Python function
python -m cProfile -s cumtime app/script.py 2>&1 | head -25

# SQL query
# prefix the query with: EXPLAIN ANALYZE

# Frontend
# browser devtools Performance tab / Lighthouse; note LCP, bundle size:
npx vite build 2>&1 | tail -20   # or next build — read the size table
```

Record baseline in the report: metric, value, conditions. No baseline = no pass.

## 2. Find the biggest cost — usual suspects in order

1. **N+1 queries** — one query per loop iteration. Log SQL in dev and count queries
   per request; >10 for a simple page = suspect. Fix: eager load / join / batch fetch.
2. **Missing index** — `EXPLAIN ANALYZE` shows sequential scan on a large table with a
   WHERE/ORDER BY. Fix: add index on the filtered column(s), re-EXPLAIN to confirm.
3. **Fetching too much** — SELECT * for 3 fields, unpaginated lists, full-table loads
   into memory. Fix: select columns, paginate, stream.
4. **Work inside loops** that belongs outside — repeated parsing, compiled regexes,
   per-iteration I/O. Fix: hoist, batch.
5. **Sequential awaits** on independent I/O. Fix: `asyncio.gather` / `Promise.all`.
6. **Frontend:** unsplit bundles (lazy-load routes), unoptimized images (dimensions +
   modern format), render storms (state too high in tree, missing memo on hot lists),
   fetch waterfalls (parallelize, move fetch up).
7. **Missing cache** for hot, rarely-changing reads — LAST resort, after the above.
   Every cache needs a stated invalidation story or it's a future correctness bug.

Fix ONE thing — the biggest.

## 3. Re-measure

Same command as the baseline. Improvement < ~20% → revert the change (complexity not
paid for), pick the next suspect. Meaningful win → keep, commit separately
(`perf(scope): …`), then decide with the numbers whether target is met or loop again.

## Bans

- No micro-optimizing warm code (string concat style, loop unrolling) while any
  suspect above exists.
- No caching added "just in case".
- No rewriting in another language/framework as a first move.
- No perf claims without before/after numbers in the report (guide 05 applies).

## Output contract

Report: baseline number → change made (one per iteration) → after number → verdict.
Tests still green (guide 08 rules apply — perf changes preserve behavior).
