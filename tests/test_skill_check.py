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
