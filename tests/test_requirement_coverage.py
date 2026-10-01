"""Requirement gap mapping, proxy evidence, keyword coverage, and model fallback."""

import json
from unittest.mock import MagicMock

import pytest

import resume_tailor.pipeline as pipeline_module
import tailor
from keyword_coverage import (
    attach_proxies,
    forbidden_claim_terms,
    mentions,
    placement_findings,
    priority_proxies,
    requirement_map,
    resume_coverage,
    sanitize_jd_profile,
    supported_tech_requirements,
    title_matches,
)
from models import (
    EvidencePlan,
    JDProfile,
    KeywordWeight,
    RequirementProxy,
    RequirementProxyPlan,
    SelectionCandidate,
    WorkRewriteResponse,
)
from pipeline_core import (
    ContractError,
    choose_selected,
    master_fact_index,
    project_evidence,
    proxy_coverage_gaps,
    sanitize_target_terms,
    validate_requirement_proxy_plan,
    validate_work_response,
    work_evidence,
)
from resume_tailor.batch import is_quota_error
from resume_tailor.runtime import ModelUnavailableError
from tests.test_holistic_review import Stub
from tests.test_tailor import evidence_plan, master, selected_evidence, work_item


def jd(**overrides) -> JDProfile:
    fields = {
        "role": "Software Engineer",
        "title_aliases": ["Software Developer"],
        "must_have_skills": ["Kotlin", "PostgreSQL"],
        "nice_to_have_skills": ["React"],
        "keywords": [
            KeywordWeight(term="Kotlin", weight=5, category="language"),
            KeywordWeight(term="PostgreSQL", weight=5, aliases=["Postgres"], category="tool"),
            KeywordWeight(term="communication", weight=2, category="soft_skill"),
        ],
    }
    fields.update(overrides)
    return JDProfile(**fields)


def kotlin_proxy(**overrides) -> RequirementProxy:
    fields = {
        "requirement": "kotlin",
        "requirement_type": "nice_to_have",
        "category": "language",
        "proximity": "same_family",
        "proxy_terms": ["Java"],
        "source_fact_ids": ["skills[0].keywords[0]", "work[0].highlights[3]"],
        "transfer_basis": "Kotlin is a JVM language interoperable with Java.",
        "relevance": 90,
        "list_as_transferable_skill": True,
    }
    fields.update(overrides)
    return RequirementProxy(**fields)


def mapped(profile: JDProfile | None = None):
    facts = master_fact_index(master())
    requirements = requirement_map(profile or jd(), facts)
    return requirements, facts


def test_requirement_map_classifies_direct_and_missing_requirements():
    requirements, _ = mapped()
    status = {item["term"]: item["status"] for item in requirements}
    assert status["Kotlin"] == "missing"
    assert status["PostgreSQL"] == "direct"
    assert status["React"] == "direct"
    assert requirements[0]["requirement_type"] == "must_have"


def test_literal_matching_avoids_substring_and_common_word_false_hits():
    assert not mentions("Built JavaScript dashboards", ["Java"])
    assert not mentions("Wrote modern C++ services", ["C"])
    assert not mentions("Plans to go to market", ["Go"])
    assert mentions("Shipped REST APIs in Go", ["Go"])
    assert mentions("Tuned Postgres queries", ["PostgreSQL", "Postgres"])
    assert mentions("Designed REST APIs", ["REST API"])


def test_title_match_ignores_seniority_words():
    profile = jd()
    assert title_matches("Software Engineering Intern", profile)
    assert title_matches("Senior Software Developer", profile)
    assert not title_matches("Data Analyst Intern", profile)


def test_proxy_plan_is_canonicalized_and_attached():
    requirements, facts = mapped()
    plan = RequirementProxyPlan(proxies=[kotlin_proxy()])
    validate_requirement_proxy_plan(plan, requirements, facts)
    proxy = plan.proxies[0]
    assert proxy.requirement == "Kotlin"
    assert proxy.requirement_type == "must_have"
    attached = attach_proxies(requirements, plan.proxies)
    kotlin = next(item for item in attached if item["term"] == "Kotlin")
    assert kotlin["status"] == "proxy"
    assert kotlin["proxy_terms"] == ["Java"]
    assert priority_proxies(attached)[0]["term"] == "Kotlin"
    keyword_only = [
        {**item, "proxy_fact_ids": ["skills[0].keywords[0]"]} for item in attached
    ]
    assert priority_proxies(keyword_only, facts) == []
    assert forbidden_claim_terms(attached) == ("Kotlin",)


