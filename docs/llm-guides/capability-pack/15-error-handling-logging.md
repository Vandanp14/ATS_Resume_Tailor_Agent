# 15 — Error Handling & Logging

Rule: **every error is either handled meaningfully or propagated loudly — never
swallowed.** The catch block you write casually today is the invisible outage
someone debugs for a day next year.

## The catch test

Before writing ANY catch/except, answer three questions. Can't answer → don't catch;
let it propagate to someone who can.

1. **Can I actually handle it here?** (retry, fallback with equal correctness,
   convert to a domain error) — or am I just hiding it?
2. **What does the caller/user see when this fires?** "Empty list that looks like
   success" = wrong answer.
3. **Will anyone know it happened?** If handled silently, log it.

## Error taxonomy — three kinds, three treatments

| Kind | Examples | Treatment |
|---|---|---|
| **Expected** | validation failure, not-found, permission denied | Return typed/structured error to caller. Not logged as error (info/debug at most). Not an exception in hot paths if the language favors result types. |
| **Transient** | network timeout, deadlock, 429/503 from upstream | Retry with backoff + jitter, BOUNDED attempts, only for idempotent operations. Log warn on retry, error on exhaustion. |
| **Bug** | null where impossible, broken invariant, unhandled case | Fail fast and loud. Never catch-and-continue. Stack trace to logs, generic message to user. |

Catch **specific** exception types matching the kind you can handle.
`except Exception` / bare `catch (e)` belongs ONLY at top-level boundaries
(request handler, worker loop, main) where it logs with stack trace and returns a
clean 500 — nowhere else.

## Placement: handle at boundaries, add context in the middle

- Log an error ONCE, at the boundary that handles it. Log-and-rethrow at every layer
  = same failure five times in the logs, all noise.
- Middle layers that can't handle: either don't catch, or catch → wrap with context
  (`raise OrderSyncError(f"order {id}") from e` — keep the cause chain) → rethrow.
- User-facing surface splits the message: safe generic text out, full detail +
  correlation/request ID into logs (guide 09 §5).

## Logging discipline

Levels — pick by "who needs to wake up":

- `error`: broken, needs human action. An error log nobody would act on is noise —
  downgrade it.
- `warn`: survived but degraded (retry fired, fallback used, config missing→default).
- `info`: lifecycle facts (started, listening, job done, migration ran).
- `debug`: development detail; off in prod.

Rules:
- Structured over prose: `log.error("payment failed", order_id=id, err=str(e))` —
  greppable keys, not sentence soup.
- Include enough to debug WITHOUT reproducing: IDs, operation, input summary. Never
  secrets/tokens/passwords/full PII (guide 09).
- Exceptions logged WITH stack trace (`logger.exception(...)` / `logger.error(msg,
  exc_info=True)`) — message-only logs amputate the trace.
- No `print()` left in production paths; use the project's logger.

## Fallback rule

A fallback value (cache miss → empty, API down → default) is legitimate ONLY when the
degradation is invisible-safe AND logged. Fallback that masks an outage as normal data
(error → `return []` → user sees "no transactions") is the classic silent failure —
guide 06 hunts these; don't write them.

## Output contract

Every catch block passes the three-question test · specific exception types ·
boundaries log once with stack trace + context · retries bounded, idempotent-only ·
zero silent fallbacks · no stray prints.
