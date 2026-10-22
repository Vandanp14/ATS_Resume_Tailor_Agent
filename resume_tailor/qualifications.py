"""College qualification lines checked in code: experience, degree, substitution.

Years of experience are counted from the master's own work dates, never from a
model, so the number a screener sees is one the candidate can defend.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from models import Education, JDProfile, JSONResume, QualificationLine, Work

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
_PENDING_DEGREE_RE = re.compile(r"imminent|expected|anticipated|completion", re.I)


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


def _domain_stems(domain: str | None) -> list[str]:
    words = re.split(r"[/,\s]+|\band\b", (domain or "").casefold())
    return [word[:5] for word in words if word and word not in _DOMAIN_STOPWORDS]


def role_matches_domain(work: Work, domain: str | None) -> bool:
    """Whether a role's title or bullets show work in the line's domain."""
    stems = _domain_stems(domain)
    if not stems:
        return bool(work.position)
    words = re.findall(
        r"[a-z]+", " ".join([work.position or "", *(work.highlights or [])]).casefold()
    )
    return any(word.startswith(stem) for stem in stems for word in words)


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