@pytest.mark.parametrize(
    "proxy, message",
    [
        (kotlin_proxy(requirement="PostgreSQL"), "already stated"),
        (kotlin_proxy(proxy_terms=["Scala"]), "do not appear in the cited facts"),
        (kotlin_proxy(source_fact_ids=["skills[9].keywords[0]"]), "nonexistent_sources"),
        (kotlin_proxy(requirement="Rust"), "not a target-profile requirement"),
    ],
)
def test_proxy_plan_rejects_untruthful_proxies(proxy, message):
    requirements, facts = mapped()
    with pytest.raises(ContractError, match=message):
        validate_requirement_proxy_plan(
            RequirementProxyPlan(proxies=[proxy]), requirements, facts
        )


def test_proxy_plan_repair_keeps_valid_proxies_and_drops_bad_terms():
    requirements, facts = mapped()
    plan = RequirementProxyPlan(
        proxies=[
            kotlin_proxy(proxy_terms=["Java", "Scala"]),
            kotlin_proxy(requirement="PostgreSQL"),
        ]
    )
    notes = validate_requirement_proxy_plan(plan, requirements, facts, repair=True)
    assert [proxy.requirement for proxy in plan.proxies] == ["Kotlin"]
    assert plan.proxies[0].proxy_terms == ["Java"]
    assert len(notes) == 2


def test_keyword_only_proxy_is_enriched_with_bullet_capable_facts():
    requirements, facts = mapped()
    # projects[0].technologies[0] is "Python"; the project's own work follows.
    plan = RequirementProxyPlan(
        proxies=[
            kotlin_proxy(
                proxy_terms=["Python"], source_fact_ids=["projects[0].technologies[0]"]
            )
        ]
    )
    validate_requirement_proxy_plan(plan, requirements, facts)
    added = plan.proxies[0].source_fact_ids[1:]
    assert "projects[0].description" in added or "work[2].highlights[0]" in added
    assert all(facts[fact_id]["kind"] != "technology" for fact_id in added)


def test_bullets_may_not_claim_a_missing_technology():
    resume = master()
    selected = selected_evidence(resume)
    plan = evidence_plan(selected)
    facts = master_fact_index(resume)
    items = [work_item(source, plan) for source in selected.work]
    bullet = items[0].bullets[0]
    bullet.text = bullet.text + " using Kotlin"
    with pytest.raises(ContractError, match="absent from the master"):
        validate_work_response(
            WorkRewriteResponse(work=items),
            selected.work,
            plan,
            facts,
            forbidden_terms=("Kotlin",),
        )


def test_greedy_selection_prefers_complementary_requirement_coverage():
    resume = master()
    facts = master_fact_index(resume)
    projects = project_evidence(resume)
    requirements = requirement_map(
        jd(must_have_skills=["React"], nice_to_have_skills=[], keywords=[]), facts
    )
    candidates = {
        "projects[0]": SelectionCandidate(
            source_id="projects[0]", relevance=70, selected=True
        ),
        "projects[1]": SelectionCandidate(
            source_id="projects[1]", relevance=60, selected=False
        ),
    }
    chosen = choose_selected(
        candidates, projects, 1, requirements=requirements, fact_index=facts
    )
    assert [item["source_id"] for item in chosen] == ["projects[1]"]
    assert chosen[0]["selection_covered_requirement_ids"] == ["R1"]


def test_title_matching_roles_win_work_slots():
    resume = master()
    facts = master_fact_index(resume)
    work = work_evidence(resume)
    profile = JDProfile(
        role="Analyst", must_have_skills=[], nice_to_have_skills=[], keywords=[]
    )
    candidates = {
        item["source_id"]: SelectionCandidate(
            source_id=item["source_id"], relevance=50, selected=False
        )
        for item in work
    }
    chosen = choose_selected(
        candidates, work, 1, requirements=[], fact_index=facts, jd=profile
    )
    assert chosen[0]["position"] == "Analyst"
    assert chosen[0]["selection_title_match"] is True


