# ATS Resume Tailor Agent

Takes one hand-maintained **master resume** (JSON Resume format) plus a **job
description** (plain text file) and produces a tailored, ATS-optimized resume:
validated JSON, Jake's-Resume-style LaTeX, and a one-page PDF — along with a
JD-match coverage report and bounded auto-iteration to close keyword gaps.

Primary workflow: drop any number of `.txt` job descriptions into the `jds/`
folder, run one command, and get a tailored one-page PDF per JD in
`output/<jd-name>/`.

Target model is `gemini-3.1-flash-lite` (a weak, cheap model) — the whole
pipeline is built for weak-model reliability: schema-constrained decoding
against Pydantic models, retry-on-invalid-output, and worked examples in every
prompt template.

## Content policy — what tailoring will and will not do

This tool rewrites your resume aggressively, but it does not lie. The policy
is enforced in every prompt template and cross-checked by a scorer pass.

**Allowed:**

- Aggressive rewriting of bullets into the JD's language and keyword mirroring
- Reordering and selecting the most relevant projects, bullets, and skills
- Inferring or generalizing *adjacent* skills from genuinely present
  experience (e.g. "used React" → "frontend frameworks including the React
  ecosystem")

**Forbidden (the truth floor):**

- Inventing employers, job titles, employment dates, degrees, certifications,
  projects, or metrics/numbers that are not in your master resume

Every fact in the tailored output must be traceable to the master resume. The
scorer flags any tailored content without a master-resume source as a truth
violation; violations force a re-run of the offending section, and if they
persist after the pass limit, **the run fails loudly instead of rendering a
fabricated resume**. Honest limitation: the truth check is itself an LLM call,
so it is a strong guardrail, not a mathematical proof — skim the output before
you send it anywhere.

## Architecture

```
master.json + jd.txt
   │
   ▼
[1] JD parser ── 1 LLM call ──► JDProfile (Pydantic)
   │
   ▼
[2] Per-section tailors (1 LLM call each, independent):
      summary • skills • work • projects   (education = passthrough, no LLM)
   │
   ▼
[3] Assembler ──► tailored JSONResume (Pydantic-validated)
   │
   ▼
[4] Scorer ── 1 LLM call ──► MatchReport (coverage %, missing must-haves,
   │                          weak sections, truth-floor violations)
   ▼
[5] Iterate: coverage < threshold (default 80%) → re-run ONLY weak sections
    with gap feedback appended. Max 2 total passes. Truth violations always
    trigger a re-run of the offending section with the violation named.
   │
   ▼
[6] Renderer: JSONResume → Jake's-style LaTeX (Jinja-filled .tex) → PDF via tectonic
```

Education is never sent to the LLM — it is copied verbatim from the master
(there is nothing to tailor, and it eliminates a fabrication surface). Worst
case per JD is 11 LLM calls: 1 (JD) + 4 (sections) + 1 (score) + 4
(worst-case re-runs) + 1 (re-score).

## Setup

```bash
cd ATS_Resume_Tailor_Agent
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# API key: copy the example env and fill in your Gemini key
cp .env.example .env
# edit .env → set GEMINI_API_KEY=...   (never commit .env)

# PDF compilation (recommended): tectonic is a single self-contained LaTeX
# engine that auto-downloads the packages it needs on first run
brew install tectonic          # macOS
# other platforms: https://tectonic-typesetting.github.io/install.html
```

No tectonic? Everything still works with `--no-pdf`: you get `tailored.json`
and `resume.tex` (compile the `.tex` anywhere, e.g. Overleaf), but the
one-page auto-fit is skipped (it needs a real compile to count pages) and a
warning is printed.

## Usage

### Batch drop-folder mode (the primary workflow)

1. Drop job descriptions as plain-text files into `jds/` — one JD per file,
   any names:

   ```
   jds/
   ├── stripe-backend.txt
   ├── nimbus-platform.txt
   └── acme-fullstack.txt
   ```

2. Run once:

   ```bash
   .venv/bin/python tailor.py batch
   ```

3. Collect results — one directory per JD, named by the file stem:

   ```
   output/
   ├── stripe-backend/
   │   ├── tailored.json      # tailored resume, JSON Resume format
   │   ├── resume.tex         # Jake's-style LaTeX source
   │   ├── resume.pdf         # one-page PDF
   │   ├── match_report.json  # coverage %, missing must-haves, notes
   │   └── .done              # completion marker (enables skip-on-rerun)
   ├── nimbus-platform/ ...
   └── acme-fullstack/ ...
   ```

JDs are processed **sequentially, never in parallel** — deliberate, to respect
Gemini rate limits.

**Re-running is safe and idempotent:** any JD directory containing a `.done`
marker is skipped, so a re-run only picks up new or unfinished JDs. A run
killed mid-JD leaves no `.done` marker, so that JD restarts cleanly next time.
Use `--force` to re-process everything.

**Quota exhaustion:** transient 429s are absorbed by provider-level
exponential backoff. If your Gemini quota is *truly* exhausted (backoff
retries run out), the batch runner stops cleanly, prints exactly which JDs
completed and which remain, and exits with code 75 (`EX_TEMPFAIL`):

> Gemini quota exhausted — wait and re-run the same command; completed JDs
> will be skipped.

That is the whole recovery procedure: wait, re-run the same command.

### Single-JD mode

```bash
.venv/bin/python tailor.py master.json jd.txt -o out/
```

Writes `out/tailored.json`, `out/resume.tex`, `out/resume.pdf`, and
`out/match_report.json`.

### CLI reference

Single-run flags (work in both modes):

| Flag | Default | Meaning |
|---|---|---|
| `-o OUT_DIR` | — | Output directory (single-JD mode) |
| `--threshold N` | `80` | Minimum JD coverage %; below it, weak sections are re-tailored with gap feedback |
| `--max-passes N` | `2` | Total tailoring passes cap (bounded iteration — no runaway loops) |
| `--no-pdf` | off | Skip PDF compilation (no tectonic needed); also skips the one-page fit loop, with a warning |
| `--ats-score` | off | Additionally run the sibling hiring-agent's evaluator on the tailored resume and print its category scores (extra LLM calls; needs the hiring-agent checkout, see Bootstrap section) |
| `--call-interval SECONDS` | `4.5` | Free-tier pacer: minimum spacing between consecutive LLM calls. 4.5 s guarantees ≤ 14 requests/min against the 15 RPM Gemini free-tier limit, so a 10-JD batch runs ~10–12 min with zero quota errors by construction. On a paid tier, set `0` to disable |

Batch-only flags:

| Flag | Default | Meaning |
|---|---|---|
| `--jd-dir DIR` | `jds/` | Folder scanned for `*.txt` job descriptions |
| `--out-dir DIR` | `output/` | Where per-JD output directories are written |
| `--delay-seconds N` | `0` | Extra pause between JDs (proactive rate-limit headroom, on top of `--call-interval`) |
| `--force` | off | Ignore `.done` markers and re-process every JD |

## ATS-rubric optimization

Tailoring is optimized against a known ATS evaluation rubric (the sibling
hiring-agent's evaluator: open-source ≤ 35, self-projects ≤ 30, production
experience ≤ 25, technical skills ≤ 10, bonus ≤ 20; deductions for
tutorial-grade projects, missing links, and low-effort OSS). Two mechanisms:

1. **Baked in (always on):** the shared tailoring rules push rubric-relevant
   *selection and emphasis* — surface contributions to other people's
   open-source projects prominently; prefer complex/impactful projects over
   tutorial-grade ones; every selected project keeps its GitHub/live link
   from the master; surface startup/founder/early-stage and production
   experience; include portfolio and LinkedIn URLs when present. All of this
   stays inside the truth floor — the rubric shapes what gets picked and
   highlighted, never what gets invented.
2. **Live check (opt-in):** `--ats-score` runs the actual hiring-agent
   evaluator on the tailored resume and prints its category scores next to
   the JD match report. Off by default because it costs extra LLM calls.

## One-page auto-fit

The final PDF is exactly one page, automatically:

- Every tailored item (work bullet, project, skill group) carries a JD-driven
  relevance score assigned at generation time. Nothing is pre-truncated — the
  whole master is considered first.
- A deterministic trim loop (no extra LLM calls) then renders, counts pages,
  and while the PDF exceeds one page drops the single lowest-relevance item
  per iteration, in fixed priority order: (a) work bullets beyond 2 per
  position, (b) whole projects beyond 2, (c) skill groups, (d) the oldest
  low-relevance position's remaining bullets down to 1, (e) the whole
  lowest-relevance position. Ties break by recency (older goes first).
- Education and the header/contact block are never trimmed.
- Hard cap of 25 trim iterations, then the run fails loudly rather than
  shipping a two-page "one-pager".
- Requires `tectonic` (counting pages needs a real compile). With `--no-pdf`
  the fit loop is skipped and a warning is printed.

## Maintaining `master.json`

Your master resume is the single source of truth for every tailored output.
It uses the [JSON Resume](https://jsonresume.org/schema/) format — see
`examples/master.example.json` for a complete, realistic example of every
section the pipeline uses (`basics`, `work`, `education`, `skills`,
`projects`).

Guidelines that make tailoring work well:

- **Put everything in.** The master is not a resume — it is a superset. Old
  roles, side projects, niche skills: include them all. The pipeline selects
  and trims per JD; a fact it has never seen can never be surfaced.
- **Keep every link.** GitHub links on every project, live-demo URLs, your
  portfolio and LinkedIn in `basics.profiles`/`basics.url`. Selected projects
  always carry their links into the output, and links score rubric points.
- **Write bullets with real numbers** (latency, throughput, users, time
  saved) — but only true ones. The tailor may rephrase your metrics; it is
  forbidden from inventing new ones, so un-quantified master bullets stay
  un-quantified.
- **Name open-source contributions explicitly** ("3 merged PRs to Apache
  Airflow, including …"), and name programs precisely — GSoC and
  "Girl Script Summer of Code" are different things and are never conflated.
- **Don't pre-trim for length.** One-page fitting is the renderer's job, done
  per-JD by relevance.
- After editing, sanity-check that it still parses:

  ```bash
  .venv/bin/python -c "import json, models; models.JSONResume.model_validate(json.load(open('master.json'))); print('ok')"
  ```

## Bootstrapping `master.json` from an existing PDF

If you have a resume PDF but no `master.json` yet, `bootstrap_master.py`
extracts one using the sibling **hiring-agent** project's LLM extraction
pipeline (one call per section, ~6 total). It is a one-time convenience, not
part of the tailoring pipeline.

```bash
# Simplest, always-correct invocation: use the hiring-agent's own venv python
~/Desktop/hackerank_ats/hiring-agent/.venv/bin/python \
    bootstrap_master.py resume.pdf -o master.json

# Non-default checkout location:
... bootstrap_master.py resume.pdf -o master.json \
    --hiring-agent-path ~/src/hiring-agent
```

How it works and what it needs:

- It inserts the hiring-agent checkout onto `sys.path` and calls its
  `PDFHandler.extract_json_from_pdf` — no code is copied.
- **The hiring-agent's dependencies must be importable** by whichever Python
  runs the script (`pymupdf`, `pymupdf4llm`, `google-generativeai`, …). The
  documented, simplest path is to run the script with the hiring-agent's venv
  python, as above. This repo's `.venv` also works once
  `pip install -r requirements.txt` has been run here.
- The hiring-agent reads its model and `GEMINI_API_KEY` from **its own
  `.env`** — make sure that file has a key, otherwise it silently falls back
  to a local Ollama server.
- If extraction fails (e.g. a scanned/image-only PDF), the script prints the
  failing section and exits nonzero — nothing is written.

Then **review the output by hand**: LLM extraction is good but not perfect,
and the truth floor is only as truthful as your master. Fix anything wrong,
then maintain `master.json` directly from that point on (see the section
above).

## Repository layout

```
tailor.py               # orchestrator CLI (single-JD + batch modes)
render.py               # JSONResume → LaTeX → PDF, one-page fit loop
bootstrap_master.py     # one-time PDF → master.json (via hiring-agent)
models.py               # JSON Resume + pipeline Pydantic models
llm_utils.py            # retry/validation plumbing around the LLM provider
prompt.py               # model/provider configuration (.env)
prompts/templates/      # Jinja prompt templates (shared tailoring rules)
templates/latex/        # Jake's-Resume-style LaTeX Jinja template
jds/                    # ← drop-folder: put your *.txt job descriptions here
examples/               # example master resume + example JD
tests/                  # unit tests (mocked) + live integration tests
```

## Tests

```bash
.venv/bin/pytest -m "not integration" -q    # unit tests, fully mocked, no network
.venv/bin/pytest -m integration -q          # live gemini-3.1-flash-lite calls (needs .env)
```

## Non-goals (v1)

No JD URL scraping (paste text into a file), one LaTeX template only (Jake's
style), no cover letters or LinkedIn artifacts, no caching layer.
