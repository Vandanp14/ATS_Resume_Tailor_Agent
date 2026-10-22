"""Experience length, degree, and substitution for college qualification lines."""

from __future__ import annotations

from datetime import date

from models import JDProfile, JSONResume, QualificationLine
from resume_tailor.qualifications import (
    assess_degree,
    assess_experience,
    experience_months,
    months_between,
    substitution_years,
    years_label,
)

TODAY = date(2026, 10, 21)


def _master(credits: int | None = None) -> JSONResume:
    return JSONResume.model_validate(
        {
            "basics": {"name": "Test User"},
            "education": [
                {
                    "institution": "SUNY Oswego",
                    "studyType": "Bachelor of Science",
                    "area": "Computer Science",
                    "endDate": "2026-12",
                    **({"credits_completed": credits} if credits is not None else {}),
                }
            ],
            "work": [
                {"name": "Fanatics", "position": "Software Engineering Intern", "startDate": "2026-06", "endDate": "Present",
                 "highlights": ["Developed product-configuration workflows in Elixir."]},
                {"name": "Facilities", "position": "Software Developer Intern", "startDate": "2024-04", "endDate": "2026-04",
                 "highlights": ["Built React dashboards."]},
                {"name": "Institutional Research", "position": "Data Analyst Intern", "startDate": "2025-08", "endDate": "2025-12",
                 "highlights": ["Developed Python and SQL pipelines."]},
                {"name": "Major Projects", "position": "Project Analyst", "startDate": "2023-11", "endDate": "2024-04",
                 "highlights": ["Implemented Jira-based Gantt tracking."]},
                {"name": "Help Desk", "position": "Help Desk Attendant", "startDate": "2023-02", "endDate": "2023-05",
                 "highlights": ["Resolved Tier-1 and Tier-2 support issues."]},
            ],
        }
    )


def _jd(*lines: QualificationLine, substitution: bool = False) -> JDProfile:
    return JDProfile(
        role="UX/UI Developer",
        must_have_skills=[],
        nice_to_have_skills=[],
        keywords=[],
        minimum_qualifications=list(lines),
        allows_substitution=substitution,
    )


def _experience(years: float, domain: str | None = "web development/programming") -> QualificationLine:
    return QualificationLine(
        text=f"{years} years recent web development/programming experience.",
        type="experience_length",
        years=years,
        domain=domain,
    )


def test_web_development_months_union():
    months = experience_months(_master(), "web development/programming", TODAY)
    assert months == 28
    assert years_label(28) == "2+ years"
    assert years_label(24) == "2 years"
    assert years_label(12) == "1 year"
    assert years_label(7) == "less than 1 year"


def test_months_never_negative_or_future():
    assert months_between("2027-01", None, TODAY) == 0
    assert months_between("2024", "2024", TODAY) == 11
    assert months_between(None, "2025-01", TODAY) == 0
    assert months_between("2026-06", "2030-01", TODAY) == 4
    assert months_between("2026-06", "Present", TODAY) == 4


def test_two_years_line_is_covered():
    line = _experience(2)
    assert assess_experience(line, _master(), _jd(line), TODAY).status == "covered"


def test_three_years_line_is_flagged_with_reason():
    line = _experience(3)
    status = assess_experience(line, _master(), _jd(line), TODAY)
    assert status.status == "unsupported"
    assert "2 years 4 months" in status.reason and "3" in status.reason


def test_substitution_only_when_posting_allows():
    line = _experience(4)
    assert substitution_years(_master(90).education) == 3.0
    assert assess_experience(line, _master(90), _jd(line), TODAY).status == "unsupported"
    allowed = assess_experience(line, _master(90), _jd(line, substitution=True), TODAY)
    assert allowed.status == "covered_with_substitution"


def test_quarter_credits_use_45_per_year():
    master = _master(90)
    master.education[0].credit_system = "quarter"
    assert substitution_years(master.education) == 2.0


def test_degree_plus_years_line_not_double_counted():
    line = QualificationLine(
        text="Bachelor's degree and four years of experience, or an equivalent combination.",
        type="degree",
        years=4,
        domain="web development/programming",
    )
    status = assess_experience(line, _master(90), _jd(line, substitution=True), TODAY)
    assert status.status == "unsupported"
    assert "covered only with substitution" in status.reason


def test_expected_degree_needs_imminent_wording():
    required = QualificationLine(text="Bachelor's degree in Computer Science.", type="degree")
    status = assess_degree(required, _master(), _jd(required), TODAY)
    assert status.status == "unsupported"
    assert "Dec 2026" in status.reason
    preferred = QualificationLine(
        text="Preferred bachelor's degree in Computer Science (imminent completion of degree considered.)",
        type="degree",
    )
    assert assess_degree(preferred, _master(), _jd(preferred), TODAY).status == "covered"
