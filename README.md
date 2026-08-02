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

1. Parse the job description.
2. Rank and select work roles and projects.
3. Build a global evidence plan for three selected work destinations with
   `4/3/3` bullet targets.
4. Tailor at most five master-listed skill groups.
5. Rewrite work into allocation-bound STAR bullets.
6. Rewrite exactly two selected projects with two STAR bullets each.
7. Assemble a work-first draft with no professional-summary block.
8. Run one holistic semantic review over the draft and complete evidence plan.
9. Apply only section edits that preserve provenance, STAR fields, and counts.
10. Render and deterministically fit the PDF to one page without trimming the
    required `4/3/3` work or `2×2` project bullets.

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
`google-genai` typed client with structured JSON schemas and a 30-second
request timeout. A Gemini model never falls back to Ollama if configuration is
missing or invalid.

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

Use `--bridge-skills` to run an additional evidence-backed gap analysis. Missing
JD skill keywords may be added only under `Transferable / Adjacent Tools`, never
to work or project claims. Every addition and its supporting master fact IDs are
recorded in `match_report.json`; the default command does not run this stage.

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
