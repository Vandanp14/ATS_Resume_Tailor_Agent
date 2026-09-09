"""Renderer: JSONResume -> Jake's-Resume-style LaTeX -> one-page PDF.

Responsibilities
----------------
1. LaTeX-safe rendering of a :class:`models.JSONResume` through the Jinja
   template ``templates/latex/jakes.tex.jinja`` (custom ``\\VAR{}`` / ``\\BLOCK{}``
   delimiters so Jinja never collides with LaTeX braces). *Every* interpolated
   string is escaped for the ten LaTeX specials ``& % $ # _ { } ~ ^ \\`` before
   it reaches the template, and optional fields are dropped entirely (no literal
   ``None``, no dangling ``$|$`` separators).
2. :func:`render` writes the ``.tex`` always and, when asked, compiles a PDF with
   ``tectonic`` (raising an actionable error if the binary is missing).
3. :func:`fit_to_one_page` implements the deterministic one-page fit loop:
   render, count pages with ``pypdf``, and while the PDF spans more than one page
   trim project content above the two-bullet floor, skill groups above three, and
   projects above two. Required 4/3/3 work bullets, two bullets on each selected
   project, education, and the header are protected; the fitter fails loudly if
   those constraints cannot fit.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from models import (
    Award,
    Basics,
    Certificate,
    Education,
    Interest,
    JSONResume,
    Language,
    Project,
    Publication,
    Reference,
    ScoredProject,
    ScoredSkill,
    ScoredWork,
    Skill,
    TRANSFERABLE_SKILL_GROUP,
    Volunteer,
    Work,
    strip_relevance_project,
    strip_relevance_skill,
    strip_relevance_work,
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RenderError(RuntimeError):
    """Raised when rendering or the one-page fit loop cannot complete."""


# ---------------------------------------------------------------------------
# LaTeX escaping
# ---------------------------------------------------------------------------

# Order is irrelevant because a single regex pass replaces each source character
# exactly once -- the replacement text (which itself contains ``\``, ``{``, ``}``)
# is never re-scanned, so ``&`` never becomes ``\textbackslash{}&`` etc.
_LATEX_ESCAPE_MAP: dict[str, str] = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
_LATEX_ESCAPE_RE = re.compile("|".join(re.escape(k) for k in _LATEX_ESCAPE_MAP))

# Common Unicode punctuation that the template's T1/Computer-Modern setup has no
# glyphs for (tectonic's XeTeX engine silently DROPS them, corrupting both the
# PDF and ATS text extraction). Master resumes come from PDF extraction and
# tailored bullets mirror JD language, so curly quotes, dashes, bullets, and
# NBSP are routine. Normalize them to ASCII/TeX equivalents BEFORE the specials
# pass -- every replacement is an ASCII non-special, so the escape pass below
# stays correct and engine-independent.
_UNICODE_NORMALIZE_MAP: dict[str, str] = {
    "‘": "'",
    "’": "'",
    "‚": ",",
    "′": "'",  # single quotes / prime
    "ʼ": "'",
    "´": "'",
    "`": "`",
    "“": '"',
    "”": '"',
    "„": ",,",
    "″": '"',  # double quotes / prime
    "–": "--",
    "—": "---",  # en / em dash
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "―": "---",
    "−": "-",  # hyphens / minus
    "•": "-",
    "·": "-",
    "‧": "-",  # bullets
    "…": "...",  # ellipsis
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",  # non-breaking / thin spaces
    " ": " ",
    " ": " ",
    " ": " ",
    "­": "",  # soft hyphen (invisible) -> drop
}
_UNICODE_TRANSLATE = {ord(k): v for k, v in _UNICODE_NORMALIZE_MAP.items()}


def latex_escape(text: str | None) -> str | None:
    """Escape the ten LaTeX special characters in ``text``.

    First normalizes common Unicode punctuation (curly quotes, en/em dashes,
    bullets, ellipsis, NBSP) to ASCII/TeX equivalents so the T1-encoded engine
    does not silently drop glyphs it cannot render.

    ``None`` passes through as ``None`` so callers can distinguish "absent" from
    "empty" and guard optional fields. Non-string values are coerced with
    ``str()`` first.
    """
    if text is None:
        return None
    normalized = str(text).translate(_UNICODE_TRANSLATE)
    return _LATEX_ESCAPE_RE.sub(lambda m: _LATEX_ESCAPE_MAP[m.group()], normalized)


def _esc(value: Any) -> str | None:
    """Escape a value, collapsing ``None`` / blank / whitespace-only to ``None``.

    Used for optional resume fields so the template's ``\\BLOCK{ if ... }`` guards
    omit them entirely rather than emitting empty markup.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return latex_escape(s)


