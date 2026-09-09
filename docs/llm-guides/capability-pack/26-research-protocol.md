# 26 — Research Protocol

Rule: **one query is not research.** Weak models fire a single search, take the top
hit, present an undated blog's claim as settled fact, and dump chronological notes. This
guide replaces all four habits with a procedure. Three parts: **fan out** (search),
**trust** (grade sources), **deliver** (write it up).

## Part 1 — Fan out

**Never search with only one query.** Before searching, decompose the question into
**3-5 distinct angles**. Write them down first, then search each:

1. **Concept** — the plain-language idea ("how does X pagination work").
2. **Exact string** — verbatim error text, function name, or config key in quotes.
3. **Official-docs-scoped** — add `site:` for the spec/vendor/repo docs.
4. **Version/changelog** — the release notes or migration guide for the current version.
5. **Competing-viewpoint** — "X vs", "X problems", the GitHub issue or forum thread.

**Reformulation ladder — apply when a result set is thin, never re-run the same words:**

1. Broaden — drop the most specific term.
2. Narrow — add a version number, platform, or exact identifier.
3. Swap — synonyms; switch concept↔symptom (error string ↔ what it means).
4. Filter — add `site:`, `filetype:`, or a date qualifier.
5. Re-angle — search the adjacent artifact (changelog, issue tracker, spec section).

**Breadth before depth:** scan several results before committing to read one fully.

**STOP criteria — stop at the FIRST that hits (do not keep searching, do not quit early):**
- **Saturation:** the last 2 new queries surfaced no new primary facts.
- **Primary hit:** a primary source answers the question definitively.
- **Budget:** the tool-call or time box is spent — report what you have, flag the gap.

## Part 2 — Trust

Apply to **every** claim before you rely on it.

**Date every source.** No date, or older than the subject's last major version →
downgrade or discard. An undated 2019 article does not describe a 2025 API.

**Primary-source ladder — prefer the highest rung available:**

1. Spec / source code / official docs
2. Maintainer statements (release notes, core-team issue comments)
3. Reputable secondary (established tech press, well-cited write-ups)
4. Random blog / forum answer / another LLM's output

**Triangulation:** any claim that drives a decision needs **2 independent sources OR 1
primary**. Single-source, non-primary claims get flagged, never stated flat.

**Confidence tags — attach one to every conclusion:**

| Tag | Means | Earned by |
|---|---|---|
| CONFIRMED | Verified fact | Primary source, or 2 independent sources agree |
| INFERRED | Reasoned from evidence, not stated outright | Logic over confirmed facts |
| SPECULATION | Unverified guess | No corroboration yet |

**Never write inference or speculation in the same flat declarative voice as a fact.**
The reader must be able to tell what is load-bearing.

**Conflict resolution — when sources disagree, surface it, do not silently pick one:**
1. State both claims and their sources.
2. Weight by recency + authority + primary-ness.
3. State which won and why, in one sentence.

*Example:* Blog (2021) says the flag defaults on; official docs (v4, 2025) say off. Docs
win — primary and newer. Conclusion: defaults off [CONFIRMED].

## Part 3 — Deliver

**Recommendations are not findings. Never blend them.** Output has three separated
sections (full fill-in contract: `templates/research-brief.md`):

- **FINDINGS** — top-N ranked by impact (default **5-7**; cap forces prioritization).
  Each item: `claim | evidence (URL+date or file:line) | confidence tag | applies-to-us`.
- **OPEN QUESTIONS** — what is unresolved and why.
- **RECOMMENDATIONS** — physically separate, labeled as your judgment, each tied to a
  finding ID.

**Hard bans:**
- No uncited findings. Every claim carries a URL+date or file:line.
- No recommendation inside the findings table.
- No unranked chronological notes dump ("I looked at X, then Y…").
- No untagged conclusion.

## Output contract

Deliverable is done only when: every finding cites a dated source · every conclusion
carries CONFIRMED/INFERRED/SPECULATION · decision-bearing claims are triangulated ·
findings are ranked and bounded · recommendations sit in their own labeled section ·
open questions are listed.
