# Resume Generator — Output QA Findings

Source reviewed: `CTG_Vandan_Patel_Resume.pdf`. Each row: the pattern found in the generated output (X), the constraint the system instructions need to enforce (Y), and what a passing bullet/section looks like once fixed (Z). Grouped by priority for tuning order.

## High Priority

| # | Pattern (X) | Required Fix (Y) | Target State (Z) |
|---|---|---|---|
| 1 | Every bullet follows an identical **[strong verb] + [jargon noun-phrase] + [precise stat]** template, producing uniform sentence length and rhythm across an entire role block. | Vary sentence structure per bullet. Never repeat the same verb-then-outcome-clause shape twice in a row within one role. | Bullets in the same role read as distinct pieces of work, not a stat-machine's output — different openers, and at least one bullet per role built around a decision or obstacle instead of a number. |
| 2 | Metrics are stated with false precision and no baseline ("36.5%", "zero tuning required", "82,000+ records") — unfalsifiable, which reads as fabricated even when true. | Require every metric to include or imply its baseline/denominator ("X of Y", "from A to B"). Ban unqualified single-decimal precision with no baseline in the same clause. Ban absolute/self-congratulatory qualifiers ("zero", "no tuning required", "always", "flawless"). | Every number on the page is one the candidate could defend the arithmetic for, live, in an interview. |
| 3 | Technical jargon stacked without a concrete referent ("agentic AI integration across internal manufacturing systems", "SQL dual-identifier engine", "dynamic OpenAPI 3.0 specification generation") — names a category instead of describing what was built. | Require the bullet to state the concrete artifact or action in plain terms before or instead of the abstract label. Flag and rewrite any multi-word technical noun-phrase that isn't a standard, googleable industry term. | A non-expert reader can picture the literal thing that was built or changed. |
| 4 | Verb intensity mismatched to scope — "architected and deployed" applied to 5 read-only endpoints. | Scale verb strength to scope. Reserve architected / spearheaded / orchestrated / pioneered for genuine system-level design decisions; use direct verbs (built, added, wrote, implemented) for narrower work. | Verb choice signals accurate scope, not maximum drama. |

## Medium Priority

| # | Pattern (X) | Required Fix (Y) | Target State (Z) |
|---|---|---|---|
| 5 | Personal-project bullets stack multiple precise counts in one sentence ("44 API routes across 20 relational tables", "82-test suite", "11-model relational schema", "102 automated tests"). | Cap at one quantified claim per bullet. Prefer stating what the number demonstrates (coverage, reliability) over the raw count, unless the count itself is the point. | Numbers appear only where they add real signal, not as decoration. |
| 6 | Skills section lists generic process/soft categories (OOP, SDLC, code reviews, version control) while the named technologies actually used in the experience bullets (e.g. Elixir, Phoenix/LiveView, RabbitMQ, AWS, Docker) are missing or buried in a single passing mention. | Extract every named technology, framework, and tool mentioned anywhere in the source experience/project text and surface it in the skills section verbatim — don't let it live only inside a bullet clause. | Skills section is a keyword-complete inventory matching what the experience section actually describes; nothing differentiating is hidden from keyword/ATS matching. |
| 7 | A role has no metric in its bullets even though a real, source-confirmed metric exists for it, while unverifiable-sounding stats appear elsewhere on the page. | When the input data contains a concrete, sourced number for a role, prioritize surfacing that one over generating a vague description or inventing one for a different role. | The strongest, most defensible numbers in the source material make it onto the page; weak ones aren't invented to fill a gap. |

## Low Priority

| # | Pattern (X) | Required Fix (Y) | Target State (Z) |
|---|---|---|---|
| 8 | Two roles' date ranges overlap with no qualifier, reading as unexplained double-employment. | When two entries' date ranges overlap, auto-append a short qualifier (e.g. "part-time, concurrent"). | Chronology reads clearly on a first skim, no double-take required. |

## Worked examples (for calibrating the rewrite prompt)

**Patterns #1, #3, #4**
- Before: *"Architected and deployed 5 read-only REST API endpoints with dynamic OpenAPI 3.0 specification generation, establishing a proof-of-concept for agentic AI integration across internal manufacturing systems."*
- Target shape: *"Built 5 read-only REST endpoints with auto-generated OpenAPI specs — the first internal API designed for an AI agent to call directly instead of a person using a UI."*

**Pattern #2**
- Before: *"Validated API performance at scale on staging, serving 82,000+ records with a 37 ms worst-case query time and zero tuning required."*
- Target shape: *"Load-tested the endpoint against the full 82,000-record staging dataset; worst-case query time held at 37 ms, within the team's 50 ms SLA."* (baseline/SLA present, self-congratulatory qualifier dropped)

**Pattern #5**
- Before: *"Built a full-stack PWA using React, TypeScript, and FastAPI, exposing 44 API routes across 20 relational tables to enable automated tracking of health metrics and personalized coaching insights."*
- Target shape: *"Built a full-stack PWA (React, TypeScript, FastAPI) that automates health-metric tracking and generates personalized coaching insights from it."* (drop the route/table count — it demonstrates nothing on its own)
