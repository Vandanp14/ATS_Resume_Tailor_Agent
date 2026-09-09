<!-- Source: vandan-llm-toolkit skills/secure-by-default/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# Secure by Default

An LLM's default output is a security disaster, and the reason is structural. Its training corpus is decades of tutorials and demo code that build SQL by string concatenation, drop user input into `innerHTML`, hash passwords with SHA-256, and inline API keys — so those patterns read as the *natural* way to write the code. The model reproduces the median of what it saw, and the median is insecure. Frontier-quality security comes not from a smarter model but from refusing to emit that median.

That refusal happens **while you write**, not in an audit at the end. Retrofitting a parameterized query or a `HttpOnly` cookie afterward means hunting the insecure line you already shipped; applying the convention as you write means it never exists. This skill is the deep convention layer. The workflow-level pass — **[guides/capability-pack/09-security-pass.md](../../guides/capability-pack/09-security-pass.md), read it first** — says *when* to run the gate and how to report it; this skill gives the copy-paste values and bad→good pairs it points into.


## Operating rules

Apply on **every** feature touching input, auth, data, or deploy. Not a separate audit step — a writing convention.

1. **Treat every value from outside the process as hostile** — params/body/headers, uploads, webhooks, URLs, CLI args. Re-validate server-side with a schema (zod/Pydantic) even when the client checked; client validation is UX, never a boundary.
2. **Parameterize every query; never build a shell string from input.** No string-interpolated SQL, ever. Dynamic table/column names go through an allowlist; subprocesses use the argv/exec-array form, never `shell=True`.
3. **Render untrusted data as text, not HTML.** `textContent` / JSX escaping; `innerHTML` / `dangerouslySetInnerHTML` only on `DOMPurify.sanitize()` output.
4. **Authenticate AND authorize.** Every request on a specific object must verify the principal owns *that object* — scope the query by owner id or run a policy check. Deny by default. Missing authorization is the most common LLM omission.
5. **Never bind whole request bodies to persistence.** Destructure allowed fields before any `create`/`update`; keep `role`, `isAdmin`, `ownerId`, `balance` off the bindable set.
6. **Use a CSPRNG for anything security-sensitive** — tokens, IDs, reset codes, salts. Never `Math.random()` / `random`.
7. **Hash passwords with a memory-hard KDF** (Argon2id) using the [canonical params](#canonical-values). Never plaintext, MD5, SHA-1, or unsalted SHA-256.
8. **Keep secrets server-side only** — never committed, never in client code (`NEXT_PUBLIC_*` is public), never in logs. Proxy third-party calls through your backend.
9. **Return generic errors to clients; log detail server-side** with an opaque correlation id. No stack traces, SQL, or paths in responses; no passwords/tokens/PII in logs.
10. **Rate-limit auth and expensive endpoints** per-IP and per-account, before the handler runs.


## Which reference to read (classification table)

Match the surface to its risks, then read that reference **just-in-time** — only the row you are on, when you reach it.

| Surface | Top risks | Read |
|---|---|---|
| Form input / request body | XSS, mass assignment, client-only validation | [references/injection-and-input.md](references/injection-and-input.md) |
| API endpoint | IDOR/broken authz, mass assignment, verbose errors | [references/injection-and-input.md](references/injection-and-input.md) + [references/auth-and-secrets.md](references/auth-and-secrets.md) |
| Auth flow (login/session/JWT) | weak hashing, localStorage tokens, no rate limit, no expiry | [references/auth-and-secrets.md](references/auth-and-secrets.md) |
| DB access | SQL injection, IDOR | [references/injection-and-input.md](references/injection-and-input.md) |
| File upload | path traversal, type spoofing, DoS, webshell | [references/injection-and-input.md](references/injection-and-input.md) |
| Outbound fetch (URL preview/webhook/proxy) | SSRF to internal services + cloud metadata | [references/injection-and-input.md](references/injection-and-input.md) |
| Deploy / ship to prod | debug on, missing headers, hallucinated deps, leaked secrets | [references/deploy-gate.md](references/deploy-gate.md) |

Glosses: **injection-and-input** — bad→good pairs for SQLi, XSS, eval/exec, traversal, SSRF, mass assignment, uploads. **auth-and-secrets** — hashing params, session/JWT rules, IDOR pattern, rate-limit defaults, secrets hygiene. **deploy-gate** — numbered production-readiness gate, one verify command per check.


## Hard bans

Flat prohibitions — disaster patterns the corpus taught the model. Never emit one.

- **Never** interpolate untrusted data into a SQL string, shell command, `eval`, or dynamic import.
- **Never** pass user data to `innerHTML` / `dangerouslySetInnerHTML` / `document.write` without `DOMPurify`.
- **Never** hardcode a secret or reference one from client-shipped code (`NEXT_PUBLIC_*`, browser `import.meta.env`).
- **Never** store a JWT or session token in `localStorage`/`sessionStorage`.
- **Never** send `Access-Control-Allow-Origin: *` with credentials, or reflect an unvalidated `Origin`.
- **Never** hash a password with MD5/SHA-1/unsalted SHA-256, or store it recoverable.
- **Never** use `Math.random()` for a token, id, salt, or secret.
- **Never** `Model.create(req.body)` / `Object.assign(entity, req.body)` — allowlist fields.
- **Never** return `err.stack` / raw errors to the client, or ship with debug mode on.
- **Never** install a package name an LLM emitted without verifying it exists and is the intended one (slopsquatting).
- **Never** trust a client-supplied filename or `Content-Type` on an upload; verify by magic bytes.


## Canonical values

Copy verbatim — current per OWASP Top 10:2025 and the cheat sheets. Never substitute from memory.

```
# Security headers (production HTTPS response):
Strict-Transport-Security: max-age=63072000; includeSubDomains; preload
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Content-Security-Policy: default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'
Permissions-Policy: geolocation=(), camera=(), microphone=(), payment=(), usb=(), magnetometer=()
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Embedder-Policy: require-corp
Cross-Origin-Resource-Policy: same-site
Cache-Control: no-store          # on authenticated/sensitive responses
# Omit `preload` unless you control ALL subdomains. Ship CSP as Report-Only first, then enforce.

# Auth/session cookie:
Set-Cookie: __Host-session=<id>; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=1800

# Password hashing (Argon2id minimum; raise m as hardware allows):
m=19456 (19 MiB), t=2, p=1       # equivalents: m=47104,t=1,p=1 | m=12288,t=3,p=1
# no Argon2id? scrypt N=2^17,r=8,p=1 | bcrypt cost>=10 (72-byte cap) | PBKDF2-SHA256 600000 (FIPS)
```


## Output contract — pre-ship security gate

Confirm each item before calling a feature done; a failed item is a written risk note with a named owner, never silent. This is the deep-convention checklist [09-security-pass.md](../../guides/capability-pack/09-security-pass.md) reports against.



- [ ] External input schema-validated server-side; queries parameterized; no shell/eval on input.
- [ ] Untrusted data rendered as text or DOMPurify-sanitized — no raw `innerHTML`.
- [ ] Every object-scoped route verifies ownership (IDOR-tested: auth as A, request B's id → 403/404); writes allowlist fields.
- [ ] Passwords Argon2id with canonical params; tokens/ids from a CSPRNG.
- [ ] Session/JWT in `HttpOnly; Secure; SameSite` cookies with expiry, never `localStorage`; auth endpoints rate-limited.
- [ ] Secrets server-side only, gitignored, out of logs and client bundle; any once-committed secret rotated.
- [ ] CORS is an exact-origin allowlist (no `*`+credentials); errors generic to client; debug off in prod.
- [ ] The full [deploy gate](references/deploy-gate.md) passes before shipping to production.

Quality and test discipline backing these checks live in capability-pack guides 04, 05, 15, 17, and 22. For a dependency's *installed* API and version before you use it, the **version-grounded-coding** skill owns that lookup.
