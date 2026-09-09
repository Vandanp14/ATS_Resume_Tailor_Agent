<!-- Source: vandan-llm-toolkit skills/docs-craft/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# Docs Craft

Turn "the docs are bad" into shipped, correct documentation. This skill assumes the user
offers **no structure and no taste** — they say a vague imperative ("fix the README",
"make this repo professional") and this skill owns every decision after that. The judgment
lives in the fixed templates, decision table, hard bans, and verification gate below.
Never fall back on "use your judgment" — follow the procedure and the output is the same
regardless of which model runs it.

Two ideas carry the skill. First, **one document does one job** — Diátaxis (diataxis.fr)
is authoritative: never mix a tutorial, how-to, reference, and explanation in one file.
Second, **a doc is only done when it has been run** — the quickstart is executed verbatim
in a clean environment or the doc is not finished. That gate is the doc equivalent of a
passing test.

## Operating rules (read first, apply always)

1. **Classify before writing.** Run Phase 1 and pick exactly one artifact. If the ask
   implies several ("fix all the docs"), produce separate single-job files.
2. **Never invent structure for a templated artifact.** README, the config-table
   Reference, docstring, ADR, CHANGELOG, and the repo checklist each have a fixed template
   here — fill it; do not reorder its sections or add sections it does not name. The three
   Diátaxis prose genres (tutorial, how-to, explanation) have no section template here;
   for those this skill owns one rule — one job per file (below) — and you follow the
   genre's structure at diataxis.fr.
3. **Copy values verbatim.** Section orders, word budgets, CHANGELOG headings, ADR
   sections, and the badge cap are exact. Do not substitute "similar" choices.
4. **One document, one Diátaxis type.** A file that teaches and also lists every config
   flag has already failed — split it.
5. **Run the quickstart before claiming done** (see the gate). If the environment cannot
   run it, say so and mark it UNVERIFIED — never imply it works.
6. **When in doubt, cut.** Filler intros, vanity badges, and docstrings that echo the
   signature are removed on sight. Fewer true words beat a complete-looking page.

## Phase 1 — Classify the ask → pick the artifact

Map what the user said (or what the repo is missing) to one artifact and its template.

| The ask / the gap | Artifact | Template lives in |
|---|---|---|
| "fix the README", "make it legit", orient a first-time visitor | **README** | this file + [readme-and-repo.md](references/readme-and-repo.md) |
| "teach a newcomer", "getting-started lesson", learn by doing | **Tutorial** (learning-oriented) | no template here — apply the boundary rule (below), structure per diataxis.fr |
| "how do I do X", a recipe for someone who knows the basics | **How-to guide** (task-oriented) | no template here — apply the boundary rule (below), structure per diataxis.fr |
| "document config / options", material for lookup | **Reference** (information-oriented) | config table in readme-and-repo.md; broader API/CLI reference → structure per diataxis.fr |
| "explain why", architecture, background, design rationale | **Explanation** (understanding-oriented) | no template here — apply the boundary rule (below), structure per diataxis.fr |
| "why did we choose X", "record this decision" | **ADR** | [docstrings-and-adrs.md](references/docstrings-and-adrs.md) |
| "track changes", "add a changelog", release notes | **CHANGELOG** | [readme-and-repo.md](references/readme-and-repo.md) |
| "document this function / class / module" | **Docstring** | [docstrings-and-adrs.md](references/docstrings-and-adrs.md) |
| "make the repo professional", project files missing | **Repo professionalization checklist** | [readme-and-repo.md](references/readme-and-repo.md) |

### The four Diátaxis types (never mix them in one document)

| Type | Serves | Use when the reader… |
|---|---|---|
| **Tutorial** | learning by doing | is a newcomer who needs a guaranteed first success; you hold their hand step by step |
| **How-to guide** | a specific goal | already knows the basics and wants to accomplish one real task |
| **Reference** | fast, accurate lookup | is working and needs a dry, exhaustive description of the machinery |
| **Explanation** | understanding | is reading away from the code to grasp *why* it is built this way |

Positioned on two axes: study ↔ work and practice ↔ theory. Tutorial = study+practice,
how-to = work+practice, reference = work+theory, explanation = study+theory. If a draft
drifts across a boundary, split the file.

## Phase 2 — Draft against the fixed template

### The README formula (fixed section order + per-section budgets)

Every README uses exactly this order; budgets count prose only. The full copy-paste
skeleton is in [readme-and-repo.md](references/readme-and-repo.md).

| # | Section | Content | Budget |
|---|---|---|---|
| 1 | Title + one-liner | what it is **and who it's for**, one sentence | ≤ 25 words |
| 2 | Badges | max 3, each pointing to live data; skip entirely if none qualify | — |
| 3 | Quickstart | copy-paste install + one minimal usage example that **runs verbatim** | ≤ 80 words |
| 4 | Usage / examples | 2–3 real examples that go beyond the quickstart | ≤ 150 words |
| 5 | Configuration | table: option · type · default · description | table |
| 6 | Troubleshooting | table: symptom → fix | ≤ 120 words |
| 7 | Contributing + License | one-line pointer to each | ≤ 30 words |

For a docstring, ADR, or CHANGELOG, open the matching reference **just before** you write
that artifact — not upfront — and fill its template.

## Phase 3 — Verify (the gate)

A doc ships only after this passes. Do it, do not assume it.

- **Execute the quickstart verbatim in a clean environment** — a fresh clone, container,
  or virtualenv with nothing preinstalled. Copy each command and code block exactly and
  run it. It must produce the result the README promises.
- If a command fails, is out of order, or assumes hidden state, **fix the doc** and rerun
  from the top. A quickstart that has never been run is a guess, not documentation.
- If this environment cannot run it, say so and label the quickstart UNVERIFIED.

Final checklist: one Diátaxis type per file · README follows the seven-section order ·
badges ≤ 3 and all live · config is a table · every ADR fits one page · CHANGELOG uses the
six keep-a-changelog headings · no docstring restates its signature · quickstart run clean.

## Hard bans

- **No badge walls.** More than 3 badges, or any badge without live data —
  "Made with love", "PRs welcome", "awesome", "100% pure X" — is deleted.
- **No "Welcome to X" / "This project is a…" filler intros.** Line one states what it is
  and who it's for.
- **No docs that restate code line-by-line.** A docstring or comment that only re-says the
  signature is noise; delete it (see the leanness rule in the docstring reference).
- **No quickstart that has never been run verbatim in a clean environment.**
- **No mixing Diátaxis types in one document.**
- **No CHANGELOG scraped from `git log` or written only at release time.** Entries are
  authored in human language at merge time.