def test_proxy_gap_detection_and_target_term_sanitizing():
    resume = master()
    selected = selected_evidence(resume)
    plan = evidence_plan(selected)
    requirements, facts = mapped()
    proxy_plan = RequirementProxyPlan(proxies=[kotlin_proxy()])
    validate_requirement_proxy_plan(proxy_plan, requirements, facts)
    attached = attach_proxies(requirements, proxy_plan.proxies)
    priority = priority_proxies(attached)

    gaps = proxy_coverage_gaps(plan, priority, selected.projects, facts)
    assert gaps and "Kotlin" in gaps[0]
    plan.assignments[0].source_fact_ids.append("skills[0].keywords[0]")
    assert proxy_coverage_gaps(plan, priority, selected.projects, facts) == []

    # work[0].highlights[2] says "Integrated PostgreSQL services."
    assignment = plan.assignments[0]
    assignment.source_fact_ids = ["work[0].highlights[2]", "skills[0].keywords[0]"]
    assignment.target_terms = ["postgres", "Java", "React", "Bananas"]
    forbidden = forbidden_claim_terms(attached)
    dropped = sanitize_target_terms(plan, attached, forbidden, facts)
    assert assignment.target_terms == ["PostgreSQL", "Java"]
    assert dropped == [
        f"{assignment.assignment_id}:React (unsupported)",
        f"{assignment.assignment_id}:Bananas",
    ]
    assignment.target_terms = ["Kotlin"]
    assert sanitize_target_terms(plan, attached, forbidden, facts) == [
        f"{assignment.assignment_id}:Kotlin (never used)"
    ]
    assert assignment.target_terms == []


def test_resume_coverage_and_placement_are_measured_literally():
    requirements, _ = mapped(
        jd(must_have_skills=["PostgreSQL"], nice_to_have_skills=[], keywords=[])
    )
    resume = {
        "skills": [{"name": "Data", "keywords": ["PostgreSQL"]}],
        "work": [{"position": "Engineer", "highlights": ["Built an API."]}],
        "projects": [],
    }
    coverage = resume_coverage(resume, requirements)
    assert coverage["computed_coverage_pct"] == 100.0
    findings = placement_findings(resume, requirements)
    assert any("no work or project bullet" in item for item in findings)
    assert any("first bullet" in item for item in findings)


def test_invented_keywords_are_dropped_from_the_jd_profile():
    profile = jd(
        keywords=[
            KeywordWeight(term="Kotlin", weight=5),
            KeywordWeight(term="Blockchain", weight=4),
        ]
    )
    cleaned, dropped = sanitize_jd_profile(profile, "We need Kotlin engineers.")
    assert [item.term for item in cleaned.keywords] == ["Kotlin"]
    assert dropped == ["Blockchain"]


# Model fallback ---------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, code: int, status: str):
        super().__init__(f"{code} {status}. model trouble")
        self.code = code
        self.status = status
        self.message = "model trouble"


def chain_pipeline(provider) -> tailor.TailorPipeline:
    return tailor.TailorPipeline(
        model="gemini-3.1-flash-lite",
        call_interval=0,
        provider=provider,
        planning_models=["gemini-3.8-flash", "gemini-3.5-flash"],
        fallback_models=["gemini-3.5-flash-lite"],
    )


def _ok_plan_response():
    return {"message": {"content": json.dumps({"proxies": []})}}


def test_planning_stage_falls_back_and_skips_unavailable_model_afterwards():
    provider = MagicMock()
    seen = []

    def chat(model, messages, options=None, **kwargs):
        seen.append(model)
        if model == "gemini-3.8-flash":
            raise ApiError(503, "UNAVAILABLE")
        return _ok_plan_response()

    provider.chat.side_effect = chat
    pipeline = chain_pipeline(provider)
    for _ in range(2):
        pipeline._call_once(
            "plan_requirement_coverage",
            RequirementProxyPlan,
            jd_profile_json="{}",
            missing_requirements_json="[]",
            stated_requirements_json="[]",
            global_evidence_json="{}",
        )
    assert seen == ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.5-flash"]


def test_quota_errors_stick_for_the_run_but_overload_cools_down(monkeypatch):
    provider = MagicMock()
    seen = []
    errors = {
        "gemini-3.8-flash": ApiError(429, "RESOURCE_EXHAUSTED"),
        "gemini-3.5-flash": ApiError(503, "UNAVAILABLE"),
    }

    def chat(model, messages, options=None, **kwargs):
        seen.append(model)
        if model in errors:
            raise errors[model]
        return _ok_plan_response()

    provider.chat.side_effect = chat
    monkeypatch.setattr(pipeline_module, "TRANSIENT_COOLDOWN_SECONDS", 0.0)
    pipeline = chain_pipeline(provider)
    for _ in range(2):
        pipeline._call_once("plan_requirement_coverage", RequirementProxyPlan)
    # 429 is never retried this run; the 503 model is retried once cooled down.
    assert seen == [
        "gemini-3.8-flash",
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite",
    ]


