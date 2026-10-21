# College mode: design

Date: 2026-10-21
Status: draft, pending approval
Depends on: `2026-10-21-resume-flow-and-skill-check-design.md` (literal JD
terms, skill check, current-role-first, model routing). Build that first.

## Why

The user will start applying to college and university **staff** tech roles:
web developer, IT, software, analyst, and related. These are not faculty jobs,
so they use a resume, not an academic CV. Screening differs from big
companies: HR checks each posted **Minimum Qualification** line, often
literally, and only applicants who meet all of them reach the search committee
(UC Davis HR: "only those applicants who meet minimum qualifications as
outlined in the job posting … are eligible for consideration"; Brown HR tells
screeners to judge resume content, not style). Two-page resumes are normal for
computing roles.

The current pipeline cannot serve this. Example: the saved SUU UX/UI Developer
posting (`jds/uiux_developer_utah_university.txt`) lists minimum
qualifications such as "Two years recent web development/programming
experience", "Strong understanding of Section 508/ADA Accessibility compliance
and remediation", "Requires ability to work cordially with other University
personnel", and "Ability to work on concurrent projects". The pipeline rejects
non-technical requirements (`non_skill_requirement`, `pipeline_core.py:1345`,
`:1459`), so lines like these are never targeted. It also forces one page,
three jobs, and two projects, which drops the user's Help Desk and Project
Analyst roles, strong evidence for IT and analyst postings.

The user is a first-generation applicant and has no prior picture of what a
college resume should look like; the norms below are the designer's
recommendation, approved by the user.

## Scope

Resume only. Cover letters and references stay manual (the user iterates on
cover letters elsewhere).

## Goals

1. A per-run **College posting** switch, set manually by the user. No
   auto-detection.
2. Minimum and preferred qualifications are parsed as **line items** (including
   experience-length, degree, and interpersonal lines), each matched to
   evidence in the master resume.
3. A code check confirms each minimum-qualification line has visible proof on
   the page. Lines with no supporting evidence are **flagged** in the run
   report and UI; the system does not stretch wording to fake a match. The user
   decides whether to apply.
4. Up to **two pages**, with more roles and projects than the big-company
   shape.
5. A short **summary** at the top naming the posting's title and the user's
   relevant years of experience.

## Non-goals

- Cover letters, references, transcripts.
- Faculty / academic CV format.
- Auto-detecting college postings.
- Changing big-company mode. With the switch off, output must be identical to
  what the first project produces.

## Anti-goals

- Wording that claims a qualification the master resume does not support
  (e.g. turning 2 years into "3+ years").
- A two-page resume padded with weak material just to fill space.
- Breaking checkpoint resume, privacy redaction, or the bullet-review /
  fit-recovery pauses.

## Constraints

- Local-only app.
- Same LaTeX/Jinja template family (`templates/latex/jakes.tex.jinja`) with
  conditional sections; PDF text must stay cleanly extractable (verified with
  pdfminer and MuPDF for the current template).
- Gemini free tier; follows the model routing from the first project. College
  mode may add at most one AI call per run (the summary), and only when the
  switch is on.

## Design

### 1. Switch

A "College posting" toggle on the new-job form (web) and a CLI flag. It is part
of the run options, so it is saved with the job, included in the checkpoint
fingerprint, and shown on the job page.

### 2. Qualification line items

When the switch is on, the JD parse additionally returns:

- `minimum_qualifications`: list of line items, each with the verbatim posting
  text, a type (`experience_length`, `degree`, `technical`, `interpersonal`,
  `other`), and for `experience_length` the number of years and the domain
  ("web development/programming").
- `preferred_qualifications`: same shape.

Technical terms inside these lines still flow into the literal-keyword and
skill-check machinery from the first project.

Each line is mapped to evidence:

- `experience_length`: computed in code from master work dates (month/year)
  for roles whose content matches the domain. Designer's calls:
  - Months are the union of matching roles' date ranges, so overlaps count
    once. "Present" counts up to the run date.
  - Internships and student jobs count at full calendar length (HR may
    prorate part-time work; that is the user's risk to judge, consistent with
    flag-not-block).
  - "Recent" is ignored unless the posting gives a number of years.
  - For "web development/programming", Facilities (2024-04 to 2026-04) and
    Fanatics (2026-06 to Present) both match, so as of 2026-10 that is about
    28 months.
  - Shown on the page as whole years with "+" when there are extra months
    ("2+ years"), never rounded up.
  - When a posting has no experience-length line, the summary uses the union
    of all technical roles. When it has several with different domains, the
    summary uses the one tied to the posting's title.
