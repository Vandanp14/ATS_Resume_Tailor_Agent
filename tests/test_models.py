"""Validation + round-trip tests for the new tailoring-pipeline models.

Every new model validates a realistic fixture dict and rejects a specific
invalid one (out-of-range score, missing required field, wrong nested shape).
The strip_relevance_* helpers are checked for exact field preservation and
correct collapse of scored bullets back to plain strings.
"""

import pytest
from pydantic import BaseModel, ValidationError

from models import (
    Skill,
    Work,
    Project,
    KeywordWeight,
    JDProfile,
    TailoredSummary,
    ScoredSkill,
    ScoredBullet,
    ScoredWork,
    ScoredProject,
    TailoredSkills,
    TailoredWork,
    TailoredProjects,
    TruthViolation,
    MatchReport,
    strip_relevance_skill,
    strip_relevance_work,
    strip_relevance_project,
    strip_relevance_skills,
    strip_relevance_work_list,
    strip_relevance_projects,
)


# --- KeywordWeight ----------------------------------------------------------


def test_keyword_weight_valid():
    kw = KeywordWeight(term="kubernetes", weight=5)
    assert kw.term == "kubernetes"
    assert kw.weight == 5


@pytest.mark.parametrize("bad_weight", [0, 6, -1])
def test_keyword_weight_rejects_out_of_range(bad_weight):
    with pytest.raises(ValidationError):
        KeywordWeight(term="x", weight=bad_weight)


# --- JDProfile --------------------------------------------------------------


VALID_JD = {
    "role": "Senior Backend Engineer",
    "seniority": "senior",
    "domain": "fintech",
    "must_have_skills": ["Python", "PostgreSQL", "Kubernetes"],
    "nice_to_have_skills": ["Go", "gRPC"],
    "keywords": [
        {"term": "distributed systems", "weight": 5},
        {"term": "REST APIs", "weight": 3},
    ],
}


def test_jdprofile_round_trips_valid_fixture():
    jd = JDProfile(**VALID_JD)
    assert jd.role == "Senior Backend Engineer"
    assert jd.must_have_skills == ["Python", "PostgreSQL", "Kubernetes"]
    assert jd.keywords[0].weight == 5
    # Optional scalars may be omitted.
    minimal = JDProfile(
        role="Intern", must_have_skills=[], nice_to_have_skills=[], keywords=[]
    )
    assert minimal.seniority is None


def test_jdprofile_rejects_missing_required_role():
    bad = {k: v for k, v in VALID_JD.items() if k != "role"}
    with pytest.raises(ValidationError):
        JDProfile(**bad)


def test_jdprofile_rejects_bad_nested_keyword_weight():
    bad = {**VALID_JD, "keywords": [{"term": "x", "weight": 99}]}
    with pytest.raises(ValidationError):
        JDProfile(**bad)


# --- TailoredSummary --------------------------------------------------------


def test_tailored_summary_valid_and_invalid():
    assert TailoredSummary(summary="Backend engineer with 5 years...").summary
    with pytest.raises(ValidationError):
        TailoredSummary()  # summary is required


# --- Scored* item wrappers --------------------------------------------------


def test_scored_skill_valid_and_range_enforced():
    s = ScoredSkill(name="Backend", keywords=["Python", "Go"], relevance=90)
    assert s.relevance == 90
    assert s.keywords == ["Python", "Go"]
    with pytest.raises(ValidationError):
        ScoredSkill(name="Backend", relevance=101)


def test_scored_bullet_valid_and_range_enforced():
    b = ScoredBullet(text="Built X serving 1M users", relevance=0)
    assert b.relevance == 0
    with pytest.raises(ValidationError):
        ScoredBullet(text="x", relevance=-1)


def test_scored_work_valid_with_nested_bullets():
    w = ScoredWork(
        name="Acme Corp",
        position="Engineer",
        startDate="2021-01",
        endDate="2023-06",
        relevance=85,
        highlights=[
            {"text": "Shipped payments service", "relevance": 95},
            {"text": "Mentored two juniors", "relevance": 40},
        ],
    )
    assert w.position == "Engineer"
    assert w.highlights[0].text == "Shipped payments service"
    assert w.highlights[1].relevance == 40


def test_scored_work_rejects_plain_string_highlights():
    # highlights is List[ScoredBullet], not List[str]; a bare string is invalid.
    with pytest.raises(ValidationError):
        ScoredWork(name="Acme", relevance=50, highlights=["just a string"])


def test_scored_project_valid_and_range_enforced():
    p = ScoredProject(
        name="opensource-cli",
        description="A CLI tool",
        url="https://github.com/u/opensource-cli",
        highlights=["1k stars"],
        relevance=70,
    )
    assert p.name == "opensource-cli"
    assert p.highlights == ["1k stars"]
    with pytest.raises(ValidationError):
        ScoredProject(name="x", relevance=200)


# --- Tailored* section wrappers ---------------------------------------------


