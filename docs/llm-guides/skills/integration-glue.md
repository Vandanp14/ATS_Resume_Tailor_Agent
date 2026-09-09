<!-- Source: vandan-llm-toolkit skills/integration-glue/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# Integration Glue

Weak models write happy-path integrations: no timeout, no retry discipline, no idempotency, unverified webhooks, vague tool schemas, raw third-party JSON spread straight into domain types. The code demos fine and rots in production — the first slow dependency, duplicate delivery, or replayed webhook takes it down. **The seams are where LLM-built systems fail, and seam discipline can be written down.** This skill is that written-down discipline: the reliability contract every boundary must satisfy, regardless of which model holds the pen.

A seam is any place your process talks to something it does not control in the same memory space: an internal service, a third-party API, an inbound webhook, a database, an event broker, an MCP server. Each has a small set of failure modes and a matching discipline. Get the discipline right at the boundary and the core stays clean; get it wrong and no amount of business-logic correctness saves you.

This skill owns seam **reliability**. Seam **security** (injection, authz, secrets, prompt injection) lives in the `secure-by-default` skill — one pointer, not a restatement. Installed-version doc lookup lives in `version-grounded-coding`. Design-level API shape lives in guide 12; migrations in 13; error-handling philosophy in 15; data correctness in 17. Read those for the design pass — this skill owns the contract, compatibility, and consumer mechanics that keep a live boundary from rotting.


## Operating rules

1. **Every outbound call gets a timeout.** Separate connect, read, and total budgets — never one blanket socket timeout, never the library default (usually infinite).
2. **Every retry is idempotent-safe or not sent.** A retry that may double-commit is a bug, not resilience. Gate retries on method + status; carry an idempotency key on unsafe methods you must retry.
3. **Every seam returns the house error envelope.** RFC 9457 `application/problem+json` on the way out; validate and translate on the way in. No bespoke `{error: "..."}` shapes.
4. **Every consumer dedups.** All delivery — webhooks, events, outbox relay — is at-least-once. Persist the provider's event id, ignore repeats, make handlers idempotent.
5. **Every seam has a deadline that propagates.** Compute an absolute deadline at the edge, pass it downstream, and give each hop `deadline − now − buffer`.
6. **Every MCP tool ships a complete input schema.** No tool without a JSON Schema describing every argument and constraint.


## Classify the seam, then read the reference

| Seam type | Top failure modes | Read |
|---|---|---|
| Internal / east-west API | cascading timeout, retry storm, no deadline budget | `references/resilience.md`, `references/api-contracts.md` |
| Third-party API / SDK | rate-limit bans, sandbox↔prod bleed, unpinned SDK, raw-response leakage | `references/mcp-and-third-party.md`, `references/resilience.md` |
| Inbound webhook | forged/replayed payloads, duplicate delivery, parse-before-verify | `references/data-and-events.md` |
| Database | N+1, pool exhaustion, non-atomic dual-write | `references/data-and-events.md` |
| Event / queue out | lost or duplicated events, dual-write gap | `references/data-and-events.md` |
| MCP server / tool | vague schema, wrong error tier, tool poisoning, over-privilege | `references/mcp-and-third-party.md` |


## Hard bans

- **No outbound call without a timeout.** Not the default. An explicit connect + total budget.
- **No retry without backoff + full jitter + idempotency.** All three or don't retry.
- **No webhook handler without signature + timestamp check** on the raw body, constant-time compare, before parsing.
- **No spreading raw API responses into your domain types.** Validate and map at the boundary; a provider field change must not silently reshape your model.
- **No N+1 in a loop when a batch/join endpoint exists.** Eager-load or batch.
- **No MCP tool without a complete input schema.** `inputSchema` is required and MUST NOT be null.


## Canonical values

Copy these verbatim. Do not soften them.

**Timeout budgets**
```
connect timeout:            1–5 s
internal / east-west total: 1–3 s   (a same-cluster call over ~3s is overloaded — fail fast)
external third-party total: 10–30 s (noisy networks need TCP-retry slack)
deadline header:            x-request-deadline = absolute unix millis, propagated every hop
```

**Retry defaults**
```
algorithm:   full jitter -> sleep = random(0, min(cap, base * 2^attempt))
base:        200 ms      cap: 20 s      maxAttempts: 5
retryable:   408, 429, 500, 502, 503, 504 + transient transport errors
never retry: other 4xx, 501, 505, or any non-idempotent POST that may have committed
Retry-After: when present on 429/503, honor it EXACTLY instead of computed backoff
```

**Idempotency-key semantics** (Stripe reference)
```
key:       client-supplied UUIDv4, scoped per account + endpoint
store:     {key -> saved status + body}, retention 24h
replay <24h with same params:      return the ORIGINAL saved status+body
replay with different params:      422 (key reused with different parameters)
arrives while first still running: 409 (retry later)
saved only once execution begins:  validation/conflict failures do NOT poison the key
```

**Error envelope** (RFC 9457, `Content-Type: application/problem+json`)
```json
{ "type": "https://api.example.com/problems/validation-error",
  "title": "Your request parameters didn't validate.",
  "status": 422,
  "detail": "'age' must be a positive integer.",
  "instance": "/orders/12345",
  "errors": [ { "pointer": "#/age", "detail": "must be >= 0" } ] }
```
`status` MUST match the HTTP status. `title` is stable per problem type; `detail` is per-occurrence.


## Output contract — the seam-review gate

Before you call an integration done, confirm every line:

- [ ] Every outbound call has explicit connect + total timeouts; a deadline is computed at the edge and propagated.
- [ ] Retries use full jitter, a cap, a max-attempt count, and fire only for retryable status/method combinations; `Retry-After` is honored.
- [ ] Unsafe methods that retry carry an idempotency key; the server stores and replays saved responses.
- [ ] A circuit breaker fronts any dependency that can fail persistently (not just transiently).
- [ ] Every outbound error is an RFC 9457 problem document; inbound errors are validated and mapped, never spread raw.
- [ ] Webhook handlers verify HMAC signature + timestamp tolerance on the raw body with a constant-time compare, then dedup by provider event id.
- [ ] DB writes that must publish events use the transactional outbox; consumers dedup at-least-once delivery.
- [ ] No N+1: relations are eager/batch-loaded; pool is small and bounded with an acquisition timeout.
- [ ] Every MCP tool has a complete input schema; recoverable failures return `isError` results, protocol faults return JSON-RPC errors.
- [ ] Third-party SDKs are pinned; responses are validated at the boundary; sandbox and prod credentials are separated.
- [ ] Seam **security** checked against `secure-by-default`; installed versions confirmed via `version-grounded-coding`.
