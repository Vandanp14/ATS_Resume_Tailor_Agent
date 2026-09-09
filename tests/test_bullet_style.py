from pipeline_core import (
    BANNED_OPENER_PHRASES,
    RESTRICTED_VERBS,
    scan_bullet_style,
    scan_metric_quality,
)
from models import ScoredBullet, ScoredProject, ScoredWork
from render import ScoredResume


def _resume(work_texts, project_texts):
    work = [
        ScoredWork(
            name=f"Company {i}",
            position="Engineer",
            relevance=50,
            highlights=[ScoredBullet(text=t, relevance=50) for t in texts],
        )
        for i, texts in enumerate(work_texts)
    ]
    projects = [
        ScoredProject(
            name=f"Project {i}",
            relevance=50,
            highlights=list(texts),
        )
        for i, texts in enumerate(project_texts)
    ]
    return ScoredResume(work=work, projects=projects)


def test_clean_bullets_produce_no_findings():
    resume = _resume(
        [["Built a React dashboard enabling real-time KPI visibility."]],
        [["Redesigned the checkout flow, reducing abandoned carts."]],
    )
    assert scan_bullet_style(resume) == []


def test_banned_opener_phrase_is_detected_case_insensitively():
    resume = _resume([["Responsible for onboarding new engineers."]], [])
    findings = scan_bullet_style(resume)
    assert len(findings) == 1
    assert "Work[0] bullet 1" in findings[0]
    assert "responsible for" in findings[0]


def test_each_banned_phrase_is_flagged():
    resume = _resume(
        [["Worked on the payments API."], ["Helped with QA testing."]], []
    )
    findings = scan_bullet_style(resume)
    assert len(findings) == 2
    for phrase in ("worked on", "helped with"):
        assert any(phrase in f for f in findings)


def test_restricted_verb_opener_is_flagged():
    resume = _resume([["Led the platform migration to Kubernetes."]], [])
    findings = scan_bullet_style(resume)
    assert len(findings) == 1
    assert "restricted verb" in findings[0]
    assert "'led'" in findings[0]


def test_repetitive_openers_flagged_once_per_section():
    resume = _resume(
        [
            [
                "Built the auth service.",
                "Built the reporting service.",
                "Built the billing service.",
            ]
        ],
        [],
    )
    findings = scan_bullet_style(resume)
    assert len(findings) == 1
    assert "Work[0] opens 3 bullets with the same verb 'built'" in findings[0]


def test_repetition_tracks_per_section():
    resume = _resume(
        [["Built the auth service."], ["Built the reporting service."]],
        [["Built the billing service."]],
    )
    assert scan_bullet_style(resume) == []


def test_scan_is_warn_only_never_raises():
    resume = _resume(
        [["Responsible for x."], ["Led y."], ["Built z."], ["Built w."]],
        [["Worked on q."]],
    )
    findings = scan_bullet_style(resume)
    assert isinstance(findings, list)
    assert len(findings) >= 3


def test_banned_phrase_with_punctuation_and_case():
    resume = _resume([["Participated in design reviews."]], [])
    findings = scan_bullet_style(resume)
    assert len(findings) == 1
    assert "participated in" in findings[0]


def test_restricted_verb_is_caught_away_from_the_opening_word():
    # The reviewed output's own example: a tier-3 verb smuggled in mid-sentence
    # by pairing it with a weak one. Checking only the first token missed it.
    resume = _resume(
        [["Designed and architected 5 read-only REST endpoints for the team."]], []
    )
    findings = scan_bullet_style(resume)
    assert any("architected" in finding for finding in findings)


def test_repeated_trailing_result_clause_is_flagged():
    resume = _resume(
        [
            [
                "Built a reporting service, enabling faster month-end close.",
                "Wrote a reconciliation job, reducing manual review.",
            ]
        ],
        [],
    )
    findings = scan_bullet_style(resume)
    assert any("participial result clause" in finding for finding in findings)


def test_single_result_clause_is_allowed():
    resume = _resume(
        [
            [
                "Built a reporting service, enabling faster month-end close.",
                "Moved queue traffic onto RabbitMQ after the broker fell over.",
            ]
        ],
        [],
    )
    assert scan_bullet_style(resume) == []


def test_metric_scan_flags_numbers_a_reader_cannot_check():
    resume = _resume(
        [
            [
                "Served 82,000 records with a 36.5 ms query time and zero tuning.",
            ]
        ],
        [],
    )
    findings = scan_metric_quality(resume)
    joined = " ".join(findings)
    assert "no baseline" in joined
    assert "decimal precision" in joined
    assert "stacks" in joined
    assert "absolute qualifiers" in joined


def test_metric_scan_accepts_a_baselined_single_claim():
    resume = _resume(
        [["Held worst-case query time at 37 ms, within the team's 50 ms budget."]],
        [["Resolved 18 of the 22 open reconciliation defects."]],
    )
    assert scan_metric_quality(resume) == []