def test_tailored_skills_wrapper():
    ts = TailoredSkills(skills=[{"name": "Backend", "relevance": 80}])
    assert ts.skills[0].relevance == 80
    with pytest.raises(ValidationError):
        TailoredSkills(skills=[{"name": "Backend", "relevance": 900}])


def test_tailored_work_wrapper():
    tw = TailoredWork(
        work=[{"name": "Acme", "position": "Eng", "relevance": 88, "highlights": []}]
    )
    assert tw.work[0].name == "Acme"
    with pytest.raises(ValidationError):
        TailoredWork(work="not-a-list")


def test_tailored_projects_wrapper():
    tp = TailoredProjects(projects=[{"name": "proj", "relevance": 60}])
    assert tp.projects[0].name == "proj"
    with pytest.raises(ValidationError):
        TailoredProjects(projects=[{"name": "proj", "relevance": -3}])


# --- TruthViolation + MatchReport -------------------------------------------


def test_truth_violation_valid_and_invalid():
    tv = TruthViolation(
        section="work",
        claim="Led a 20-person team",
        reason="Master resume shows no management role",
    )
    assert tv.section == "work"
    with pytest.raises(ValidationError):
        TruthViolation(section="work", claim="x")  # reason required


def test_match_report_round_trips_valid_fixture():
    report = MatchReport(
        coverage_pct=82.5,
        missing_must_haves=["Kubernetes"],
        weak_sections=["skills"],
        truth_violations=[
            {"section": "work", "claim": "Invented metric", "reason": "not in master"}
        ],
        notes="Coverage acceptable; one violation to fix.",
    )
    assert report.coverage_pct == 82.5
    assert report.truth_violations[0].section == "work"
    # notes is optional
    assert (
        MatchReport(
            coverage_pct=0,
            missing_must_haves=[],
            weak_sections=[],
            truth_violations=[],
        ).notes
        is None
    )


@pytest.mark.parametrize("bad_coverage", [-0.1, 100.1, 250])
def test_match_report_rejects_out_of_range_coverage(bad_coverage):
    with pytest.raises(ValidationError):
        MatchReport(
            coverage_pct=bad_coverage,
            missing_must_haves=[],
            weak_sections=[],
            truth_violations=[],
        )


# --- strip_relevance_* helpers ----------------------------------------------


def test_strip_relevance_skill_produces_plain_skill():
    scored = ScoredSkill(
        name="Backend", level="Advanced", keywords=["Go"], relevance=90
    )
    plain = strip_relevance_skill(scored)
    assert type(plain) is Skill
    assert plain.name == "Backend"
    assert plain.level == "Advanced"
    assert plain.keywords == ["Go"]
    assert not hasattr(plain, "relevance")


def test_strip_relevance_work_collapses_bullets_and_preserves_order():
    scored = ScoredWork(
        name="Acme",
        position="Engineer",
        startDate="2021-01",
        endDate="2023-06",
        summary="Backend work",
        url="https://acme.example",
        relevance=85,
        highlights=[
            {"text": "first bullet", "relevance": 95},
            {"text": "second bullet", "relevance": 30},
        ],
    )
    plain = strip_relevance_work(scored)
    assert type(plain) is Work
    assert plain.highlights == ["first bullet", "second bullet"]  # order preserved
    assert plain.name == "Acme"
    assert plain.position == "Engineer"
    assert plain.startDate == "2021-01"
    assert plain.url == "https://acme.example"
    assert not hasattr(plain, "relevance")


def test_strip_relevance_work_handles_none_highlights():
    scored = ScoredWork(name="Acme", position="Eng", relevance=50, highlights=None)
    assert strip_relevance_work(scored).highlights is None


def test_strip_relevance_project_preserves_link_and_tech():
    scored = ScoredProject(
        name="opensource-cli",
        description="A CLI tool",
        url="https://github.com/u/opensource-cli",
        technologies=["Python", "Click"],
        highlights=["1k stars"],
        relevance=70,
    )
    plain = strip_relevance_project(scored)
    assert type(plain) is Project
    assert (
        plain.url == "https://github.com/u/opensource-cli"
    )  # link survives (ATS rubric)
    assert plain.technologies == ["Python", "Click"]
    assert plain.highlights == ["1k stars"]
    assert not hasattr(plain, "relevance")


def test_strip_relevance_list_helpers():
    skills = strip_relevance_skills(
        TailoredSkills(
            skills=[{"name": "A", "relevance": 10}, {"name": "B", "relevance": 20}]
        )
    )
    assert [s.name for s in skills] == ["A", "B"]
    assert all(type(s) is Skill for s in skills)

    work = strip_relevance_work_list(
        TailoredWork(
            work=[
                {
                    "name": "W1",
                    "relevance": 5,
                    "highlights": [{"text": "b", "relevance": 1}],
                }
            ]
        )
    )
    assert work[0].highlights == ["b"]
    assert type(work[0]) is Work

    projects = strip_relevance_projects(
        TailoredProjects(projects=[{"name": "P1", "relevance": 9}])
    )
    assert [p.name for p in projects] == ["P1"]
    assert all(type(p) is Project for p in projects)
