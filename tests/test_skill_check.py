"""Skill-check answers: storage in the master resume and use as facts."""

from __future__ import annotations

import json

from keyword_coverage import forbidden_claim_terms, normalize_term, requirement_map
from models import CONFIRMED_SKILL_GROUP, JDProfile, JSONResume, KeywordWeight
from pipeline_core import master_fact_index
from resume_tailor import skill_answers
from resume_tailor.runtime import load_master
from resume_tailor.skill_answers import (
    answered_keys,
    apply_answers,
    bullet_tech_requirements,
    confirmed_terms,
    replace_answers,
    save_master,
)


def _master(**extra) -> JSONResume:
    data = {
        "basics": {"name": "Test User"},
        "skills": [{"name": "Languages", "keywords": ["Python"]}],
        "work": [
            {
                "name": "Acme",
                "position": "Developer",
                "startDate": "2025-01",
                "highlights": ["Designed dashboard layouts for facilities staff."],
            }
        ],
    }
    data.update(extra)
    return JSONResume.model_validate(data)


def test_apply_answers_round_trip():
    master = apply_answers(_master(), ["Figma", "figma"], ["Siteimprove"])
    assert confirmed_terms(master) == ["Figma"]
    assert master.skill_check is not None
    assert master.skill_check.declined == ["Siteimprove"]
    moved = apply_answers(master, ["Siteimprove"], [])
    assert confirmed_terms(moved) == ["Figma", "Siteimprove"]
    assert moved.skill_check.declined == []
    keys = answered_keys(moved)
    assert {normalize_term("python"), normalize_term("figma"), normalize_term("siteimprove")} <= keys
    # The original is untouched.
    assert confirmed_terms(_master()) == []


def test_replace_answers_sets_both_lists_exactly():
    master = apply_answers(_master(), ["Figma", "Azure"], ["JUnit"])
    replaced = replace_answers(master, ["JUnit"], ["Figma"])
    assert confirmed_terms(replaced) == ["JUnit"]
    assert replaced.skill_check.declined == ["Figma"]
    cleared = replace_answers(replaced, [], [])
    assert all(group.name != CONFIRMED_SKILL_GROUP for group in cleared.skills or [])


def test_save_master_is_atomic(tmp_path, monkeypatch):
    path = tmp_path / "master.json"
    path.write_text(_master().model_dump_json(), encoding="utf-8")
    calls: list[tuple[str, str]] = []
    real_replace = skill_answers.os.replace

    def spy(src, dst):
        calls.append((str(src), str(dst)))
        assert json.loads(open(src, encoding="utf-8").read())["skills"]
        real_replace(src, dst)

    monkeypatch.setattr(skill_answers.os, "replace", spy)
    saved = apply_answers(_master(), ["Figma"], ["Siteimprove"])
    save_master(saved, path)
    assert calls == [(str(path.with_suffix(".json.tmp")), str(path))]
    assert load_master(path) == saved


def test_confirmed_skill_is_direct_and_allowed_in_bullet():
    master = apply_answers(_master(), ["Figma"], [])
    jd = JDProfile(
        role="Web Developer",
        must_have_skills=["Figma", "Python"],
        nice_to_have_skills=[],
        keywords=[
            KeywordWeight(term="Figma", weight=5, category="tool", evidence_span="Figma"),
            KeywordWeight(term="Python", weight=5, category="language", evidence_span="Python"),
        ],
    )
    requirements = requirement_map(jd, master_fact_index(master))
    status = {item["term"]: item["status"] for item in requirements}
    assert status == {"Figma": "direct", "Python": "direct"}
    assert "Figma" not in forbidden_claim_terms(requirements)
    terms = [term for term, _ in bullet_tech_requirements(requirements, master)]
    assert terms == ["Python"]


# -- check_skills: parse + requirement map before the run ----------------------

from unittest.mock import MagicMock  # noqa: E402

import resume_tailor.pipeline as pipeline_module  # noqa: E402
import tailor  # noqa: E402
from models import RequirementProxyPlan  # noqa: E402
from tests.test_holistic_review import Stub  # noqa: E402
from tests.test_tailor import master as tailor_master  # noqa: E402

CHECK_JD = "Hiring a web developer with Python, Figma, Siteimprove, Kubernetes."


class GapStub(Stub):
    """Stub whose parsed JD names tool gaps and a soft skill."""

    def __call__(self, template, response_model, **context):
        if response_model is JDProfile:
            self.calls.append((template, response_model, context))

            def kw(term, category):
                return KeywordWeight(term=term, weight=4, category=category, evidence_span=term)

            return JDProfile(
                role="Web Developer",
                must_have_skills=["Python", "Figma"],
                nice_to_have_skills=["Siteimprove", "Kubernetes"],
                keywords=[
                    kw("Python", "language"),
                    kw("Figma", "tool"),
                    kw("Siteimprove", "tool"),
                    kw("Kubernetes", "platform"),
                    kw("communication", "soft_skill"),
                ],
            )
        return super().__call__(template, response_model, **context)


def _pipeline(monkeypatch, stub):
    instance = tailor.TailorPipeline(
        model="gemini-3.1-flash-lite", call_interval=0, provider=MagicMock()
    )
    monkeypatch.setattr(instance, "_call_once", stub)
    return instance


