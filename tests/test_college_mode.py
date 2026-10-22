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