def test_bullet_may_not_name_a_technology_its_facts_do_not():
    resume = master()
    selected = selected_evidence(resume)
    plan = evidence_plan(selected)
    facts = master_fact_index(resume)
    requirements = requirement_map(jd(), facts)
    tech = supported_tech_requirements(requirements)
    assert ("PostgreSQL", ("PostgreSQL", "Postgres", "Postgres SQL")) in tech
    items = [work_item(source, plan) for source in selected.work]
    target = next(
        bullet
        for item in items
        for bullet in item.bullets
        if "PostgreSQL" not in " ".join(facts[i]["text"] for i in bullet.source_ids)
    )
    target.text += " on Postgres"
    with pytest.raises(ContractError, match="source facts do not mention"):
        validate_work_response(
            WorkRewriteResponse(work=items),
            selected.work,
            plan,
            facts,
            tech_requirements=tech,
        )


def test_project_bullets_may_name_their_listed_technologies():
    from pipeline_core import _bullet_evidence_text

    facts = master_fact_index(master())
    text = _bullet_evidence_text(["projects[1].highlights[0]"], facts)
    assert "React" in text  # projects[1].technologies, not the highlight


def test_cross_entry_objections_are_waived_but_reported():
    from models import TruthViolation
    from pipeline_core import assemble_scored, waive_cross_entry_objections
    from tests.test_tailor import components

    resume = master()
    parts = components(resume)
    scored = assemble_scored(resume, parts)
    facts = master_fact_index(resume)
    moved = scored.work[0].highlights[0].text  # allocation-1 cites projects[0]
    violations = [
        TruthViolation(section="work", claim=moved, reason="Attributed to work[0] but the facts are for a project."),
        TruthViolation(section="work", claim=moved, reason="States a number the facts never give."),
    ]
    kept, waived = waive_cross_entry_objections(
        violations, scored, parts.evidence_plan, facts
    )
    assert [item.reason for item in waived] == [violations[0].reason]
    assert [item.reason for item in kept] == [violations[1].reason]


def test_proxy_bullets_may_not_justify_the_gap():
    resume = master()
    selected = selected_evidence(resume)
    plan = evidence_plan(selected)
    facts = master_fact_index(resume)
    items = [work_item(source, plan) for source in selected.work]
    for filler in (
        ", mirroring distributed message broker architectures",
        " using Java and related virtual-machine languages",
    ):
        items = [work_item(source, plan) for source in selected.work]
        items[0].bullets[0].text += filler
        with pytest.raises(ContractError, match="justifies a skill gap"):
            validate_work_response(
                WorkRewriteResponse(work=items), selected.work, plan, facts
            )


def test_exhausted_chain_cancels_with_every_api_error():
    provider = MagicMock()
    provider.chat.side_effect = ApiError(429, "RESOURCE_EXHAUSTED")
    pipeline = chain_pipeline(provider)
    with pytest.raises(ModelUnavailableError) as caught:
        pipeline._call_once("tailor_skills", RequirementProxyPlan)
    error = caught.value
    assert [model for model, _ in error.failures] == [
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash-lite",
    ]
    assert "429 RESOURCE_EXHAUSTED" in str(error)
    assert error.quota_exhausted and is_quota_error(error)
    assert error.diagnostic()["model_failures"][0]["model"] == "gemini-3.1-flash-lite"


def test_auth_errors_stop_immediately_without_fallback():
    provider = MagicMock()
    provider.chat.side_effect = ApiError(403, "PERMISSION_DENIED")
    pipeline = chain_pipeline(provider)
    with pytest.raises(ModelUnavailableError, match="403 PERMISSION_DENIED"):
        pipeline._call_once("tailor_skills", RequirementProxyPlan)
    assert provider.chat.call_count == 1
    assert not is_quota_error(
        ModelUnavailableError("x", [("m", "503 UNAVAILABLE: busy")])
    )


def test_injected_provider_keeps_a_single_model_chain():
    pipeline = tailor.TailorPipeline(
        model="gemini-3.1-flash-lite", call_interval=0, provider=MagicMock()
    )
    assert pipeline.planning_chain == ("gemini-3.1-flash-lite",)


# End to end: a must-have gap with proxy evidence -------------------------------