def _esc_list(values: list[Any] | None) -> list[str]:
    """Escape a list of strings, dropping blanks. Never returns ``None``."""
    if not values:
        return []
    return [e for e in (_esc(v) for v in values) if e]


def _join_escaped(values: list[Any] | None, sep: str) -> str | None:
    """Escape non-blank ``values`` and join with the (literal) LaTeX ``sep``.

    ``sep`` is *not* escaped -- it is fixed template markup such as ``, `` or
    ``~$|$~``. Returns ``None`` when nothing survives so no dangling separator
    is ever produced.
    """
    parts = _esc_list(values)
    if not parts:
        return None
    return sep.join(parts)


# ---------------------------------------------------------------------------
# Jinja environment
# ---------------------------------------------------------------------------

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates" / "latex"
_TEMPLATE_NAME = "jakes.tex.jinja"


def _build_env() -> Environment:
    """Jinja env with LaTeX-safe delimiters (``\\VAR{}`` / ``\\BLOCK{}`` / ``\\#{}``)."""
    return Environment(
        block_start_string=r"\BLOCK{",
        block_end_string="}",
        variable_start_string=r"\VAR{",
        variable_end_string="}",
        comment_start_string=r"\#{",
        comment_end_string="}",
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
        undefined=StrictUndefined,
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    )


_ENV = _build_env()


# ---------------------------------------------------------------------------
# Template context construction (escaping happens here, once, for every string)
# ---------------------------------------------------------------------------


_MONTH_NAMES = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}


def _format_date(value: str | None) -> str | None:
    """Format ISO month dates for people while leaving other source formats intact."""
    if value is None:
        return None
    raw = str(value).strip()
    match = re.fullmatch(r"(19|20)\d{2}-(0?[1-9]|1[0-2])", raw)
    if match:
        return f"{_MONTH_NAMES[int(match.group(2))]} {raw[:4]}"
    return raw or None


def _date_range(start: str | None, end: str | None) -> str | None:
    """Build an escaped human-readable date range, gracefully partial."""
    s, e = _esc(_format_date(start)), _esc(_format_date(end))
    if s and e:
        return f"{s} -- {e}"
    return s or e


def _education_end_date(value: str | None, today: date | None = None) -> str | None:
    """Format an education end date and label a future completion as expected."""
    formatted = _format_date(value)
    if formatted is None:
        return None
    raw = str(value).strip()
    match = re.fullmatch(r"((?:19|20)\d{2})(?:-(0?[1-9]|1[0-2]))?", raw)
    if not match:
        return formatted
    year = int(match.group(1))
    month = int(match.group(2) or 12)
    current = today or date.today()
    prefix = "Expected " if (year, month) > (current.year, current.month) else ""
    return prefix + formatted


def _education_date_range(
    start: str | None, end: str | None, today: date | None = None
) -> str | None:
    start_text = _esc(_format_date(start))
    end_text = _esc(_education_end_date(end, today))
    if start_text and end_text:
        return f"{start_text} -- {end_text}"
    return start_text or end_text


def _raw(value: Any) -> str | None:
    """Return ``value`` stripped to a non-blank raw string, else ``None``.

    Unlike :func:`_esc` this performs **no** LaTeX escaping -- used for the
    ``\\href{...}`` target, which must stay raw (escaping ``_`` / ``%`` etc.
    would corrupt the link).
    """
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _link_display(raw_url: str) -> str:
    """Jake-style link display text: drop a leading scheme and ``www.``.

    e.g. ``https://www.linkedin.com/in/jake`` -> ``linkedin.com/in/jake``.
    """
    display = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", "", raw_url)
    display = re.sub(r"^www\.", "", display)
    return display


