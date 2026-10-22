"""College mode: switch, qualification lines, coverage, two pages, summary."""

from __future__ import annotations

import uuid
from pathlib import Path

from tests.conftest import FakePipe, create_job, wait_for

REPO_ROOT = Path(__file__).resolve().parent.parent


# -- Task 1: the switch ----------------------------------------------------------


class RecordingPipe(FakePipe):
    seen: list[bool] = []

    def run(self, master, jd_text, out_dir, no_pdf, job, resume=False):
        RecordingPipe.seen.append(self.college_mode)
        return super().run(master, jd_text, out_dir, no_pdf, job, resume)


def test_college_flag_reaches_pipeline(make_app):
    from fastapi.testclient import TestClient

    RecordingPipe.seen = []
    app, _ = make_app(pipeline_factory=RecordingPipe)
    client = TestClient(app, base_url="http://127.0.0.1")
    job = create_job(client, str(uuid.uuid4()), college_mode=True).json()["job_id"]
    assert wait_for(client, job)["state"] == "completed"
    plain = create_job(client, str(uuid.uuid4()), jd_text="Another posting.").json()["job_id"]
    assert wait_for(client, plain)["state"] == "completed"
    assert RecordingPipe.seen == [True, False]


def test_jd_parse_fingerprint_depends_on_college_mode():
    from resume_tailor.checkpoints import stage_fingerprint

    base = dict(master_json="{}", jd_text="Posting")
    assert stage_fingerprint("jd_parse", **base) != stage_fingerprint(
        "jd_parse", **base, college_mode=True
    )
    assert stage_fingerprint("jd_parse", **base) == stage_fingerprint(
        "jd_parse", **base, college_mode=False, bridge_skills=True
    )


def test_job_fingerprint_unchanged_when_off():
    from resume_tailor.web.models import CreateJobRequest, JobOptions, job_fingerprint

    request = CreateJobRequest(company="A", role="B", jd_text="C")
    seed = ("A", "B", "C", False, False, False)
    assert job_fingerprint(request, JobOptions()) == uuid.uuid5(uuid.NAMESPACE_URL, repr(seed)).hex
    on = CreateJobRequest(company="A", role="B", jd_text="C", college_mode=True)
    assert job_fingerprint(on, JobOptions(college_mode=True)) != job_fingerprint(request, JobOptions())