class GapStub(Stub):
    def __init__(self, cite_proxy: bool):
        super().__init__()
        self.cite_proxy = cite_proxy
        if cite_proxy:
            assignment = next(
                item for item in self.plan.assignments if item.inferred_impact is None
            )
            assignment.source_fact_ids.append("skills[0].keywords[0]")

    def __call__(self, template, response_model, **context):
        if response_model is JDProfile:
            self.calls.append((template, response_model, context))
            return JDProfile(
                role="Engineer",
                must_have_skills=["Kotlin", "Python"],
                nice_to_have_skills=[],
                keywords=[KeywordWeight(term="Kotlin", weight=5, category="language")],
            )
        if response_model is RequirementProxyPlan:
            self.calls.append((template, response_model, context))
            return RequirementProxyPlan(proxies=[kotlin_proxy()])
        return super().__call__(template, response_model, **context)


@pytest.mark.parametrize("cite_proxy", [True, False])
def test_gap_proxy_reaches_the_plan_or_is_reported(monkeypatch, tmp_path, cite_proxy):
    pipeline = tailor.TailorPipeline(
        model="gemini-3.1-flash-lite", call_interval=0, provider=MagicMock()
    )
    stub = GapStub(cite_proxy)
    monkeypatch.setattr(pipeline, "_call_once", stub)
    monkeypatch.setattr(pipeline_module, "render", MagicMock())
    result = pipeline.run(master(), "Kotlin and Python engineer", tmp_path, no_pdf=True)
    assert result == 0
    plan_calls = [call for call in stub.calls if call[1] is EvidencePlan]
    plan_context = plan_calls[0][2]
    assert "Kotlin" in plan_context["priority_proxies_json"]
    report = json.loads((tmp_path / "match_report.json").read_text())
    kotlin = next(item for item in report["requirement_map"] if item["term"] == "Kotlin")
    assert kotlin["status"] == "proxy"
    assert "keyword_coverage" in report and "computed_coverage_pct" in report["keyword_coverage"]
    if cite_proxy:
        assert len(plan_calls) == 1
        assert report["unplaced_proxy_evidence"] == []
    else:
        assert len(plan_calls) == 2
        assert "Kotlin" in plan_calls[1][2]["feedback"]
        assert report["unplaced_proxy_evidence"]


def test_web_scheduled_provider_gets_the_model_chain():
    from resume_tailor.web.scheduler import ScheduledProvider

    provider = ScheduledProvider(MagicMock(), MagicMock(), provider_tracks_attempts=True)
    pipeline = tailor.TailorPipeline(
        model="gemini-3.1-flash-lite",
        call_interval=0,
        provider=provider,
        planning_models=["gemini-3.8-flash"],
        fallback_models=["gemini-3.5-flash-lite"],
    )
    assert pipeline.default_chain == ("gemini-3.1-flash-lite", "gemini-3.5-flash-lite")
    default = tailor.TailorPipeline(
        model="gemini-3.1-flash-lite", call_interval=0, provider=provider
    )
    assert len(default.planning_chain) > 1


def test_all_models_busy_waits_and_retries_instead_of_stopping(monkeypatch):
    provider = MagicMock()
    calls = []

    def chat(model, messages, options=None, **kwargs):
        calls.append(model)
        if len(calls) <= 2:  # the whole two-model chain is overloaded once
            raise ApiError(503, "UNAVAILABLE")
        return _ok_plan_response()

    provider.chat.side_effect = chat
    sleeps = []
    monkeypatch.setattr(pipeline_module.time, "sleep", sleeps.append)
    pipeline = chain_pipeline(provider)
    result = pipeline._call_once("tailor_skills", RequirementProxyPlan)
    assert result.proxies == []
    assert sleeps == [pipeline_module.CHAIN_RETRY_DELAYS_SECONDS[0]]
    assert calls == [
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
    ]


def test_persistently_busy_chain_stops_after_all_rounds(monkeypatch):
    provider = MagicMock()
    provider.chat.side_effect = ApiError(503, "UNAVAILABLE")
    sleeps = []
    monkeypatch.setattr(pipeline_module.time, "sleep", sleeps.append)
    pipeline = chain_pipeline(provider)
    with pytest.raises(ModelUnavailableError, match="503 UNAVAILABLE"):
        pipeline._call_once("tailor_skills", RequirementProxyPlan)
    assert sleeps == list(pipeline_module.CHAIN_RETRY_DELAYS_SECONDS)
    assert provider.chat.call_count == 2 * (len(sleeps) + 1)
