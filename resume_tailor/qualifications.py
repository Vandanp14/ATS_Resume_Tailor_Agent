"""College qualification lines checked in code: experience, degree, substitution.

Years of experience are counted from the master's own work dates, never from a
model, so the number a screener sees is one the candidate can defend.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from keyword_coverage import mentions, normalize_term, term_variants
from models import (
    EvidencePlan,
    Education,
    JDProfile,
    JSONResume,
    QualificationLine,
    SummaryDraft,
    Work,
)
from pipeline_core import master_fact_index
from render import ScoredResume

QualificationState = Literal[
    "covered", "covered_with_substitution", "unsupported", "supported_not_on_page"
]
# Worst first: when one line is checked two ways, the worse result stands.
_SEVERITY = ("unsupported", "supported_not_on_page", "covered_with_substitution", "covered")
_PRESENT = frozenset({"", "present", "current", "now"})
_DOMAIN_STOPWORDS = frozenset(
    {"experience", "recent", "related", "field", "of", "in", "the", "or", "and", "a"}
)
_CREDITS_PER_YEAR = {"semester": 30, "quarter": 45}
_BACHELOR_RE = re.compile(r"\bbachelor|\bb\.?\s?s\.?\b|\bb\.?\s?a\.?\b", re.I)
_GRADUATE_RE = re.compile(
    r"\bmaster'?s?\b|\bm\.\s?s\.|\bmba\b|\bph\.?\s?d|\bdoctora", re.I
)
# Wording that accepts a degree still in progress; plain "completion of a
# degree" asks for a finished one.
_PENDING_DEGREE_RE = re.compile(
    r"imminent|expected|anticipated|pursuing|in progress|near completion"
    r"|completion of (?:the )?degree (?:will be )?considered",
    re.I,
)
# Titles that mark a role as hands-on technical work.
_TECHNICAL_TITLE_RE = re.compile(
    r"develop|engineer|programm|software|\bweb\b|devops|\bdata\b|scientist", re.I
)
# Domains that just mean "writing software"; any technical role counts.
_SOFTWARE_DOMAIN_WORDS = frozenset(
    {"web", "development", "developer", "programming", "software", "coding",
     "application", "applications", "computer", "technical"}
)


@dataclass
class QualificationStatus:
    text: str
    type: str
    status: QualificationState
    reason: str
    fact_ids: list[str] = field(default_factory=list)


def _month_index(value: str | None, *, end: bool) -> int | None:
    text = (value or "").strip()
    if not text[:4].isdigit():
        return None
    month = int(text[5:7]) if len(text) >= 7 and text[5:7].isdigit() else (12 if end else 1)
    return int(text[:4]) * 12 + month - 1


def _today_index(today: date) -> int:
    return today.year * 12 + today.month - 1


def _month_range(start: str | None, end: str | None, today: date) -> range:
    first = _month_index(start, end=False)
    if first is None:
        return range(0)
    if end is None or end.strip().casefold() in _PRESENT:
        last = _today_index(today)
    else:
        last = _month_index(end, end=True)
        if last is None:
            return range(0)
    return range(first, max(first, min(last, _today_index(today))))


def months_between(start: str | None, end: str | None, today: date) -> int:
    """Whole months from start to end (Present = today); never negative or future."""
    return len(_month_range(start, end, today))


def _is_technical_role(work: Work) -> bool:
    return bool(_TECHNICAL_TITLE_RE.search(work.position or ""))


def role_matches_domain(work: Work, domain: str | None) -> bool:
    """Whether a role counts toward experience in the line's domain.

    Judged from the job title, never from bullet wording ("developed" appears
    in every kind of role). No domain, or a domain that just means writing
    software, counts technical roles only.
    """
    words = [
        word
        for word in re.split(r"[/,\s]+|\band\b", (domain or "").casefold())
        if word and word not in _DOMAIN_STOPWORDS
    ]
    if not words or set(words) <= _SOFTWARE_DOMAIN_WORDS:
        return _is_technical_role(work)
    title = re.findall(r"[a-z]+", (work.position or "").casefold())
    return any(word.startswith(stem[:5]) for stem in words for word in title)


def experience_months(master: JSONResume, domain: str | None, today: date) -> int:
    """Months in matching roles, overlapping roles counted once."""
    months: set[int] = set()
    for work in master.work or []:
        if role_matches_domain(work, domain):
            months.update(_month_range(work.startDate, work.endDate, today))
    return len(months)


def years_label(months: int) -> str:
    """Whole years, "+" for extra months, never rounded up."""
    years, extra = divmod(months, 12)
    if years == 0:
        return "less than 1 year"
    unit = "year" if years == 1 and not extra else "years"
    return f"{years}{'+' if extra else ''} {unit}"


def _span(months: int) -> str:
    years, extra = divmod(months, 12)
    parts = []
    if years:
        parts.append(f"{years} year{'s' if years != 1 else ''}")
    if extra or not years:
        parts.append(f"{extra} month{'s' if extra != 1 else ''}")
    return " ".join(parts)


def substitution_years(education: Sequence[Education] | None) -> float:
    """Completed credits as years: 30 semester or 45 quarter credits per year."""
    return sum(
        (item.credits_completed or 0) / _CREDITS_PER_YEAR[item.credit_system]
        for item in education or []
    )


def _worse(first: QualificationStatus, second: QualificationStatus) -> QualificationStatus:
    return min(first, second, key=lambda item: _SEVERITY.index(item.status))


def assess_experience(
    line: QualificationLine, master: JSONResume, jd: JDProfile, today: date
) -> QualificationStatus:
    domain = line.domain or "work"
    months = experience_months(master, line.domain, today)
    if line.years is None or months / 12 >= line.years:
        return QualificationStatus(
            line.text, line.type, "covered", f"{_span(months)} of {domain}"
        )
    shortfall = f"posting asks {line.years:g} years; master shows {_span(months)} of {domain}"
    extra = substitution_years(master.education) if jd.allows_substitution else 0.0
    if extra and months / 12 + extra >= line.years:
        degree_lines = [
            item
            for item in (*jd.minimum_qualifications, *jd.preferred_qualifications)
            if item.type == "degree"
        ]
        if degree_lines:
            return QualificationStatus(
                line.text,
                line.type,
                "unsupported",
                "covered only with substitution; your degree is used for the degree "
                f"line ({shortfall})",
            )
        return QualificationStatus(
            line.text,
            line.type,
            "covered_with_substitution",
            f"{_span(months)} of {domain} plus {extra:g} years from completed credits",
        )
    return QualificationStatus(line.text, line.type, "unsupported", shortfall)


def assess_degree(
    line: QualificationLine, master: JSONResume, jd: JDProfile, today: date
) -> QualificationStatus:
    if _GRADUATE_RE.search(line.text):
        graduate = [
            item for item in master.education or [] if _GRADUATE_RE.search(item.studyType or "")
        ]
        if not graduate:
            status = QualificationStatus(
                line.text,
                line.type,
                "unsupported",
                "posting asks for a graduate degree; your education lists none",
            )
            if line.years is not None:
                status = _worse(status, assess_experience(line, master, jd, today))
            return status
    degrees = [
        item for item in master.education or [] if _BACHELOR_RE.search(item.studyType or "")
    ]
    if not degrees:
        status = QualificationStatus(
            line.text, line.type, "unsupported", "no bachelor's degree in your education"
        )
    else:
        latest = max(degrees, key=lambda item: _month_index(item.endDate, end=True) or 0)
        finished = _month_index(latest.endDate, end=True)
        if finished is not None and finished > _today_index(today) and not _PENDING_DEGREE_RE.search(line.text):
            when = date(finished // 12, finished % 12 + 1, 1).strftime("%b %Y")
            status = QualificationStatus(
                line.text,
                line.type,
                "unsupported",
                f"degree expected {when}; posting asks for a completed degree",
            )
        else:
            status = QualificationStatus(
                line.text, line.type, "covered", f"{latest.studyType}, {latest.area or ''}".rstrip(", ")
            )
    if line.years is not None:
        status = _worse(status, assess_experience(line, master, jd, today))
    return status


# -- coverage of every posted line -------------------------------------------

_COVERED = frozenset({"covered", "covered_with_substitution"})


def _page_text(plain: JSONResume) -> str:
    parts: list[str] = []
    if plain.basics and plain.basics.summary:
        parts.append(plain.basics.summary)
    for entries in (plain.work or [], plain.projects or []):
        for entry in entries:
            parts.extend(entry.highlights or [])
    for group in plain.skills or []:
        parts.extend(group.keywords or [])
    for item in plain.education or []:
        parts.extend(filter(None, [item.studyType, item.area]))
    return "\n".join(parts)


def rendered_source_ids(scored: ScoredResume, plain: JSONResume) -> set[str]:
    """Fact ids behind bullets that actually reached the page."""
    on_page = {
        text
        for entries in (plain.work or [], plain.projects or [])
        for entry in entries
        for text in entry.highlights or []
    }
    return {
        fact_id
        for entries in (scored.work or [], scored.projects or [])
        for entry in entries
        for bullet in entry.highlights or []
        if bullet.text in on_page
        for fact_id in bullet.source_ids
    }


def _qualification_fact_ids(
    line: QualificationLine, requirements: Sequence[dict], plan: EvidencePlan
) -> list[str]:
    keys = {normalize_term(line.text)}
    keys.update(item["id"] for item in requirements if item["term"] == line.text)
    return [
        fact_id
        for assignment in plan.assignments
        if keys
        & (
            {normalize_term(value) for value in assignment.matched_requirements}
            | set(assignment.matched_requirements)
        )
        for fact_id in assignment.source_fact_ids
    ]


def _technical(line: QualificationLine, master: JSONResume) -> QualificationStatus:
    if not line.named_terms:
        return QualificationStatus(
            line.text, line.type, "unsupported", "names no tool or standard to check"
        )
    facts = "\n".join(fact["text"] for fact in master_fact_index(master).values())
    absent = [term for term in line.named_terms if not mentions(facts, term_variants(term))]
    if absent:
        return QualificationStatus(
            line.text,
            line.type,
            "unsupported",
            "not in your resume: "
            + ", ".join(absent)
            + " (tick it in the skill check if you know it)",
        )
    return QualificationStatus(line.text, line.type, "covered", "named in your resume")


def _row(status: QualificationStatus, required: bool, page_terms: list[str], fact_ids: list[str]) -> dict:
    return {
        "text": status.text,
        "type": status.type,
        "required": required,
        "status": status.status,
        "reason": status.reason,
        "page_terms": page_terms,
        "fact_ids": fact_ids,
    }


def recheck_on_page(
    rows: Sequence[dict], scored: ScoredResume, plain: JSONResume
) -> list[dict]:
    """Downgrade covered lines whose proof did not survive editing or trimming."""
    text = _page_text(plain)
    rendered = rendered_source_ids(scored, plain)
    result: list[dict] = []
    for row in rows:
        row = dict(row)
        if row["status"] in _COVERED:
            missing_terms = [
                term for term in row.get("page_terms", []) if not mentions(text, term_variants(term))
            ]
            fact_ids = row.get("fact_ids", [])
            if missing_terms:
                row["status"] = "supported_not_on_page"
                row["reason"] = "true, but the page does not show: " + ", ".join(missing_terms)
            elif fact_ids and not rendered & set(fact_ids):
                row["status"] = "supported_not_on_page"
                row["reason"] = "true, but the bullet that shows it was cut"
        result.append(row)
    return result


def qualification_coverage(
    final_resume: ScoredResume,
    plain: JSONResume,
    jd: JDProfile,
    master: JSONResume,
    plan: EvidencePlan,
    requirements: Sequence[dict],
    today: date,
) -> list[dict]:
    """One row per posted minimum and preferred line: covered or why not."""
    rows: list[dict] = []
    for required, lines in ((True, jd.minimum_qualifications), (False, jd.preferred_qualifications)):
        for line in lines:
            page_terms: list[str] = []
            fact_ids: list[str] = []
            if line.type == "experience_length":
                status = assess_experience(line, master, jd, today)
                if status.status == "covered":
                    page_terms = [years_label(experience_months(master, line.domain, today))]
            elif line.type == "degree":
                status = assess_degree(line, master, jd, today)
                degree = next((item.studyType for item in master.education or [] if item.studyType), None)
                page_terms = [degree] if degree else []
                if line.years is not None:
                    # The years half must show too, not only the degree name.
                    page_terms.append(years_label(experience_months(master, line.domain, today)))
            elif line.type == "technical":
                status = _technical(line, master)
                page_terms = list(line.named_terms)
            else:
                fact_ids = _qualification_fact_ids(line, requirements, plan)
                status = (
                    QualificationStatus(line.text, line.type, "covered", "shown by a bullet")
                    if fact_ids
                    else QualificationStatus(line.text, line.type, "unsupported", "no fact shows this")
                )
            rows.append(_row(status, required, page_terms, fact_ids))
    return recheck_on_page(rows, final_resume, plain)


# -- summary -----------------------------------------------------------------

_NUMBER_WORDS = (
    "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|several|"
    "many|multiple|numerous"
)
_YEARS_RE = re.compile(
    rf"(?:less than\s+)?\b(?:\d+|{_NUMBER_WORDS})\+?\s+years?\b", re.I
)
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_LINE_PREFIX_RE = re.compile(r"^(?:requires|required|must have|preferred)\s+", re.I)
_TRAILING_RE = re.compile(r"[\s,;.:]*(?:\b(?:and|or|with|of|the|a)\b[\s,;.:]*)*$", re.I)
MAX_SUMMARY_WORDS = 60


def validate_summary(
    draft: SummaryDraft,
    title: str,
    years: str,
    fact_index: Mapping[str, dict],
    unsupported_terms: Sequence[str] = (),
) -> list[str]:
    """Problems that keep a summary off the page.

    ``unsupported_terms`` are technologies and standards the master never
    states; the summary may not name them.
    """
    problems: list[str] = []
    text = draft.text
    if title.casefold() not in text.casefold():
        problems.append(f"must name the posting title {title!r}")
    stated = _YEARS_RE.findall(text)
    if stated and any(value.casefold() != years.casefold() for value in stated):
        problems.append(f"states years {stated}; use exactly {years!r}")
    unknown = [fact_id for fact_id in draft.source_fact_ids if fact_id not in fact_index]
    if unknown:
        problems.append(f"cites facts that do not exist: {unknown}")
    cited = " ".join(fact_index[fact_id]["text"] for fact_id in draft.source_fact_ids if fact_id in fact_index)
    claimed = [term for term in unsupported_terms if mentions(text, term_variants(term))]
    if claimed:
        problems.append(f"names what your resume does not show: {claimed}")
    allowed = set(_NUMBER_RE.findall(f"{years} {cited} {title}"))
    invented = sorted(set(_NUMBER_RE.findall(text)) - allowed)
    if invented:
        problems.append(f"states numbers no fact gives: {invented}")
    if len(text.split()) > MAX_SUMMARY_WORDS:
        problems.append(f"must be {MAX_SUMMARY_WORDS} words or fewer")
    return problems


def _short_phrase(line: str) -> str:
    words = _LINE_PREFIX_RE.sub("", line.strip()).split()[:6]
    phrase = _TRAILING_RE.sub("", " ".join(words))
    if phrase[:1].isupper() and phrase[1:2].islower():
        phrase = phrase[0].lower() + phrase[1:]
    return phrase


def fallback_summary(title: str, years: str, domain: str | None, covered: Sequence[str]) -> str:
    """Summary built in code when the model's version fails validation."""
    phrases = [phrase for phrase in (_short_phrase(line) for line in covered[:3]) if phrase]
    tail = f" across {', '.join(phrases)}" if phrases else ""
    return f"{title} candidate with {years} of {domain or 'technical'} experience{tail}."