def _count(stub, model):
    return sum(1 for _, response_model, _ in stub.calls if response_model is model)


def test_check_skills_returns_only_unanswered_tech_gaps(monkeypatch, tmp_path):
    answered = apply_answers(tailor_master(), [], ["Siteimprove"])
    result = _pipeline(monkeypatch, GapStub()).check_skills(answered, CHECK_JD, tmp_path)
    assert [chip.term for chip in result.chips] == ["Figma", "Kubernetes"]
    assert {chip.status for chip in result.chips} == {"missing"}
    assert result.remembered_declined == ["Siteimprove"]
    assert result.remembered_confirmed == []


def test_alias_answer_suppresses_chip(monkeypatch, tmp_path):
    answered = apply_answers(tailor_master(), [], ["k8s"])
    result = _pipeline(monkeypatch, GapStub()).check_skills(answered, CHECK_JD, tmp_path)
    assert "Kubernetes" not in [chip.term for chip in result.chips]


def test_check_then_run_makes_no_repeat_parse_call(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline_module, "render", MagicMock())
    stub = GapStub()
    check_dir, run_dir = tmp_path / "check", tmp_path / "run"
    _pipeline(monkeypatch, stub).check_skills(tailor_master(), CHECK_JD, check_dir)
    (run_dir / "checkpoints").mkdir(parents=True)
    for path in (check_dir / "checkpoints").glob("*.json"):
        (run_dir / "checkpoints" / path.name).write_bytes(path.read_bytes())
    answered = apply_answers(tailor_master(), ["Figma"], ["Siteimprove", "Kubernetes"])
    code = _pipeline(monkeypatch, stub).run(
        answered, CHECK_JD, run_dir, no_pdf=True, resume=True
    )
    assert code == 0
    assert _count(stub, JDProfile) == 1
    assert _count(stub, RequirementProxyPlan) == 1


LONG_TERM = "Enterprise " * 12 + "Platform"


class LongTermStub(GapStub):
    def __call__(self, template, response_model, **context):
        result = super().__call__(template, response_model, **context)
        if response_model is JDProfile:
            long_term = LONG_TERM
            result.keywords.append(
                KeywordWeight(term=long_term, weight=3, category="platform", evidence_span=long_term)
            )
        return result


def test_overlong_terms_are_not_offered_as_chips(monkeypatch, tmp_path):
    jd = f"{CHECK_JD} {LONG_TERM}"
    result = _pipeline(monkeypatch, LongTermStub()).check_skills(tailor_master(), jd, tmp_path)
    assert all(len(chip.term) <= 80 for chip in result.chips)
    assert "Figma" in [chip.term for chip in result.chips]


def test_declined_terms_are_removed_from_jd_keywords():
    from resume_tailor.skill_answers import without_declined

    master = apply_answers(tailor_master(), [], ["k8s", "Figma"])
    assert without_declined(["Kubernetes", "Python", "figma", "React"], master) == ["Python", "React"]


def test_confirmed_group_heading_never_reaches_the_page():
    from models import CONFIRMED_SKILL_GROUP, Skill
    from resume_tailor.skill_answers import CONFIRMED_SKILL_HEADING, relabel_confirmed_group

    groups = [
        Skill(name="Languages", keywords=["Python"]),
        Skill(name=CONFIRMED_SKILL_GROUP, keywords=["Figma"]),
    ]
    relabeled = relabel_confirmed_group(groups)
    assert [group.name for group in relabeled] == ["Languages", CONFIRMED_SKILL_HEADING]
    assert relabeled[1].keywords == ["Figma"]
    assert CONFIRMED_SKILL_HEADING != CONFIRMED_SKILL_GROUP


class StandardsStub(GapStub):
    def __call__(self, template, response_model, **context):
        result = super().__call__(template, response_model, **context)
        if response_model is JDProfile:
            from models import QualificationLine

            result.minimum_qualifications.append(
                QualificationLine(
                    text="Strong understanding of Section 508/ADA Accessibility compliance.",
                    type="technical",
                    named_terms=["Section 508", "ADA", "Python"],
                )
            )
        return result


STANDARDS_JD = CHECK_JD + " Strong understanding of Section 508/ADA Accessibility compliance."


def test_college_check_offers_standards_from_lines(monkeypatch, tmp_path):
    college = tailor.TailorPipeline(
        model="gemini-3.1-flash-lite", call_interval=0, provider=MagicMock(), college_mode=True
    )
    monkeypatch.setattr(college, "_call_once", StandardsStub())
    terms = [chip.term for chip in college.check_skills(tailor_master(), STANDARDS_JD, tmp_path / "c").chips]
    assert "Section 508" in terms and "ADA" in terms and "Python" not in terms
    plain = _pipeline(monkeypatch, StandardsStub()).check_skills(tailor_master(), STANDARDS_JD, tmp_path / "p")
    assert "Section 508" not in [chip.term for chip in plain.chips]
    answered = apply_answers(tailor_master(), [], ["ADA"])
    monkeypatch.setattr(college, "_call_once", StandardsStub())
    again = [chip.term for chip in college.check_skills(answered, STANDARDS_JD, tmp_path / "a").chips]
    assert "ADA" not in again and "Section 508" in again
