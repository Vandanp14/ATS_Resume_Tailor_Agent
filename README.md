# ATS Resume Tailor Agent

Builds a job-specific, one-page resume from a hand-maintained JSON Resume
master. The primary command is:

```bash
.venv/bin/python tailor.py batch
```

Each `jds/*.txt` file produces an output directory containing:

```text
output/<jd-name>/
├── tailored.json
├── match_report.json
├── resume.tex
├── resume.pdf
└── .done
```

## Pipeline

The orchestration is intentionally linear:

1. Parse the job description; drop any weighted keyword the posting never
   states.
2. Map requirement coverage. Code matches every JD requirement literally
   (with true-synonym aliases such as Postgres/PostgreSQL) against the master:
   `direct`, or `missing`. For missing technical requirements, one model call
   finds the closest real evidence (`proxy`): a missing Elixir maps to the
   Clojure project, a missing Kafka maps to RabbitMQ work. Proxy terms must
   appear in the cited facts.
3. Rank work roles and projects. The final set is picked in code: model
   relevance, a bonus for titles matching the target role, and the weighted
   requirements each entry newly covers, directly or through proxy evidence.
4. Build a global evidence plan for three selected work destinations with
   `4/3/3` bullet targets. The highest-priority gap proxies must reach a
   bullet (cross-entry, e.g. Clojure project work under a software role) or a
   selected project, and each assignment carries the exact JD `target_terms`
   its own facts support.
5. Tailor at most five master-listed skill groups.
6. Rewrite work into allocation-bound STAR bullets. Bullets may never name a
   missing JD technology, never justify a gap ("mirroring ... architectures"),
   and, on the first attempt, never name a JD technology their own facts lack.
7. Rewrite exactly two selected projects with two STAR bullets each.
8. Assemble a work-first draft with no professional-summary block.
9. Run one holistic semantic review over the draft, the complete evidence plan,
   and code-computed keyword gaps.
10. Apply only section edits that preserve provenance, STAR fields, and counts.
11. Render and deterministically fit the PDF to one page without trimming the
    required `4/3/3` work or `2×2` project bullets.

`match_report.json` records the requirement map, each proxy, measured keyword
coverage (`computed_coverage_pct` over all requirements, `supported_coverage_pct`
over requirements the master states), and placement findings.
`scripts/coverage_report.py` re-measures every output without LLM calls, for
regression checks after prompt changes.

The model never returns contact data, education, employers, titles, dates,
project names, URLs, or project technology lists. `pipeline_core.py` copies
those fields directly from `master.json` and validates them before rendering.

Code rejects deterministic contract violations: malformed schemas; incorrect
selection or bullet counts; unknown, missing, duplicate, or unallocated source
IDs; incomplete STAR fields; unplanned impact claims; non-master skills; and
changed protected fields. The evidence planner may intentionally allocate a
fact from any work role, project, or skill group to a selected work destination.
It may also declare a plausible exact point-estimate impact. Cross-entry
attributions and inferred metrics remain traceable in `match_report.json`. The
one holistic review owns semantic plausibility, contradiction, duplication,
coverage, and readability. Only an unresolved truth violation blocks output
publication; reviewer section edits that fail validation are skipped, logged in
`rejected_section_edits`, and surfaced as a terminal warning while the run
completes. Skills edits may include JD must-have and nice-to-have keywords the
master lacks, with duplicate keywords dropped. Findings corrected by a valid
reviewer section replacement are retained under `resolved_truth_violations` in
the match report and do not block publication.

All bullet writing (work, projects, and reviewer section edits) follows the
bullet guide: a categorized action-verb dictionary, an ownership-calibration
ladder, and the final bullet test. A warn-only scanner surfaces weak openers
("responsible for", "worked on", "helped with", "participated in"), opener
restricted verbs, and three or more bullets opening with the same verb as
terminal warnings; style findings never block a run.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Set `GEMINI_API_KEY` and `DEFAULT_MODEL` in `.env`. Gemini uses the supported
`google-genai` typed client with structured JSON schemas and a
`GEMINI_TIMEOUT_MS` request timeout (default 120 s). A Gemini model never falls
back to Ollama if configuration is missing or invalid.

Model chains: reasoning-heavy stages (requirement mapping, selection, evidence
planning, holistic review) try `PLANNING_MODELS` first
(default `gemini-3.8-flash,gemini-3.5-flash`), then `DEFAULT_MODEL`, then
`FALLBACK_MODELS` (default `gemini-3.5-flash-lite`); other stages start at
`DEFAULT_MODEL`. A model that answers 503/500/timeout is skipped for 90 s; a
retired (404) or quota-exhausted (429) model is skipped for the rest of the
run. Auth errors (401/403) stop immediately. When every model in a stage's
chain fails, tailoring stops and the error lists exactly what the Gemini API
returned for each model; a batch stops too instead of failing every remaining
job the same way.

Install Tectonic for PDF generation:

```bash
brew install tectonic
```

Use `--no-pdf` when only JSON and LaTeX output are needed.

