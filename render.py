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
3. :func:`fit_to_one_page` implements the spec's deterministic one-page fit loop:
   render, count pages with ``pypdf``, and while the PDF spans more than one page
   drop exactly one lowest-relevance item per iteration in a fixed priority order
   (bullets beyond 2 per position -> projects beyond 2 -> skill groups -> oldest
   low-relevance position's bullets to 1 -> whole lowest-relevance position),
   never touching education or the header, tie-broken by recency (older first),
   with a hard cap of 25 iterations before failing loudly.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

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
_LATEX_ESCAPE_MAP: Dict[str, str] = {
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


def latex_escape(text: Optional[str]) -> Optional[str]:
    """Escape the ten LaTeX special characters in ``text``.

    ``None`` passes through as ``None`` so callers can distinguish "absent" from
    "empty" and guard optional fields. Non-string values are coerced with
    ``str()`` first.
    """
    if text is None:
        return None
    return _LATEX_ESCAPE_RE.sub(lambda m: _LATEX_ESCAPE_MAP[m.group()], str(text))


def _esc(value: Any) -> Optional[str]:
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


def _esc_list(values: Optional[List[Any]]) -> List[str]:
    """Escape a list of strings, dropping blanks. Never returns ``None``."""
    if not values:
        return []
    return [e for e in (_esc(v) for v in values) if e]


def _join_escaped(values: Optional[List[Any]], sep: str) -> Optional[str]:
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


def _date_range(start: Optional[str], end: Optional[str]) -> Optional[str]:
    """Build an escaped ``start -- end`` date string, gracefully partial."""
    s, e = _esc(start), _esc(end)
    if s and e:
        return f"{s} -- {e}"
    return s or e


def _contact_line(basics: Optional[Basics]) -> Optional[str]:
    """Join phone / email / profile URLs / portfolio with ``~$|$~``.

    Missing pieces are skipped so the separator never dangles.
    """
    if basics is None:
        return None
    parts: List[Any] = [basics.phone, basics.email]
    if basics.profiles:
        parts.extend(p.url for p in basics.profiles if p is not None)
    parts.append(basics.url)
    return _join_escaped(parts, r"~$|$~")


def _education_ctx(education: Optional[List[Education]]) -> List[Dict[str, Any]]:
    ctx: List[Dict[str, Any]] = []
    for e in education or []:
        degree = _join_escaped([e.studyType, e.area], ", ")
        ctx.append(
            {
                "institution": _esc(e.institution),
                "degree": degree,
                "dates": _date_range(e.startDate, e.endDate),
                "score": _esc(e.score),
            }
        )
    return ctx


def _work_ctx(work: Optional[List[Work]]) -> List[Dict[str, Any]]:
    ctx: List[Dict[str, Any]] = []
    for w in work or []:
        ctx.append(
            {
                "name": _esc(w.name),
                "position": _esc(w.position),
                "dates": _date_range(w.startDate, w.endDate),
                "location": None,  # JSONResume Work carries no location field
                "highlights": _esc_list(w.highlights),
            }
        )
    return ctx


def _project_ctx(projects: Optional[List[Project]]) -> List[Dict[str, Any]]:
    ctx: List[Dict[str, Any]] = []
    for p in projects or []:
        tech = p.technologies or p.skills
        ctx.append(
            {
                "name": _esc(p.name),
                "tech_line": _join_escaped(tech, ", "),
                "url": _esc(p.url),
                "dates": _date_range(p.startDate, p.endDate),
                "highlights": _esc_list(p.highlights),
            }
        )
    return ctx


def _skills_ctx(skills: Optional[List[Skill]]) -> List[Dict[str, Any]]:
    ctx: List[Dict[str, Any]] = []
    for s in skills or []:
        name = _esc(s.name)
        keywords_line = _join_escaped(s.keywords, ", ")
        if not name and not keywords_line:
            continue  # nothing renderable -> drop the group entirely
        ctx.append({"name": name, "keywords_line": keywords_line})
    return ctx


def build_context(resume: JSONResume) -> Dict[str, Any]:
    """Turn a :class:`JSONResume` into a fully-escaped template context."""
    basics = resume.basics
    return {
        "name": _esc(basics.name) if basics is not None else None,
        "contact_line": _contact_line(basics),
        "summary": _esc(basics.summary) if basics is not None else None,
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
    pdf: Optional[Path] = None


def _compile_pdf(tex_path: Path, out_dir: Path) -> Path:
    """Compile ``tex_path`` to PDF with ``tectonic``; raise on missing binary/failure."""
    exe = shutil.which("tectonic")
    if exe is None:
        raise RenderError(
            "tectonic is required to compile the PDF but was not found on PATH. "
            "Install it (macOS: 'brew install tectonic'; other platforms: "
            "https://tectonic-typesetting.github.io/en-US/install.html), or pass "
            "compile_pdf=False (CLI: --no-pdf) to write only the .tex source."
        )
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

    basics: Optional[Basics] = None
    work: Optional[List[ScoredWork]] = None
    volunteer: Optional[List[Volunteer]] = None
    education: Optional[List[Education]] = None
    awards: Optional[List[Award]] = None
    certificates: Optional[List[Certificate]] = None
    publications: Optional[List[Publication]] = None
    skills: Optional[List[ScoredSkill]] = None
    languages: Optional[List[Language]] = None
    interests: Optional[List[Interest]] = None
    references: Optional[List[Reference]] = None
    projects: Optional[List[ScoredProject]] = None


def scored_to_plain(sr: ScoredResume) -> JSONResume:
    """Convert a :class:`ScoredResume` to a plain :class:`JSONResume` for rendering."""
    return JSONResume(
        basics=sr.basics,
        work=[strip_relevance_work(w) for w in sr.work] if sr.work else None,
        volunteer=sr.volunteer,
        education=sr.education,
        awards=sr.awards,
        certificates=sr.certificates,
        publications=sr.publications,
        skills=[strip_relevance_skill(s) for s in sr.skills] if sr.skills else None,
        languages=sr.languages,
        interests=sr.interests,
        references=sr.references,
        projects=(
            [strip_relevance_project(p) for p in sr.projects] if sr.projects else None
        ),
    )


# ---------------------------------------------------------------------------
# Recency (tie-break helper: older items are trimmed first)
# ---------------------------------------------------------------------------

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_PRESENT_TOKENS = ("present", "current", "ongoing", "now", "today", "to date", "till date")


def _date_value(raw: Optional[str]) -> Optional[float]:
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


def _recency_rank(start: Optional[str], end: Optional[str]) -> float:
    """Recency of a dated item; larger == more recent. Unknown dates sort oldest."""
    for candidate in (end, start):
        value = _date_value(candidate)
        if value is not None:
            return value
    return float("-inf")


def _short(text: Optional[str], limit: int = 32) -> str:
    """A compact preview of a bullet/name for trim-log descriptions."""
    if not text:
        return ""
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# One-page fit loop
# ---------------------------------------------------------------------------
#
# Trim priority order (spec Sec. One-page auto-fit, item 2). Each call to
# _next_trim drops exactly ONE item, checking tiers strictly in order and
# returning on the first tier with a candidate:
#   (a) work bullets beyond 2 per position
#   (b) whole projects beyond 2
#   (c) skill groups
#   (d) oldest low-relevance position's remaining bullets down to 1
#   (e) whole lowest-relevance position
# Education and the header/basics are never trimmed. Ties are broken by recency
# (older goes first); a final list-index term keeps every choice deterministic.


def _trim_tier_a(work: List[ScoredWork]) -> Optional[str]:
    """(a) Drop the lowest-relevance bullet among positions with more than 2 bullets."""
    keyed = []  # (sort_key, position_index, bullet_index)
    for pi, w in enumerate(work):
        highlights = w.highlights or []
        if len(highlights) > 2:
            rec = _recency_rank(w.startDate, w.endDate)
            for bi, bullet in enumerate(highlights):
                keyed.append(((bullet.relevance, rec, pi, bi), pi, bi))
    if not keyed:
        return None
    keyed.sort(key=lambda c: c[0])
    _, pi, bi = keyed[0]
    dropped = work[pi].highlights.pop(bi)
    return f"tier-a: pos#{pi} bullet '{_short(dropped.text)}' (rel={dropped.relevance})"


def _trim_tier_b(sr: ScoredResume, projects: List[ScoredProject]) -> Optional[str]:
    """(b) Drop the lowest-relevance project once there are more than 2."""
    if len(projects) <= 2:
        return None
    keyed = [
        ((p.relevance, _recency_rank(p.startDate, p.endDate), pi), pi)
        for pi, p in enumerate(projects)
    ]
    keyed.sort(key=lambda c: c[0])
    idx = keyed[0][1]
    dropped = projects.pop(idx)
    return f"tier-b: project '{_short(dropped.name)}' (rel={dropped.relevance})"


def _trim_tier_c(sr: ScoredResume, skills: List[ScoredSkill]) -> Optional[str]:
    """(c) Drop the lowest-relevance skill group."""
    if not skills:
        return None
    idx = min(range(len(skills)), key=lambda i: (skills[i].relevance, i))
    dropped = skills.pop(idx)
    return f"tier-c: skill group '{_short(dropped.name)}' (rel={dropped.relevance})"


def _trim_tier_d(work: List[ScoredWork]) -> Optional[str]:
    """(d) From the oldest lowest-relevance position with >1 bullet, drop its weakest bullet."""
    keyed = []
    for pi, w in enumerate(work):
        highlights = w.highlights or []
        if len(highlights) > 1:
            keyed.append(((w.relevance, _recency_rank(w.startDate, w.endDate), pi), pi))
    if not keyed:
        return None
    keyed.sort(key=lambda c: c[0])
    pi = keyed[0][1]
    highlights = work[pi].highlights
    bi = min(range(len(highlights)), key=lambda i: (highlights[i].relevance, i))
    dropped = highlights.pop(bi)
    return f"tier-d: pos#{pi} bullet '{_short(dropped.text)}' (rel={dropped.relevance})"


def _trim_tier_e(sr: ScoredResume, work: List[ScoredWork]) -> Optional[str]:
    """(e) Drop the whole lowest-relevance position."""
    if not work:
        return None
    keyed = [
        ((w.relevance, _recency_rank(w.startDate, w.endDate), pi), pi)
        for pi, w in enumerate(work)
    ]
    keyed.sort(key=lambda c: c[0])
    idx = keyed[0][1]
    dropped = work.pop(idx)
    return f"tier-e: position '{_short(dropped.name)}' (rel={dropped.relevance})"


def _next_trim(sr: ScoredResume) -> Optional[str]:
    """Mutate ``sr`` in place, dropping exactly one item per the priority order.

    Returns a human-readable description of what was dropped, or ``None`` when
    nothing trimmable remains (education/header are off-limits).
    """
    work = sr.work or []
    projects = sr.projects or []
    skills = sr.skills or []

    # Tiers are checked strictly in order; the first with a candidate fires.
    action = _trim_tier_a(work)
    if action:
        return action
    action = _trim_tier_b(sr, projects)
    if action:
        return action
    action = _trim_tier_c(sr, skills)
    if action:
        return action
    action = _trim_tier_d(work)
    if action:
        return action
    action = _trim_tier_e(sr, work)
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
    page_counter: Optional[Callable[[JSONResume], int]] = None,
    max_iterations: int = 25,
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
    is raised.
    """
    out_dir = Path(out_dir)
    working = scored_resume.model_copy(deep=True)
    counter = page_counter or _default_page_counter(out_dir)
    trim_log: List[str] = []

    for iteration in range(max_iterations + 1):
        plain = scored_to_plain(working)
        pages = counter(plain)
        if pages <= 1:
            return plain
        if iteration == max_iterations:
            break
        action = _next_trim(working)
        if action is None:
            raise RenderError(
                "Cannot fit resume to one page: every trimmable item has been "
                "removed (education and the header are never trimmed) but the PDF "
                f"still spans {pages} pages. Trims applied: {trim_log}"
            )
        trim_log.append(action)

    raise RenderError(
        f"Exceeded the one-page fit cap of {max_iterations} trim iterations; the "
        f"PDF still spans multiple pages. Trims applied: {trim_log}"
    )