def _href_piece(target: str, display: str) -> str:
    """Build ``\\href{<raw target>}{\\underline{<escaped display>}}``.

    ``target`` stays raw (a working URL / mailto); only ``display`` is escaped.
    ``hyperref`` is loaded with ``hidelinks`` so the link is not colored.
    """
    return r"\href{" + target + r"}{\underline{" + latex_escape(display) + "}}"


def _project_link_label(raw_url: str) -> str:
    """Return a compact, useful label for a project's visible hyperlink."""
    display = _link_display(raw_url).casefold()
    if display == "github.com" or display.startswith("github.com/"):
        return "GitHub"
    if re.match(r"^(?:https?://|www\.)", raw_url, re.IGNORECASE):
        return "Live Demo"
    return "Project Link"


def _contact_line(basics: Basics | None) -> str | None:
    """Build Jake's contact line: phone plain, email + short clickable labels.

    Phone stays plain (escaped) text. Email becomes a ``mailto:`` link showing
    the address. Each profile URL becomes a clickable, underlined ``\\href``
    whose target is the RAW url (escaping it would break the link) and whose
    display text is the profile's ``network`` label (e.g. "GitHub",
    "LinkedIn"), falling back to the scheme/``www.``-stripped URL when the
    network is missing/blank. ``basics.url`` (personal site) displays
    "Portfolio". Display text is always escaped. Pieces are joined with Jake's
    ``` $|$ ``` separator and missing pieces are skipped so it never dangles.
    """
    if basics is None:
        return None
    pieces: list[str] = []

    phone = _esc(basics.phone)
    if phone:
        pieces.append(phone)

    email = _raw(basics.email)
    if email:
        pieces.append(_href_piece("mailto:" + email, email))

    for p in basics.profiles or []:
        if p is None:
            continue
        target = _raw(p.url)
        if target:
            label = _raw(p.network) or _link_display(target)
            pieces.append(_href_piece(target, label))

    portfolio = _raw(basics.url)
    if portfolio:
        pieces.append(_href_piece(portfolio, "Portfolio"))

    if not pieces:
        return None
    return " $|$ ".join(pieces)


def _education_ctx(education: list[Education] | None) -> list[dict[str, Any]]:
    ctx: list[dict[str, Any]] = []
    for e in education or []:
        degree = _join_escaped([e.studyType, e.area], ", ")
        ctx.append(
            {
                "institution": _esc(e.institution),
                "degree": degree,
                "dates": _education_date_range(e.startDate, e.endDate),
                "score": _esc(e.score),
            }
        )
    return ctx


CONCURRENT_ROLE_QUALIFIER = "concurrent"


def _concurrent_role_indices(work: list[Work]) -> set[int]:
    """Indices of roles whose dates overlap another role's and need a qualifier.

    Two unqualified overlapping date ranges read as unexplained double
    employment on a first skim. The shorter of an overlapping pair carries the
    qualifier, since that is the one a reader is being asked to fit inside the
    other. Roles with unparseable dates are left alone.
    """

    spans: dict[int, tuple[float, float]] = {}
    for index, role in enumerate(work):
        start = _date_value(role.startDate)
        end = _date_value(role.endDate)
        if start is not None and end is not None and start <= end:
            spans[index] = (start, end)

    flagged: set[int] = set()
    for first, (start_a, end_a) in spans.items():
        for second, (start_b, end_b) in spans.items():
            if second <= first:
                continue
            if start_a >= end_b or start_b >= end_a:
                continue
            duration_a, duration_b = end_a - start_a, end_b - start_b
            flagged.add(second if duration_b <= duration_a else first)
    return flagged


def _work_ctx(work: list[Work] | None) -> list[dict[str, Any]]:
    ctx: list[dict[str, Any]] = []
    roles = list(work or [])
    concurrent = _concurrent_role_indices(roles)
    for index, w in enumerate(roles):
        dates = _date_range(w.startDate, w.endDate)
        if dates and index in concurrent:
            dates = f"{dates} ({_esc(CONCURRENT_ROLE_QUALIFIER)})"
        ctx.append(
            {
                "name": _esc(w.name),
                "position": _esc(w.position),
                "dates": dates,
                "location": None,  # JSONResume Work carries no location field
                "highlights": _esc_list(w.highlights),
            }
        )
    return ctx