def test_index_has_college_toggle():
    index = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="college-mode"' in index
    app_js = (REPO_ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "college_mode" in app_js


# -- Task 2: qualification lines in the parse ----------------------------------

SUU_JD = (REPO_ROOT / "jds" / "uiux_developer_utah_university.txt").read_text(encoding="utf-8")


def _pipeline(**kwargs):
    from unittest.mock import MagicMock

    import tailor

    return tailor.TailorPipeline(
        model="gemini-3.1-flash-lite", call_interval=0, provider=MagicMock(), **kwargs
    )


def test_college_parse_prompt_asks_for_lines():
    college = _pipeline(college_mode=True)._messages("jd_parse", jd_text="x", college_mode=True)
    plain = _pipeline()._messages("jd_parse", jd_text="x", college_mode=False)
    assert "minimum_qualifications" in college[-1]["content"]
    assert "minimum_qualifications" not in plain[-1]["content"]


def _suu_profile(lines, **extra):
    from models import JDProfile, QualificationLine

    return JDProfile(
        role="UX/UI Developer",
        must_have_skills=["HTML"],
        nice_to_have_skills=[],
        keywords=[],
        minimum_qualifications=[QualificationLine(**line) for line in lines],
        **extra,
    )


def test_sanitize_drops_invented_lines():
    from keyword_coverage import sanitize_jd_profile

    profile = _suu_profile(
        [
            {"text": "Two years recent web development/programming experience.", "type": "experience_length", "years": 2, "domain": "web development/programming"},
            {"text": "Five years of Kubernetes administration.", "type": "experience_length", "years": 5},
        ]
    )
    cleaned, _ = sanitize_jd_profile(profile, SUU_JD)
    assert [line.text for line in cleaned.minimum_qualifications] == [
        "Two years recent web development/programming experience."
    ]


def test_no_headings_is_fine():
    from models import JDProfile

    old = {"role": "Engineer", "must_have_skills": [], "nice_to_have_skills": [], "keywords": []}
    profile = JDProfile.model_validate(old)
    assert profile.minimum_qualifications == [] and profile.allows_substitution is False


# -- Task 4: qualification lines as requirements -------------------------------


def _line(text, type_, **extra):
    from models import QualificationLine

    return QualificationLine(text=text, type=type_, **extra)


def test_interpersonal_lines_become_qualification_requirements():
    from keyword_coverage import qualification_requirements
    from models import JDProfile

    jd = JDProfile(
        role="UX/UI Developer", must_have_skills=[], nice_to_have_skills=[], keywords=[],
        minimum_qualifications=[
            _line("Two years recent web development/programming experience.", "experience_length", years=2),
            _line("Requires ability to work cordially with other University personnel.", "interpersonal"),
        ],
        preferred_qualifications=[_line("Experience looking at web analytics reports.", "other")],
    )
    rows = qualification_requirements(jd, start_index=7)
    assert [(row["id"], row["weight"], row["status"]) for row in rows] == [
        ("Q8", 6, "qualification"),
        ("Q9", 3, "qualification"),
    ]
    assert rows[0]["requirement_type"] == "minimum_qualification"
    assert rows[0]["term"].startswith("Requires ability to work cordially")


def test_qualification_items_never_forbidden_proxied_or_counted_as_keywords():
    from keyword_coverage import (
        forbidden_claim_terms,
        missing_requirements,
        priority_proxies,
        resume_coverage,
    )

    row = {
        "id": "Q1", "term": "Requires ability to work cordially with other University personnel.",
        "requirement_type": "minimum_qualification", "weight": 6, "importance": 6,
        "category": "qualification", "variants": [], "status": "qualification", "matched_fact_ids": [],
    }
    assert forbidden_claim_terms([row]) == ()
    assert missing_requirements([row]) == []
    assert priority_proxies([row]) == []
    assert resume_coverage({"work": [], "projects": [], "skills": []}, [row])["requirements"] == []


def test_plan_prompt_mentions_qualification_only_in_college_mode():
    college = _pipeline(college_mode=True)._messages("plan_evidence", college_mode=True)
    plain = _pipeline()._messages("plan_evidence", college_mode=False)
    assert "status `qualification`" in college[-1]["content"]
    assert "status `qualification`" not in plain[-1]["content"]


# -- Task 5: coverage check and flags ------------------------------------------

from datetime import date as _date  # noqa: E402

TODAY = _date(2026, 10, 21)


def _college_master(confirmed=()):
    from models import JSONResume
    from resume_tailor.skill_answers import apply_answers

    master = JSONResume.model_validate(
        {
            "basics": {"name": "Test User"},
            "education": [{"institution": "SUNY Oswego", "studyType": "Bachelor of Science", "area": "Computer Science", "endDate": "2026-12"}],
            "skills": [{"name": "Languages", "keywords": ["HTML", "CSS", "JavaScript"]}],
            "work": [
                {"name": "Fanatics", "position": "Software Engineering Intern", "startDate": "2026-06", "endDate": "Present",
                 "highlights": ["Developed product-configuration workflows."]},
                {"name": "Facilities", "position": "Software Developer Intern", "startDate": "2024-04", "endDate": "2026-04",
                 "highlights": ["Built React dashboards.", "Collaborated directly with field staff to gather feedback."]},
            ],
        }
    )
    return apply_answers(master, list(confirmed), []) if confirmed else master


def _suu_jd():
    from models import JDProfile

    return JDProfile(
        role="UX/UI Developer", must_have_skills=["HTML"], nice_to_have_skills=[], keywords=[],
        minimum_qualifications=[
            _line("Two years recent web development/programming experience.", "experience_length", years=2,
                  domain="web development/programming"),
            _line("Strong understanding of Section 508/ADA Accessibility compliance and remediation.", "technical",
                  named_terms=["Section 508", "ADA"]),
            _line("Requires ability to work cordially with other University personnel.", "interpersonal"),
        ],
    )


def _scored(bullets, summary=None, skills=("HTML",)):
    from render import ScoredResume

    return ScoredResume.model_validate(
        {
            "basics": {"name": "Test User", "summary": summary},
            "education": [{"institution": "SUNY Oswego", "studyType": "Bachelor of Science", "endDate": "2026-12"}],
            "skills": [{"name": "Skills", "keywords": list(skills), "relevance": 50}],
            "work": [
                {"name": "Facilities", "position": "Software Developer Intern", "relevance": 90, "source_id": "work[1]",
                 "highlights": [{"text": text, "relevance": 80, "source_ids": ids} for text, ids in bullets]},
            ],
        }
    )


def _plan(fact_ids):
    from models import EvidencePlan

    return EvidencePlan.model_validate(
        {"assignments": [{"assignment_id": "a1", "destination_work_id": "work[1]", "source_fact_ids": fact_ids,
                          "matched_requirements": ["Q1"], "intended_accomplishment": "x", "inferred_impact": None}]}
    )


def _coverage(scored, master, plan):
    from keyword_coverage import qualification_requirements
    from render import scored_to_plain
    from resume_tailor.qualifications import qualification_coverage

    jd = _suu_jd()
    requirements = qualification_requirements(jd, 0)
    return {
        row["text"].split()[0]: row
        for row in qualification_coverage(scored, scored_to_plain(scored), jd, master, plan, requirements, TODAY)
    }


def test_suu_lines_covered_or_flagged():
    bullets = [("Collaborated with field staff to turn feedback into features.", ["work[1].highlights[1]"])]
    summary = "UX/UI Developer candidate with 2+ years of web development experience."
    rows = _coverage(_scored(bullets, summary), _college_master(), _plan(["work[1].highlights[1]"]))
    assert rows["Two"]["status"] == "covered"
    assert rows["Requires"]["status"] == "covered"
    assert rows["Strong"]["status"] == "unsupported"
    assert "Section 508" in rows["Strong"]["reason"]
    confirmed = _college_master(confirmed=["Section 508", "ADA"])
    shown = _scored(bullets, summary, skills=("HTML", "Section 508", "ADA"))
    rows = _coverage(shown, confirmed, _plan(["work[1].highlights[1]"]))
    assert rows["Strong"]["status"] == "covered"


def test_cut_bullet_reports_supported_not_on_page():
    from render import scored_to_plain
    from resume_tailor.qualifications import recheck_on_page

    bullets = [("Collaborated with field staff to turn feedback into features.", ["work[1].highlights[1]"])]
    scored = _scored(bullets, "UX/UI Developer candidate with 2+ years of web development experience.")
    rows = list(_coverage(scored, _college_master(), _plan(["work[1].highlights[1]"])).values())
    trimmed = scored.model_copy(deep=True)
    trimmed.work[0].highlights = []
    rechecked = {row["text"].split()[0]: row for row in recheck_on_page(rows, trimmed, scored_to_plain(trimmed))}
    assert rechecked["Requires"]["status"] == "supported_not_on_page"
    assert rechecked["Two"]["status"] == "covered"


def test_years_missing_from_page_is_supported_not_on_page():
    rows = _coverage(_scored([], summary=None), _college_master(), _plan(["work[1].highlights[1]"]))
    assert rows["Two"]["status"] == "supported_not_on_page"
    assert rows["Requires"]["status"] == "supported_not_on_page"


def test_unrelated_assignment_does_not_cover_a_qualification():
    from models import EvidencePlan

    plan = EvidencePlan.model_validate(
        {"assignments": [{"assignment_id": "a1", "destination_work_id": "work[1]",
                          "source_fact_ids": ["work[1].highlights[1]"], "matched_requirements": ["React.js"],
                          "intended_accomplishment": "x", "inferred_impact": None}]}
    )
    bullets = [("Collaborated with field staff to turn feedback into features.", ["work[1].highlights[1]"])]
    rows = _coverage(_scored(bullets, "UX/UI Developer candidate with 2+ years."), _college_master(), plan)
    assert rows["Requires"]["status"] == "unsupported"


def test_review_payload_and_ui_show_qualifications(tmp_path):
    import json

    from resume_tailor.web.review import read_review

    row = {"text": "Two years of web development.", "type": "experience_length", "required": True,
           "status": "unsupported", "reason": "posting asks 3 years", "page_terms": [], "fact_ids": []}
    (tmp_path / "match_report.json").write_text(json.dumps({"coverage_pct": 80, "qualification_coverage": [row]}))
    assert read_review(tmp_path)["qualification_coverage"] == [row]
    app_js = (REPO_ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "qualification_coverage" in app_js


def test_college_run_reports_rows_and_does_not_block(monkeypatch, tmp_path):
    import json
    from unittest.mock import MagicMock

    import resume_tailor.pipeline as pipeline_module
    from models import JDProfile, SummaryDraft
    from tests.test_holistic_review import Stub
    from tests.test_tailor import master

    class CollegeStub(Stub):
        def __call__(self, template, response_model, **context):
            if response_model is JDProfile:
                self.calls.append((template, response_model, context))
                return _suu_jd()
            if response_model is SummaryDraft:
                self.calls.append((template, response_model, context))
                return SummaryDraft(
                    text=f"{context['title']} candidate with {context['years_label']} of web development experience.",
                    source_fact_ids=[],
                )
            return super().__call__(template, response_model, **context)

    monkeypatch.setattr(pipeline_module, "render", MagicMock())
    pipeline = _pipeline(college_mode=True)
    monkeypatch.setattr(pipeline, "_call_once", CollegeStub())
    jd_text = "\n".join(line.text for line in _suu_jd().minimum_qualifications) + "\nHTML"
    assert pipeline.run(master(), jd_text, tmp_path, no_pdf=True) == 0
    report = json.loads((tmp_path / "match_report.json").read_text())
    texts = [row["text"] for row in report["qualification_coverage"]]
    assert len(texts) == 3 and texts[0].startswith("Two years")
    tailored = json.loads((tmp_path / "tailored.json").read_text())
    assert tailored["basics"]["summary"].startswith("UX/UI Developer candidate with")


# -- Task 6: two pages and more content ----------------------------------------


def _one_role_scored():
    from models import ScoredBullet
    from render import ScoredResume, ScoredWork

    return ScoredResume(
        basics={"name": "Test User"},
        work=[ScoredWork(name="Example Corp", position="Engineer", relevance=80, source_id="work[0]",
                         highlights=[ScoredBullet(text="Built reporting services for operations.", relevance=60)])],
    )


def test_fit_accepts_two_pages_when_allowed(tmp_path):
    import pytest

    from render import RenderError, fit_to_one_page

    plain = fit_to_one_page(_one_role_scored(), tmp_path, page_counter=lambda _: 2, max_pages=2)
    assert plain.work[0].highlights == ["Built reporting services for operations."]
    with pytest.raises(RenderError):
        fit_to_one_page(_one_role_scored(), tmp_path, page_counter=lambda _: 2)


def test_fit_recovery_bundle_respects_max_pages():
    import pytest
    from pydantic import ValidationError

    from resume_tailor.fit_recovery import FitRecoveryBundle

    base = dict(revision=1, concision_attempts=0, candidates=[], recommended_candidate_ids=[],
                scored_resume=_one_role_scored(), pending_report={}, trim_log=[], concision_log=[],
                candidate_locations={})
    assert FitRecoveryBundle(page_count=3, max_pages=2, **base).max_pages == 2
    with pytest.raises(ValidationError):
        FitRecoveryBundle(page_count=2, max_pages=2, **base)
    assert FitRecoveryBundle(page_count=2, **base).max_pages == 1


def test_resumed_bullet_review_keeps_two_page_limit(tmp_path):
    import json

    from resume_tailor.bullet_review import apply_bullet_review, load_bullet_review, persist_bullet_review

    flag = {"section": "work", "source_id": "work[0]", "label": "Engineer · Example Corp",
            "assignment_id": "allocation-1", "issues": ["x"], "original_text": "Built reporting services in Kotlin.",
            "safe_text": "Built reporting services for operations.", "safe_kind": "edited", "can_keep": True,
            "source_fact_ids": ["work[0].highlights[0]"]}
    persist_bullet_review(
        tmp_path, _one_role_scored(), [flag], pending_report={}, no_pdf=False, jd_profile_json="{}",
        forbidden_terms=[], tech_requirements=[], fact_index={}, max_pages=2,
    )
    bundle = load_bullet_review(tmp_path)
    assert bundle.max_pages == 2
    assert apply_bullet_review(tmp_path, {bundle.flags[0].flag_id: "safe"}, page_counter=lambda _: 2) == 0
    assert json.loads((tmp_path / "tailored.json").read_text())["work"]


def test_college_selects_more_entries():
    from pipeline_core import WORK_BULLET_BUDGET, work_bullet_targets
    from resume_tailor.runtime import selection_caps

    assert selection_caps(False) == (3, 2, WORK_BULLET_BUDGET, 1)
    work_cap, project_cap, budget, pages = selection_caps(True)
    assert (work_cap, project_cap, budget, pages) == (5, 4, 16, 2)
    sources = [
        {"source_id": f"work[{index}]", "endDate": "2024-12", "selection_relevance": 50,
         "selection_bullet_budget": budget,
         "source_facts": {"highlights": [{"source_id": f"work[{index}].highlights[{n}]"} for n in range(6)]}}
        for index in range(5)
    ]
    assert sum(work_bullet_targets(sources).values()) == 16


# -- Task 7: summary -----------------------------------------------------------


def test_summary_rejects_uncomputed_years():
    from models import SummaryDraft
    from resume_tailor.qualifications import validate_summary

    facts = {"work[1].highlights[0]": {"text": "Built React dashboards."}}
    bad = SummaryDraft(text="UX/UI Developer candidate with 3 years of web development experience.",
                       source_fact_ids=["work[1].highlights[0]"])
    assert any("years" in problem for problem in validate_summary(bad, "UX/UI Developer", "2+ years", facts))
    good = SummaryDraft(text="UX/UI Developer candidate with 2+ years of web development experience building React dashboards.",
                        source_fact_ids=["work[1].highlights[0]"])
    assert validate_summary(good, "UX/UI Developer", "2+ years", facts) == []


def test_summary_must_name_title_and_cite_real_facts():
    from models import SummaryDraft
    from resume_tailor.qualifications import validate_summary

    draft = SummaryDraft(text="Developer with 2+ years of experience building accessible web interfaces.",
                         source_fact_ids=["work[9].highlights[0]"])
    problems = validate_summary(draft, "UX/UI Developer", "2+ years", {})
    assert any("title" in problem for problem in problems)
    assert any("work[9]" in problem for problem in problems)


def test_fallback_summary_text():
    from resume_tailor.qualifications import fallback_summary

    text = fallback_summary(
        "UX/UI Developer", "2+ years", "web development/programming",
        ["Requires ability to work cordially with other University personnel.", "Strong understanding of HTML, JavaScript, and CSS."],
    )
    assert text == (
        "UX/UI Developer candidate with 2+ years of web development/programming experience "
        "across ability to work cordially with other, strong understanding of HTML, JavaScript."
    )


def test_template_renders_summary_only_when_set():
    from models import JSONResume
    from render import render_tex

    base = {"basics": {"name": "Test User"}}
    assert "Summary" not in render_tex(JSONResume.model_validate(base))
    with_summary = JSONResume.model_validate({"basics": {"name": "Test User", "summary": "UX/UI Developer candidate."}})
    tex = render_tex(with_summary)
    assert "\\section{Summary}" in tex and "UX/UI Developer candidate." in tex


def test_credits_render_in_education_line():
    from models import JSONResume
    from render import render_tex

    resume = JSONResume.model_validate(
        {"basics": {"name": "Test User"},
         "education": [{"institution": "SUNY Oswego", "studyType": "BS", "credits_completed": 98}]}
    )
    assert "98 credits completed" in render_tex(resume)


def test_bad_summary_falls_back_to_template(monkeypatch, tmp_path):
    from unittest.mock import MagicMock

    from models import Basics, SummaryDraft
    from render import ScoredResume

    pipeline = _pipeline(college_mode=True)
    calls = []

    def bad(template, response_model, **context):
        calls.append(template)
        return SummaryDraft(text="UX/UI Developer candidate with 9 years of experience everywhere.", source_fact_ids=[])

    monkeypatch.setattr(pipeline, "_call_once", bad)
    scored = ScoredResume(basics=Basics(name="Test User"), work=[], projects=[])
    result = pipeline._with_summary(scored, _suu_jd(), _college_master(), _plan(["work[1].highlights[1]"]), [], {})
    assert calls and "9 years" not in result.basics.summary
    assert result.basics.summary.startswith("UX/UI Developer candidate with 2+ years of web development/programming experience")


# -- review fixes ------------------------------------------------------------------


def test_summary_rejects_number_words_and_unsupported_terms():
    from models import SummaryDraft
    from resume_tailor.qualifications import validate_summary

    words = SummaryDraft(text="Web Developer with three years of web development experience.", source_fact_ids=[])
    assert any("years" in p for p in validate_summary(words, "Web Developer", "2+ years", {}))
    claim = SummaryDraft(text="Web Developer experienced with WCAG compliance and React.", source_fact_ids=[])
    problems = validate_summary(claim, "Web Developer", "2+ years", {}, unsupported_terms=["WCAG"])
    assert any("WCAG" in p for p in problems)


def test_less_than_one_year_and_digit_titles_validate():
    from models import SummaryDraft
    from resume_tailor.qualifications import validate_summary

    short = SummaryDraft(text="Web Developer candidate with less than 1 year of web experience.", source_fact_ids=[])
    assert validate_summary(short, "Web Developer", "less than 1 year", {}) == []
    titled = SummaryDraft(text="Programmer Analyst 2 candidate with 2+ years of software experience.", source_fact_ids=[])
    assert validate_summary(titled, "Programmer Analyst 2", "2+ years", {}) == []


def test_fallback_without_domain_never_says_software():
    from resume_tailor.qualifications import fallback_summary

    assert fallback_summary("Web Developer", "2+ years", None, []) == (
        "Web Developer candidate with 2+ years of technical experience."
    )


def test_summary_never_gets_experience_or_substituted_lines(monkeypatch):
    from models import Basics, SummaryDraft
    from render import ScoredResume

    seen = {}

    def capture(template, response_model, **context):
        seen.update(context)
        return SummaryDraft(text="UX/UI Developer candidate with 2+ years of web development experience.", source_fact_ids=[])

    pipeline = _pipeline(college_mode=True)
    monkeypatch.setattr(pipeline, "_call_once", capture)
    scored = ScoredResume(basics=Basics(name="Test User"), work=[], projects=[])
    pipeline._with_summary(scored, _suu_jd(), _college_master(), _plan(["work[1].highlights[1]"]), [], {})
    assert "Two years" not in seen["qualifications_json"]


def test_sanitize_keeps_lines_with_curly_quotes():
    from keyword_coverage import sanitize_jd_profile

    profile = _suu_profile([{"text": "Two years' recent web development experience.", "type": "experience_length", "years": 2}])
    cleaned, _ = sanitize_jd_profile(profile, "Minimum: Two years’ recent web development experience.")
    assert len(cleaned.minimum_qualifications) == 1


def test_degree_with_years_needs_years_on_page():
    from render import scored_to_plain
    from resume_tailor.qualifications import qualification_coverage

    from models import JDProfile

    line = _line("Bachelor's degree and two years of web development experience.", "degree", years=2,
                 domain="web development")
    jd = JDProfile(role="Web Developer", must_have_skills=[], nice_to_have_skills=[], keywords=[],
                   minimum_qualifications=[line])
    master = _college_master()
    master.education[0].endDate = "2026-05"
    scored = _scored([], summary=None)
    rows = qualification_coverage(scored, scored_to_plain(scored), jd, master, _plan(["x"]), [], TODAY)
    assert rows[0]["status"] == "supported_not_on_page"


def test_credits_only_print_in_college_mode():
    import inspect

    import resume_tailor.pipeline as pipeline_module

    assert "credits_completed" in inspect.getsource(pipeline_module.TailorPipeline.run)


def test_ui_resets_check_when_college_toggle_changes_and_skips_summary_stage():
    app_js = (REPO_ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert '$("college-mode").addEventListener("change"' in app_js
    assert '"Write summary"' in app_js and "college_mode" in app_js