- **Education-for-experience substitution** (user request, verified):
  college and public employers commonly count 30 semester credit hours (45
  quarter hours) as one year of experience (Texas A&M-Corpus Christi, Baylor,
  NJ Civil Service, NC OSHR). At that ratio 120 credits = 4 years. Rules vary
  by employer: some require the coursework to be related to the field, and
  some forbid counting education already used to meet a degree requirement.
  Therefore:
  - Apply substitution in the coverage check only when the posting allows it
    ("or equivalent combination of education and experience", "education may
    substitute for experience", or similar). Store the matched phrase.
  - Count only credits completed to date (not expected), at 30 semester / 45
    quarter credits per year, added to the computed work years. If the same
    posting has a degree requirement that the education is being used for,
    do not also count those credits toward experience; flag the line as
    "covered only with substitution" so the user decides.
  - The master resume needs a credits-completed field on the education entry
    (and its credit system, semester or quarter). If missing, no substitution
    is applied.
  - The resume text and summary state real work experience only. Substitution
    affects whether a line is flagged, not what the page claims; the page
    shows the degree, expected date, and credits completed so HR can apply
    its own rule.
- `degree`: matched against `education`, including expected graduation dates.
  Postings that say "imminent completion considered" accept an expected date.
- `technical`: existing requirement-map path.
- `interpersonal` / `other`: matched by the model to source facts (e.g.
  "Collaborated directly with field staff…" for working with university
  personnel). Non-skill requirements are allowed in this mode instead of
  rejected. Coverage is by meaning; the bullet keeps its source wording and
  may echo the posting's phrasing ("university personnel") where the fact
  supports it.
- **Standards and compliance terms** (designer's call). The master resume has
  "accessibility-focused interfaces" but never names Section 508, ADA, or
  WCAG. In college mode the skill-check chips from the first project also
  include standards/compliance terms named in qualification lines (Section
  508, ADA, WCAG 2.1 AA, FERPA, etc.), not only tools. A confirmed term is a
  fact like any confirmed skill: usable in bullets and passing truth checks.
  Unconfirmed, the line is flagged.

### 3. Coverage check and flags

After assembly, code checks each minimum-qualification line:

- **Covered**: the mapped evidence appears on the page (a bullet, the summary,
  skills, or education).
- **Unsupported**: no source fact supports it. Reported as a flag with the
  verbatim line and the reason (e.g. "posting asks 3 years; master shows 2
  years 0 months of web development"). Never rewritten to fake a match.
- **Supported but not on page**: evidence exists but was cut. The page budget
  should prevent this; if it happens, report it as a warning.

What "covered" means (designer's call): the line's mapped source fact was
selected and rendered (provenance check), **and** for `technical`,
`experience_length`, and `degree` lines the page's visible text contains the
term, figure, or degree a screener would look for (literal check, with
aliases). `interpersonal`/`other` lines need provenance only. The check is
pure code and re-runs after holistic-review edits, after the bullet-review
pause, and after page fitting, so a later edit or trim cannot silently break
coverage.

Flags appear in `match_report.json` and in the web job view. They do not block
rendering.

### 4. Page budget (two pages)

- Fitting allows up to two pages (`render.py` `fit_to_one_page` generalised to
  a page limit; fit-recovery's `page_count` assumptions in
  `resume_tailor/fit_recovery.py` follow the limit).
- More roles and projects are selectable: all roles that carry evidence for a
  qualification line, plus the strongest others; more projects than the
  current two. Exact caps and bullet counts are the builder's call, under the
  anti-goal against padding.
- Ordering follows the first project: current role first, then reverse
  chronological.
- Selection prefers entries that cover minimum-qualification lines first, then
  preferred lines, then keywords.

### 5. Summary

- A new optional `Summary` section at the top of the template, rendered only in
  college mode.
- 2-3 lines: target title as the posting names it, relevant years of
  experience (computed in §2), and the strongest qualification matches.
  Written by one AI call on the writing chain, given the JD profile, the
  qualification map, and the selected evidence; validated so that every claim
  maps to a source fact and years match the computed value.
- "One AI call" means one stage; normal model fallback and the usual retry on
  validation failure are allowed within it. If it still fails, the summary is
  built in code from a template ("{Title as posted} candidate with {N}+ years
  of {domain} experience across {top 2-3 covered qualifications}.") and a
  warning is reported. The summary is never missing in college mode.
- The summary is not part of the bullet-review pause; it is shown in the job
  view and editable through the same edit path as the rest of the output,
  if one exists, otherwise not editable in this project.

## Verification

- SUU posting with the switch on: every minimum-qualification line is either
  covered on the page or flagged with a specific reason; "Two years recent web
  development/programming experience" is computed from the Facilities and
  Fanatics dates (union, ~28 months as of 2026-10) and shown as "2+ years";
  Section 508/ADA appears as a skill-check chip and is covered only when the
  user confirms it, flagged otherwise; output is ≤ 2 pages; summary is present
  and names "UX/UI Developer" (from the AI call or the code fallback).
- Fordham posting: tool gaps (Figma, Adobe XD, Siteimprove, TERMINALFOUR) come
  through the skill check, not as fabricated bullets.
- The same postings with the switch off produce the big-company output.
- Existing tests pass; resume-from-checkpoint works in both modes.

## Left to the builder

- Exact caps for roles, projects, and bullets on two pages.
- How "content matches the domain" is decided for experience-length counting
  (keyword rules vs. model mapping).
- Template styling of the summary section.
- Whether line-item parsing is a separate prompt section or an extension of
  `jd_parse.jinja`, provided it adds no AI call.