## Commands

Batch mode:

```bash
.venv/bin/python tailor.py batch
```

Useful batch options:

```text
--master PATH          master JSON Resume (default: master.json)
--jd-dir PATH          job descriptions (default: jds)
--out-dir PATH         output root (default: output)
--model NAME           configured model name
--call-interval SEC    minimum spacing between physical model requests
--no-pdf               skip compilation and one-page fitting
--force                rerun completed jobs
--bridge-skills        add up to four JD-grounded skills in a labeled transferable group
--research-company     when the JD is thin, research the company's stack and hiring
                        signals via grounded Gemini web search (Gemini only)
--verbose              show retries, pacing waits, and fit decisions
--quiet                show only failures and the final batch result
```

Single-JD mode:

```bash
.venv/bin/python tailor.py master.json jds/intuit.txt -o output/intuit
```

JDs run sequentially. A successful `.done` marker contains JSON recording
whether a PDF was produced. A text-only legacy marker, or a marker from a
`--no-pdf` run, does not suppress a later normal PDF run. Failed reruns clear
stale final artifacts first and write `diagnostic_report.json` with the stage,
attempt count, selected source IDs, parsed response, and exact validation error.

Batch exit codes are `0` for success, `1` if any JD failed, and `75` after
exhausted Gemini quota so the same command can be retried later.

Interactive terminals show a live job-and-stage display with elapsed time.
Redirected output and CI automatically receive stable plain-text lines without
ANSI control sequences. SDK request chatter is hidden at the default verbosity;
warnings and errors remain visible.

Use `--bridge-skills` to also list up to four missing JD tools in a labeled
`Transferable / Adjacent Tools` skills group, taken from the requirement map's
validated proxies. They never appear in work or project claims. Every addition
and its supporting master fact IDs are recorded in `match_report.json`. Gap
mapping itself always runs; without the flag it only steers selection and
bullets toward the closest real evidence.

Use `--research-company` on job descriptions that are heavy on responsibilities
and culture but light on explicit tech-stack keywords. After `jd_parse`, the
pipeline checks the extracted must-have/nice-to-have/keyword count against a
threshold; only a thin JD triggers two grounded Gemini web-search calls (company
tech stack, then hiring signals). Research output only ever shapes which
already-true work/project evidence is selected and how existing bullets are
worded — it can never add a skill, keyword, or technology claim that isn't
already in the master resume. Requires an active Gemini provider; it is a no-op
on Ollama and on an already-detailed JD, and adds at most two extra calls to a
job's Gemini usage.

The executable `tailor.py` is a compatibility shim. Application code lives in
the `resume_tailor` package: `cli` owns arguments and logging, `batch` owns job
coordination, `pipeline` and `stages` own orchestration, `progress` owns output,
and the lower-level evidence, assembly, provider, and rendering modules remain
independent of the terminal UI.

## Source data

`master.json` follows JSON Resume. Keep it as a factual superset rather than a
finished one-page resume:

- Put all verified roles, projects, skills, technologies, dates, and links in
  the master.
- Give work and projects concrete evidence bullets with enough context to build
  situation/task, action, and result fields.
- Keep verified metrics in the master. When evidence lacks one, the planner may
  add a conservative inferred point estimate; the report records its source
  facts, basis, destination, and final claim.
- Education and identity fields are never tailored.

See `examples/master.example.json` for the supported shape.

## Verification

Run the fast suite:

```bash
.venv/bin/python -m pytest -q -m "not integration"
```

Run all tests, including a real Tectonic compile when installed:

```bash
.venv/bin/python -m pytest -q
```

For a production check, run the normal batch command and inspect
`tailored.json`, `match_report.json`, `resume.tex`, the PDF page count, and
extracted PDF text before using the resume.

## Railway deployment

The hosted web app uses the Dockerfile, a Railway volume, and one replica. The image
includes Python, Tectonic, and the CSS build; personal resume data stays outside Git.

1. Create a Railway project and service from this repository. Railway will use
   `railway.toml` and the Dockerfile automatically.
2. Add a volume mounted at `/data`.
3. Create a password hash locally:

   ```bash
   .venv/bin/python -m resume_tailor.web.access
   ```

4. Add these Railway variables:

   | Variable | Value |
   |---|---|
   | `PUBLIC_ORIGIN` | Exact HTTPS Railway/custom-domain origin, without a trailing slash |
   | `APP_PASSWORD_HASH` | Value printed by the password-hash command |
   | `GEMINI_API_KEY` | Your Gemini API key |
   | `DEFAULT_MODEL` | Configured Gemini model name |
   | `MASTER_RESUME_JSON` | Validated JSON Resume, if `master.json` is not already on the volume |
   | `DATA_DIR` | `/data` |

Railway provides `PORT`; the server binds to `0.0.0.0` automatically in a Railway
environment. The deployment health check is `/healthz`. Keep one replica because the
queue worker and in-memory session registry are single-process. Back up `/data` before
upgrades and use Railway’s previous deployment to roll back.
