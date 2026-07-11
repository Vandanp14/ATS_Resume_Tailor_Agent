"""Non-vacuous tests for the tailoring-pipeline prompt templates.

The strongest, mandatory test here parses the *worked-example* JSON baked into
each template and validates it against the ACTUAL Pydantic response model the
pipeline will decode into (`JDProfile`, `TailoredSummary`, `TailoredSkills`,
`TailoredWork`, `TailoredProjects`, `MatchReport`). A template whose example
drifts from its model — a missing `relevance`, a bare-string work highlight, an
out-of-range weight — fails here.

The remaining tests assert distinctive instruction content (not boilerplate any
unrelated template could satisfy): the shared truth-floor partial is included
exactly once where it belongs and nowhere else, `tailor_work` demonstrates
keyword mirroring WITHOUT fact invention with object-valued highlights, and
`match_score`'s example actually detects a truth violation.
"""

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from prompts.template_manager import TemplateManager
from models import (
    JDProfile,
    TailoredSummary,
    TailoredSkills,
    TailoredWork,
    TailoredProjects,
    MatchReport,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = REPO_ROOT / "prompts" / "templates"

# A distinctive sentence that lives ONLY in the shared partial, so counting its
# occurrences in a rendered template = counting how many times the partial was
# included.
PARTIAL_MARKER = "Girl Script Summer of Code"
PARTIAL_ATS_MARKER = "open-source contributions to OTHER people's projects"

# Realistic render context reused across templates.
JD_JSON = json.dumps(
    {
        "role": "Backend Engineer",
        "seniority": None,
        "domain": "payments",
        "must_have_skills": ["Python", "PostgreSQL", "REST APIs", "AWS"],
        "nice_to_have_skills": ["Kubernetes", "Go"],
        "keywords": [
            {"term": "distributed systems", "weight": 5},
            {"term": "payment processing", "weight": 5},
        ],
    },
    indent=2,
)
MASTER_JSON = json.dumps(
    {
        "basics": {"name": "Jordan Doe", "summary": "Backend engineer, 4 years."},
        "work": [{"name": "Acme Payments", "position": "Software Engineer"}],
        "skills": [{"name": "Languages", "keywords": ["Python", "Go"]}],
    },
    indent=2,
)

# name -> (render kwargs, worked-example response model or None)
TEMPLATE_SPECS = {
    "jd_parse": (
        {"jd_text": "Hiring a Backend Engineer for payments. Required: Python, AWS."},
        JDProfile,
    ),
    "tailor_summary": (
        {"jd_profile_json": JD_JSON, "master_json": MASTER_JSON},
        TailoredSummary,
    ),
    "tailor_skills": (
        {
            "jd_profile_json": JD_JSON,
            "master_skills_json": json.dumps(
                [{"name": "Languages", "keywords": ["Python", "Go"]}]
            ),
        },
        TailoredSkills,
    ),
    "tailor_work": (
        {
            "jd_profile_json": JD_JSON,
            "master_work_json": json.dumps(
                [{"name": "Acme Payments", "position": "Software Engineer"}]
            ),
        },
        TailoredWork,
    ),
    "tailor_projects": (
        {
            "jd_profile_json": JD_JSON,
            "master_projects_json": json.dumps(
                [{"name": "kafka-python", "url": "https://github.com/dpkp/kafka-python"}]
            ),
        },
        TailoredProjects,
    ),
    "match_score": (
        {
            "jd_profile_json": JD_JSON,
            "tailored_resume_json": MASTER_JSON,
            "master_json": MASTER_JSON,
        },
        MatchReport,
    ),
    "system_message": ({"stage": "work tailor"}, None),
}

# Templates that MUST include the shared truth-floor partial (neutral policy
# voice): the four section tailors AND the scorer/auditor.
TRUTH_FLOOR_TEMPLATES = [
    "tailor_summary",
    "tailor_skills",
    "tailor_work",
    "tailor_projects",
    "match_score",
]
# Templates that carry the second-person ATS-rubric *pressure* — the tailors
# only. The scorer must NOT get these imperatives (they would bias the audit).
ATS_PRESSURE_TEMPLATES = [
    "tailor_summary",
    "tailor_skills",
    "tailor_work",
    "tailor_projects",
]
# Templates that must NOT include any tailoring partial (no master facts to
# protect / not tailoring).
NON_PARTIAL_TEMPLATES = ["jd_parse", "system_message"]


@pytest.fixture(scope="module")
def tm() -> TemplateManager:
    return TemplateManager(template_dir=str(TEMPLATE_DIR))


def _render(tm: TemplateManager, name: str) -> str:
    kwargs, _ = TEMPLATE_SPECS[name]
    rendered = tm.render_template(name, **kwargs)
    assert rendered is not None, f"template {name!r} failed to render"
    return rendered


def _last_top_level_json(text: str) -> str:
    """Return the source of the LAST top-level ``{...}`` object in ``text``.

    A brace-depth scanner that ignores braces inside JSON strings. Every
    template ends with its worked-example output object (the final reminder line
    carries no braces), so the last top-level object is always that example —
    never the earlier schema-reference block, whose placeholder string values
    (e.g. ``"weight": "integer 1-5"``) would not validate.
    """
    spans = []
    depth = 0
    start = None
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                spans.append((start, i + 1))
                start = None
    assert spans, "no top-level JSON object found in rendered template"
    s, e = spans[-1]
    return text[s:e]


# --- registration -----------------------------------------------------------


def test_all_expected_templates_registered(tm: TemplateManager):
    available = set(tm.get_available_sections())
    assert set(TEMPLATE_SPECS) == available, (
        f"registered sections {available} != expected {set(TEMPLATE_SPECS)}"
    )
    # The shared partial is a helper include, NOT a standalone renderable section.
    assert "_tailoring_rules" not in available


# --- the strongest test: worked example validates against the real model -----


@pytest.mark.parametrize(
    "name",
    [n for n, (_, model) in TEMPLATE_SPECS.items() if model is not None],
)
def test_worked_example_validates_against_model(tm: TemplateManager, name: str):
    _, model = TEMPLATE_SPECS[name]
    rendered = _render(tm, name)
    example_src = _last_top_level_json(rendered)
    data = json.loads(example_src)  # must be strict, valid JSON
    instance = model.model_validate(data)  # must satisfy the actual response model
    assert isinstance(instance, BaseModel)


def test_jd_parse_example_captures_weighted_keywords(tm: TemplateManager):
    jd = JDProfile.model_validate(
        json.loads(_last_top_level_json(_render(tm, "jd_parse")))
    )
    assert jd.role == "Backend Engineer"
    assert "Python" in jd.must_have_skills
    # Weighted keywords present and every weight in the 1-5 band the model enforces.
    assert jd.keywords, "example must demonstrate at least one weighted keyword"
    assert all(1 <= kw.weight <= 5 for kw in jd.keywords)


def test_tailor_skills_example_every_group_scored_and_level_null(tm: TemplateManager):
    ts = TailoredSkills.model_validate(
        json.loads(_last_top_level_json(_render(tm, "tailor_skills")))
    )
    assert len(ts.skills) >= 2
    # relevance present on every group; ordered most- to least-relevant.
    relevances = [s.relevance for s in ts.skills]
    assert relevances == sorted(relevances, reverse=True)
    assert all(s.level is None for s in ts.skills)  # never invents a proficiency


def test_tailor_work_example_uses_object_bullets_and_preserves_facts(tm):
    rendered = _render(tm, "tailor_work")
    tw = TailoredWork.model_validate(json.loads(_last_top_level_json(rendered)))
    entry = tw.work[0]
    # Employer / title / dates preserved verbatim from the master excerpt.
    assert entry.name == "Acme Payments"
    assert entry.position == "Software Engineer"
    assert entry.startDate == "2021-03"  # copied verbatim from the JSON master
    assert entry.endDate is None  # master has no endDate -> stays null
    # highlights are ScoredBullet OBJECTS with text + relevance, not bare strings.
    assert entry.highlights and all(b.text and 0 <= b.relevance <= 100 for b in entry.highlights)
    joined = " ".join(b.text for b in entry.highlights)
    # Keyword mirroring happened (JD spelling "PostgreSQL" surfaced)...
    assert "PostgreSQL" in joined
    # ...but the headline JD keyword the master never supports was NOT fabricated.
    assert "distributed systems" not in joined.lower()
    # No invented metric appears in the reworded bullets.
    assert "%" not in joined


def test_tailor_work_instructs_object_highlights_and_no_fabrication(tm):
    rendered = _render(tm, "tailor_work")
    assert "highlights are OBJECTS, not strings" in rendered
    assert "copied VERBATIM from the master" in rendered
    # The distinctive restraint lesson: mirror keywords, never add facts.
    assert "would be fabrication" in rendered


def test_tailor_projects_example_keeps_links_and_ranks_tutorial_last(tm):
    rendered = _render(tm, "tailor_projects")
    tp = TailoredProjects.model_validate(json.loads(_last_top_level_json(rendered)))
    assert len(tp.projects) >= 2
    # Ordered by relevance, open-source contribution first.
    assert tp.projects[0].relevance >= tp.projects[-1].relevance
    assert tp.projects[0].url and tp.projects[0].url.startswith("http")  # link kept
    # Tutorial-grade project ranked last and its (missing) link stays null.
    assert tp.projects[-1].relevance <= 30
    assert tp.projects[-1].url is None  # no fabricated link


def test_match_score_example_detects_one_truth_violation(tm):
    rendered = _render(tm, "match_score")
    report = MatchReport.model_validate(json.loads(_last_top_level_json(rendered)))
    assert 0 <= report.coverage_pct <= 100
    # The worked example demonstrates exactly one truth-violation detection...
    assert len(report.truth_violations) == 1
    violation = report.truth_violations[0]
    assert violation.section and violation.claim and violation.reason
    # ...and distinguishes a genuine gap (missing must-have) from a fabrication.
    assert report.missing_must_haves, "example must show a gap that was NOT fabricated"


# --- shared partial is included once, and only where it belongs --------------


@pytest.mark.parametrize("name", TRUTH_FLOOR_TEMPLATES)
def test_truth_floor_included_exactly_once(tm: TemplateManager, name: str):
    rendered = _render(tm, name)
    assert rendered.count(PARTIAL_MARKER) == 1, (
        f"{name} must include the truth-floor partial exactly once"
    )


@pytest.mark.parametrize("name", ATS_PRESSURE_TEMPLATES)
def test_ats_pressure_rides_along_with_the_tailors(tm: TemplateManager, name: str):
    rendered = _render(tm, name)
    assert PARTIAL_ATS_MARKER in rendered


def test_match_score_gets_truth_floor_but_not_tailoring_imperatives(tm: TemplateManager):
    # The scorer is an auditor: it needs the truth-floor RULES to check against,
    # but must NOT be handed the second-person "you are the tailor, rewrite
    # aggressively / bias toward what the evaluator rewards" imperatives, which
    # would soften the audit (finding 14).
    rendered = _render(tm, "match_score")
    assert PARTIAL_MARKER in rendered  # truth floor present (incl. GSSoC≠GSoC rule)
    assert PARTIAL_ATS_MARKER not in rendered  # ATS pressure NOT present
    assert "Rewrite aggressively" not in rendered
    assert "bias selection, ordering, and emphasis" not in rendered


@pytest.mark.parametrize("name", NON_PARTIAL_TEMPLATES)
def test_partial_not_included_where_inapplicable(tm: TemplateManager, name: str):
    rendered = _render(tm, name)
    assert PARTIAL_MARKER not in rendered
    assert PARTIAL_ATS_MARKER not in rendered


def test_partial_states_truth_floor_and_forbidden_fabrications(tm: TemplateManager):
    # Render via a host template so the include resolves.
    rendered = _render(tm, "tailor_summary")
    assert "truth floor" in rendered.lower()
    for forbidden in [
        "Inventing employers, job titles, or employment dates.",
        "Inventing metrics, numbers, percentages, or dates",
    ]:
        assert forbidden in rendered


# --- re-run feedback block is conditional ------------------------------------


@pytest.mark.parametrize("name", ["tailor_summary", "tailor_skills", "tailor_work", "tailor_projects"])
def test_feedback_block_is_conditional(tm: TemplateManager, name: str):
    without = _render(tm, name)
    assert "Revision feedback" not in without

    kwargs, _ = TEMPLATE_SPECS[name]
    with_fb = tm.render_template(
        name, feedback="Coverage was 60%; surface the Kubernetes experience.", **kwargs
    )
    assert "Revision feedback" in with_fb
    assert "surface the Kubernetes experience" in with_fb


# --- system message ----------------------------------------------------------


def test_system_message_is_json_only_and_stage_aware(tm: TemplateManager):
    rendered = _render(tm, "system_message")
    assert "ONLY valid JSON" in rendered
    assert "WITHOUT inventing any facts" in rendered
    assert "work tailor stage" in rendered  # stage interpolated
    # Renders cleanly with no stage too.
    no_stage = tm.render_template("system_message")
    assert "stage of the pipeline" not in no_stage
