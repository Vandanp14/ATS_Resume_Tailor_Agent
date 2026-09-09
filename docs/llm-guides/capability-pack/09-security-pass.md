# 09 — Security Pass

Pre-ship checklist for anything network-facing. Defensive baseline only — this guide
hardens your own app. Run it phase by phase; each check is a grep or a question with
a yes/no answer.

## 1. Secrets

```bash
# scan the diff / repo for likely secrets
grep -rnE "(api[_-]?key|secret|passw(or)?d|token)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}" \
  --include="*.py" --include="*.ts" --include="*.js" --include="*.env*" . | grep -v node_modules
```

- Zero hardcoded secrets; all via environment variables / secret manager.
- `.env*` in `.gitignore`; verify: `git check-ignore .env` prints `.env`.
- A secret ever committed (even deleted later) = compromised → rotate it, don't just
  remove it.
- No secrets in logs, error messages, or client-side code (anything sent to the
  browser is public).

## 2. Input validation — trust nothing external

Every input from outside the process (HTTP params/body/headers, file uploads, webhook
payloads, CLI args in exposed tools):

- **SQL:** parameterized queries / ORM only. Grep for string-built SQL:
  ```bash
  grep -rnE "(execute|query)\(.*[%+].*(f\"|f'|\+)" --include="*.py" .
  ```
- **Shell:** never interpolate user input into shell commands. Use exec-array APIs
  (`subprocess.run([...])`), never `shell=True` with user data.
- **Paths:** user-supplied filenames resolved and checked against a base directory
  (`../../etc/passwd` must fail).
- **Types/bounds:** schema-validate request bodies (Pydantic/zod/etc.); reject, don't
  coerce, on failure. Enforce size limits on bodies and uploads.
- **Output encoding:** HTML-escape user content in templates; framework auto-escaping
  ON (no `dangerouslySetInnerHTML` / `| safe` with user data).

## 3. AuthN / AuthZ

- List every endpoint/route added or changed. For EACH: who may call it, and where is
  that enforced? "The frontend doesn't link to it" is not enforcement.
- Object-level checks: user A must not read/update user B's row by changing an ID in
  the URL (test it: authenticate as A, request B's resource ID, expect 403/404).
- Auth on the server, per request — not only middleware-by-path if paths can be missed;
  verify new routes actually fall under the guard.
- Tokens/sessions: expiry enforced (`<=` semantics checked), logout invalidates,
  cookies `HttpOnly; Secure; SameSite`.

## 4. Transport & headers

- HTTPS assumed/enforced in prod; no plain-HTTP calls to internal services carrying
  credentials.
- CORS: explicit origin allowlist. `*` with credentials = broken, never ship it.
- Rate limiting or abuse consideration on auth and expensive endpoints.

## 5. Errors & logging

- Stack traces / internal paths / SQL never returned to clients — generic message out,
  detail into server logs.
- Log auth failures and permission denials (you'll want them during an incident);
  never log passwords/tokens/PII.

## 6. Dependencies

```bash
npm audit --omit=dev || pip-audit || true
```

Fix criticals in direct dependencies before shipping; record accepted risks in the
report.

## Output contract

Report lists each section with pass / fail+fix / not-applicable, plus grep evidence
for sections 1–2. Anything failed and deliberately shipped = written risk note, named
owner decision — never silent.
