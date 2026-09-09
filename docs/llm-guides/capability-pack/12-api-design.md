# 12 — API Design

Checklist for every endpoint you add or change. An endpoint is a contract; contracts
are cheap to get right at creation and expensive to fix after clients exist.

## Per-endpoint checklist

**Shape**
- Nouns in paths, verbs in methods: `POST /orders`, not `POST /createOrder`.
- Plural collections, ID for items: `/orders`, `/orders/{id}`.
- Follow the codebase's existing URL/casing conventions over any general rule.

**Status codes — use the boring standard**

| Case | Code |
|---|---|
| Read OK / write OK returning body | 200 |
| Created (return the created resource + its ID) | 201 |
| Accepted for async processing | 202 |
| Success, nothing to return | 204 |
| Malformed/invalid input | 400 (or 422 if the framework convention) |
| Not authenticated | 401 |
| Authenticated but not allowed | 403 |
| Doesn't exist — or exists but caller may not know that | 404 |
| Conflict (duplicate, stale version) | 409 |
| Rate limited | 429 |
| Server bug | 500 (never for bad input) |

**Errors — one shape everywhere**

```json
{ "error": { "code": "ORDER_NOT_FOUND", "message": "human-readable", "field": "optional" } }
```

Machine-readable `code`, stable across releases. Message safe for end users — no
stack traces, no SQL, no internal paths (guide 09).

For published/external HTTP APIs, prefer the RFC 9457 `problem+json` envelope (see
`../../skills/integration-glue/references/api-contracts.md`); the shape above stays fine for internal APIs.

**Inputs**
- Schema-validate body/params (Pydantic/zod); reject unknown critical fields;
  enforce size limits. Validation failure → 400 with field-level detail.

**Lists**
- Paginate from day one (limit+cursor or limit+offset — match codebase). Default AND
  max limit enforced. Stable sort order documented. Unpaginated list = future outage.

**Writes**
- Idempotency: retried POST must not double-create — idempotency key, unique
  constraint, or upsert. PUT/DELETE naturally idempotent — keep them so.
- Return the resulting resource state so clients don't re-fetch.

**Auth** — who may call this, enforced server-side, object-level (guide 09 §3).

**Time/money fields** — ISO-8601 UTC strings; money as integer minor units or string
decimal, never float (guide 17).

## Changing an existing endpoint — compatibility rules

Additive is safe; everything else breaks somebody:

- OK: new optional field in response; new optional param with default preserving old
  behavior.
- BREAKING (needs version bump or new endpoint + deprecation): removing/renaming a
  field, changing a type, changing semantics of an existing field, tightening
  validation on inputs that used to pass, changing status codes.
- Never repurpose an existing field to mean something new — worse than removal,
  fails silently.
- Deprecate: mark in docs, keep serving, log usage, remove only when usage is zero.

## Output contract

For each endpoint: checklist above passes · error shape matches the codebase's ·
a test per: happy path, validation failure, authz failure, not-found (guide 04).