def _project_ctx(projects: list[Project] | None) -> list[dict[str, Any]]:
    ctx: list[dict[str, Any]] = []
    for p in projects or []:
        tech = p.technologies or p.skills
        name = _esc(p.name)
        tech_line = _join_escaped(tech, ", ")
        dates = _date_range(p.startDate, p.endDate)
        url_target = _raw(p.url)
        link = (
            _href_piece(url_target, _project_link_label(url_target))
            if url_target
            else None
        )
        ctx.append(
            {
                "name": name,
                "tech_line": tech_line,
                "link": link,
                "dates": dates,
                "has_primary": bool(name or dates),
                "has_meta": bool(tech_line or link),
                "highlights": _esc_list(p.highlights),
            }
        )
    return ctx


def _skills_ctx(skills: list[Skill] | None) -> list[dict[str, Any]]:
    ctx: list[dict[str, Any]] = []
    for s in skills or []:
        name = _esc(s.name)
        keywords_line = _join_escaped(s.keywords, ", ")
        if not name and not keywords_line:
            continue  # nothing renderable -> drop the group entirely
        ctx.append({"name": name, "keywords_line": keywords_line})
    return ctx


def build_context(resume: JSONResume) -> dict[str, Any]:
    """Turn a :class:`JSONResume` into a fully-escaped template context."""
    basics = resume.basics
    return {
        "name": _esc(basics.name) if basics is not None else None,
        "contact_line": _contact_line(basics),
        "education": _education_ctx(resume.education),
        "work": _work_ctx(resume.work),
        "projects": _project_ctx(resume.projects),
        "skills": _skills_ctx(resume.skills),
    }


def render_tex(resume: JSONResume) -> str:
    """Render the resume to a LaTeX source string (no file written)."""
    template = _ENV.get_template(_TEMPLATE_NAME)
    return template.render(**build_context(resume))


# ---------------------------------------------------------------------------
# Rendering + PDF compilation
# ---------------------------------------------------------------------------


@dataclass
class RenderResult:
    """Paths produced by :func:`render`. ``pdf`` is ``None`` when not compiled."""

    tex: Path
    pdf: Path | None = None


def ensure_tectonic() -> str:
    """Return the ``tectonic`` executable path, or raise an actionable RenderError.

    Exposed so callers (e.g. the orchestrator's preflight) can fail fast BEFORE
    spending paced LLM calls when PDF output is requested on a machine without
    tectonic, instead of discovering it only at compile time.
    """
    exe = shutil.which("tectonic")
    if exe is None:
        raise RenderError(
            "tectonic is required to compile the PDF but was not found on PATH. "
            "Install it (macOS: 'brew install tectonic'; other platforms: "
            "https://tectonic-typesetting.github.io/en-US/install.html), or pass "
            "compile_pdf=False (CLI: --no-pdf) to write only the .tex source."
        )
    return exe


