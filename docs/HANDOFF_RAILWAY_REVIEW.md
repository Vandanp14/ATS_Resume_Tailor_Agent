# Railway and Resume Review Handoff

This document records the implementation completed on 2026-09-09 so another agent can
continue without reconstructing the work from chat history.

## Repository state

- Repository: `Vandanp14/ATS_Resume_Tailor_Agent`
- Branch: `main`
- Delivered commit: `a7cf9ce feat: harden Railway deployment and resume review workspace`
- Remote: `origin/main` contains the delivered commit.
- Working tree: clean after the commit.
- Railway project: `ats-resume-tailor` (`c92dda1c-5a6c-4e6d-b60c-baaee1ef3ec6`)
- Railway service: `ats-resume-tailor` (`f2f58754-45ca-43d4-8569-d5170c69defd`)
- Production environment: `32494d4f-7782-4929-8b57-30abdc78f61e`
- Persistent volume: `ats-resume-tailor-volume` (`1cee6d15-393d-4858-aba0-b3e4b65fefec`), mounted at `/data`
- Live URL: https://ats-resume-tailor-production-1da4.up.railway.app
- Deployment: `eaf2f516-11ab-4d32-bca9-51e93e3b91c9` (SUCCESS, one RUNNING instance)

The implementation was started only after verifying that the prior baseline was clean and
already pushed (`47dd19c`).

## What changed

### Railway and container deployment

- `Dockerfile` builds the Tailwind/daisyUI assets in a Node 22 stage, then runs the app in
  Python 3.13.2.
- Tectonic 0.15.0 is downloaded from its official release, SHA-256 verified, and installed
  for PDF rendering.
- `railway.toml` selects the Dockerfile builder, `/healthz` health check, one replica, and
  an `ON_FAILURE` restart policy with three retries.
- `.dockerignore` and `.railwayignore` exclude secrets, personal resume data, generated
  output, local environments, and agent state.
- `DATA_DIR` defaults to `/data` in hosted environments. Mount a Railway volume at `/data`.
- `scripts/pdf_smoke.py` compiles the real resume template during the image build.
- `webapp.py` reads Railway's `PORT`, binds to `0.0.0.0` when `RAILWAY_ENVIRONMENT_ID` is
  present, and uses `/data` for the master resume, output, PDF library, and queue state.

### Hosted access and security

- `resume_tailor/web/access.py` implements scrypt password verification with a CSPRNG salt,
  opaque in-memory sessions, 30-minute expiry, five login attempts per minute, and secure
  HttpOnly SameSite cookies.
- Hosted mode requires both `PUBLIC_ORIGIN` and `APP_PASSWORD_HASH`; `PUBLIC_ORIGIN` must
  be an exact HTTPS origin without a trailing slash.
- API and UI requests are protected by the host/origin allowlist and session middleware.
- `/healthz`, `/login`, and the login endpoint remain available before authentication.
- Security headers include CSP, HSTS in hosted mode, frame denial, no-sniff, referrer,
  permissions, COOP, and CORP policies.
- Client and server error responses use the existing RFC 9457-style problem envelope.
- Body size is bounded at 512 KB before API parsing.

Sessions are intentionally in memory for the current single-user, one-replica deployment.
If this becomes multi-user or multi-replica, move sessions and identity data to a durable
store before scaling.

### Queue durability and request reliability

- Waiting job payloads continue to persist privately under the state directory.
- Original job requests are saved under `state_dir/requests/` so “Tailor again” can reload
  the original description and options.
- Queued jobs are hydrated in creation order after a restart, using microsecond timestamps.
- Queued jobs removed through the API remove their payload, metadata, and saved request.
- Graceful FastAPI lifespan shutdown stops and joins the worker for up to 20 seconds.
- A client can persist the same idempotency key and replay a lost submission response instead
  of creating a duplicate job.
- Queue admission is bounded at 100 waiting jobs.
- A restart still marks a running job as interrupted/failed unless a recoverable queued
  payload exists. A future improvement can add an explicit “retry interrupted run” action.

### Review workspace

- The sidebar has company/role search and status filtering.
- The creation form is JD-first, supports a saved browser-tab draft, and can copy clearly
  labeled company/role lines from the description.
- “Tailor again” reloads the original saved request for completed/failed web jobs.
- Completed jobs expose a readable Review tab alongside Progress, Preview, and Files.
- Pipeline output now stores `evidence_plan` and `source_facts` in `match_report.json`.
- `resume_tailor/web/review.py` converts coverage, missing requirements, truth violations,
  rejected edits, recommendations, evidence assignments, estimated metrics, and cross-entry
  attributions into a review payload.
- Review checkboxes save to `review_decision.json` only when the report SHA-256 revision still
  matches, preventing stale review decisions from being applied to a changed report.
- The PDF preview adds `#navpanes=0&view=FitH` to reduce nested viewer chrome.
- Tailwind 4.3.3 and daisyUI 5.7.32 are pinned in `package.json` and `package-lock.json`;
  `styles/ui.css` builds `static/ui.css`.

## Railway setup

```mermaid
flowchart LR
  A[GitHub main] --> B[Railway Docker build]
  B --> C[One app replica]
  C --> D[/data volume]
  C --> E[HTTPS domain]
  E --> F[/healthz]
```

1. Create a Railway project and service from the GitHub repository.
2. Mount a persistent volume at `/data`.
3. Generate a password hash:

   ```bash
   .venv/bin/python -m resume_tailor.web.access
   ```

4. Add these variables to the Railway production environment:

   | Variable | Required | Value |
   |---|---:|---|
   | `PUBLIC_ORIGIN` | yes | Exact HTTPS public origin, no trailing slash |
   | `APP_PASSWORD_HASH` | yes | Hash printed by the helper |
   | `GEMINI_API_KEY` | yes for Gemini | Secret Gemini API key |
   | `DEFAULT_MODEL` | recommended | Configured Gemini model |
   | `DATA_DIR` | recommended | `/data` |
   | `MASTER_RESUME_JSON` | first boot if no file | Validated JSON Resume string |

5. Deploy from `main`. Railway supplies `PORT`; do not hardcode it.
6. Confirm `/healthz` returns `{"ready":true}` and `/` redirects to `/login`.
7. Sign in, queue a test job with `no_pdf=true` first if the image's PDF check is not yet
   available, then verify a real PDF job and downloadable artifacts.

The production deployment is live at the URL listed above. The deployed smoke checks returned
`/healthz` → `{"ready":true}`, `/` → `303 /login`, and an authenticated `/api/meta` response
reported `pdf_available: true` with the Gemini tracker ready. No Gemini tailoring request was
submitted during deployment verification.

## Verification evidence

The following checks passed locally:

```text
.venv/bin/python -m pytest -q -m 'not integration'
167 passed, 1 deselected

npm run build:css
Done (Tailwind CSS 4.3.3)

node --check static/app.js
passed

.venv/bin/python scripts/pdf_smoke.py
passed

git diff --check
passed
```

Docker itself was not built locally because Docker Desktop’s daemon was unavailable. The
Dockerfile uses an amd64 Tectonic binary, so verify the first Railway build on an amd64
builder before choosing an ARM-only deployment target.

## Suggested continuation order

1. Run the hosted smoke test: login, logout, expired cookie, wrong origin, `/healthz`, one
   no-PDF job, one PDF job, one restart, one download.
2. Add a retry-interrupted-job action and durable sessions if the app needs stronger restart
   or multi-user guarantees.
3. Add application tracking, master resume versioning, and DOCX export only after the hosted
   review workflow is being used regularly.