def _compile_pdf(tex_path: Path, out_dir: Path) -> Path:
    """Compile ``tex_path`` to PDF with ``tectonic``; raise on missing binary/failure."""
    exe = ensure_tectonic()
    proc = subprocess.run(
        [exe, tex_path.name],
        cwd=str(out_dir),
        capture_output=True,
        text=True,
    )
    pdf_path = out_dir / (tex_path.stem + ".pdf")
    if proc.returncode != 0 or not pdf_path.exists():
        raise RenderError(
            f"tectonic failed to compile {tex_path.name} (exit {proc.returncode}).\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
    return pdf_path


def render(resume: JSONResume, out_dir: Path, compile_pdf: bool) -> RenderResult:
    """Render ``resume`` to ``out_dir/resume.tex`` and optionally ``resume.pdf``.

    The ``.tex`` is always written. When ``compile_pdf`` is true a PDF is built
    with ``tectonic`` (an actionable :class:`RenderError` names ``brew install
    tectonic`` if the binary is absent).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tex_path = out_dir / "resume.tex"
    tex_path.write_text(render_tex(resume), encoding="utf-8")

    pdf_path = _compile_pdf(tex_path, out_dir) if compile_pdf else None
    return RenderResult(tex=tex_path, pdf=pdf_path)


def count_pages(pdf_path: Path) -> int:
    """Return the number of pages in ``pdf_path`` via ``pypdf``."""
    from pypdf import PdfReader

    return len(PdfReader(str(pdf_path)).pages)


# ---------------------------------------------------------------------------
# Scored resume container (input to the one-page fit loop)
# ---------------------------------------------------------------------------


class ScoredResume(BaseModel):
    """A JSONResume whose trimmable sections carry JD-driven relevance scores.

    The one-page fit loop consumes this (it needs the relevance fields to decide
    what to drop) and returns a plain :class:`JSONResume`. Education, basics and
    the passthrough sections are plain models -- they are never trimmed. Defined
    here (not in ``models.py``) because it is a renderer-internal contract; the
    orchestrator constructs it from the Scored* section-tailor outputs.
    """

    basics: Basics | None = None
    work: list[ScoredWork] | None = None
    volunteer: list[Volunteer] | None = None
    education: list[Education] | None = None
    awards: list[Award] | None = None
    certificates: list[Certificate] | None = None
    publications: list[Publication] | None = None
    skills: list[ScoredSkill] | None = None
    languages: list[Language] | None = None
    interests: list[Interest] | None = None
    references: list[Reference] | None = None
    projects: list[ScoredProject] | None = None


def scored_to_plain(sr: ScoredResume) -> JSONResume:
    """Convert a :class:`ScoredResume` to a plain :class:`JSONResume` for rendering."""
    payload = sr.model_dump(mode="json", exclude_unset=True)
    payload["work"] = [strip_relevance_work(w) for w in sr.work] if sr.work else None
    payload["skills"] = (
        [strip_relevance_skill(s) for s in sr.skills] if sr.skills else None
    )
    payload["projects"] = (
        [strip_relevance_project(p) for p in sr.projects] if sr.projects else None
    )
    return JSONResume.model_validate(payload)


# ---------------------------------------------------------------------------
# Recency (tie-break helper: older items are trimmed first)
# ---------------------------------------------------------------------------

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_PRESENT_TOKENS = (
    "present",
    "current",
    "ongoing",
    "now",
    "today",
    "to date",
    "till date",
)


def _date_value(raw: str | None) -> float | None:
    """Parse a date string into a sortable float (larger == more recent).

    Handles ``YYYY``, ``YYYY-MM`` / ``YYYY/MM``, ``Mon YYYY`` / ``Month YYYY``,
    and "Present"/"Current"/... (treated as +inf). Returns ``None`` when no year
    can be found.
    """
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s:
        return None
    if any(tok in s for tok in _PRESENT_TOKENS):
        return float("inf")

    year_match = re.search(r"(19|20)\d{2}", s)
    if not year_match:
        return None
    year = int(year_match.group())

    month = 0
    for name, num in _MONTHS.items():
        if name in s:
            month = num
            break
    if month == 0:
        # numeric month adjacent to the year, e.g. 2021-06 or 06/2021
        rest = s.replace(year_match.group(), " ")
        mnum = re.search(r"\b(0?[1-9]|1[0-2])\b", rest)
        if mnum:
            month = int(mnum.group(1))
    return year + month / 12.0


def _recency_rank(start: str | None, end: str | None) -> float:
    """Recency of a dated item; larger == more recent. Unknown dates sort oldest."""
    for candidate in (end, start):
        value = _date_value(candidate)
        if value is not None:
            return value
    return float("-inf")


def _short(text: str | None, limit: int = 32) -> str:
    """A compact preview of a bullet/name for trim-log descriptions."""
    if not text:
        return ""
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# One-page fit loop
# ---------------------------------------------------------------------------
#
# Work bullets are never candidates: the 4/3/3 work allocation is a hard output
# contract. Two bullets on each of the two selected projects are protected too.
# The fitter may remove only content above those project floors, then skill groups
# down to three, then whole projects above the two-project floor. If that is not
# enough, publishing fails instead of silently weakening the evidence portfolio.


def _trim_excess_project_bullet(projects: list[ScoredProject]) -> str | None:
    eligible = [
        (project.relevance, index)
        for index, project in enumerate(projects)
        if len(project.highlights or []) > 2
    ]
    if not eligible:
        return None
    _, index = min(eligible)
    dropped = projects[index].highlights.pop()
    return (
        f"tier-a: excess project bullet '{_short(dropped.text)}' from "
        f"'{_short(projects[index].name)}'"
    )


def _trim_skill_group(skills: list[ScoredSkill]) -> str | None:
    if len(skills) <= 3:
        return None
    eligible = [
        index
        for index, skill in enumerate(skills)
        if skill.name != TRANSFERABLE_SKILL_GROUP
    ]
    if not eligible:
        return None
    index = min(eligible, key=lambda i: (skills[i].relevance, i))
    dropped = skills.pop(index)
    return f"tier-b: skill group '{_short(dropped.name)}' (rel={dropped.relevance})"


def _trim_excess_project(projects: list[ScoredProject]) -> str | None:
    if len(projects) <= 2:
        return None
    index = min(
        range(len(projects)),
        key=lambda i: (
            projects[i].relevance,
            _recency_rank(projects[i].startDate, projects[i].endDate),
            i,
        ),
    )
    dropped = projects.pop(index)
    return f"tier-c: project '{_short(dropped.name)}' (rel={dropped.relevance})"


def _next_trim(sr: ScoredResume) -> str | None:
    """Mutate ``sr`` in place, dropping exactly one item per the priority order.

    Returns a human-readable description of what was dropped, or ``None`` when
    nothing trimmable remains (education/header are off-limits).
    """
    projects = sr.projects or []
    skills = sr.skills or []

    action = _trim_excess_project_bullet(projects)
    if action:
        return action
    action = _trim_skill_group(skills)
    if action:
        return action
    action = _trim_excess_project(projects)
    if action:
        return action
    return None


def _default_page_counter(out_dir: Path) -> Callable[[JSONResume], int]:
    """Real page counter: render (compile) the resume and count PDF pages."""

    def counter(plain: JSONResume) -> int:
        result = render(plain, out_dir, compile_pdf=True)
        return count_pages(result.pdf)

    return counter


def fit_to_one_page(
    scored_resume: ScoredResume,
    out_dir: Path,
    page_counter: Callable[[JSONResume], int] | None = None,
    max_iterations: int = 100,
    progress_callback: Callable[[str], None] | None = None,
    exhaustion_handler: (
        Callable[[ScoredResume, int, tuple[str, ...]], str | None] | None
    ) = None,
) -> JSONResume:
    """Trim ``scored_resume`` until it renders to exactly one page.

    Renders the current resume, counts its pages, and while it spans more than
    one page drops a single lowest-relevance item per iteration in the spec's
    fixed priority order (see module notes). Returns the final trimmed plain
    :class:`JSONResume`; the matching ``.tex``/``.pdf`` are on disk in
    ``out_dir``.

    ``page_counter`` is injectable for tests (default renders + counts with
    ``pypdf`` + ``tectonic``). After ``max_iterations`` trims without reaching
    one page -- or when no trimmable content remains -- a :class:`RenderError`
    is raised. ``exhaustion_handler`` is called only after ordinary trimming has
    no legal action left; it may mutate the working scored resume and return a
    description of that action. A ``None`` result preserves the historical
    exhaustion error.
    """
    out_dir = Path(out_dir)
    working = scored_resume.model_copy(deep=True)
    counter = page_counter or _default_page_counter(out_dir)
    trim_log: list[str] = []

    for iteration in range(max_iterations + 1):
        plain = scored_to_plain(working)
        pages = counter(plain)
        if progress_callback:
            progress_callback(
                f"One-page fit iteration {iteration + 1}: rendered {pages} page(s)"
            )
        if pages == 1:
            return plain
        if pages < 1:
            raise RenderError(f"PDF page counter returned invalid page count: {pages}")
        if iteration == max_iterations:
            break
        action = _next_trim(working)
        if action is None and exhaustion_handler is not None:
            action = exhaustion_handler(working, pages, tuple(trim_log))
        if action is None:
            raise RenderError(
                "Cannot fit resume to one page: every trimmable item has been "
                "removed (education and the header are never trimmed) but the PDF "
                f"still spans {pages} pages. Trims applied: {trim_log}"
            )
        trim_log.append(action)
        if progress_callback:
            prefix = (
                "One-page fit trim"
                if action.startswith("tier-")
                else "One-page fit recovery"
            )
            progress_callback(f"{prefix}: {action}")

    raise RenderError(
        f"Exceeded the one-page fit cap of {max_iterations} trim iterations; the "
        f"PDF still spans multiple pages. Trims applied: {trim_log}"
    )
