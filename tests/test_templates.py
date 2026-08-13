from pathlib import Path

from prompts.template_manager import TemplateManager


ROOT = Path(__file__).parents[1] / "prompts" / "templates"


def test_pipeline_templates_are_registered_and_summary_is_gone():
    manager = TemplateManager(str(ROOT))
    expected = {
        "jd_parse",
        "select_work",
        "select_projects",
        "plan_evidence",
        "plan_skill_bridges",
        "tailor_skills",
        "tailor_work",
        "tailor_projects",
        "holistic_review",
        "concise_bullet",
        "audit_concision",
        "system_message",
    }
    assert expected == set(manager.get_available_sections())
    assert "tailor_summary" not in manager.get_available_sections()
    assert not (ROOT / "tailor_summary.jinja").exists()


def test_planner_receives_global_evidence_destinations_and_targets():
    prompt = (ROOT / "plan_evidence.jinja").read_text()
    assert "GLOBAL_MASTER_EVIDENCE" in prompt
    assert "SELECTED_WORK_DESTINATIONS" in prompt
    assert "REQUIRED_BULLET_TARGETS" in prompt
    assert '"inferred_impact"' in prompt
    assert "ANY work role, project, or skill group" in prompt


def test_transferable_skill_prompt_is_bounded_and_truth_preserving():
    prompt = (ROOT / "plan_skill_bridges.jinja").read_text()
    assert "GLOBAL_MASTER_EVIDENCE" in prompt
    assert "MASTER_SKILL_KEYWORDS" in prompt
    assert "at most four" in prompt
    assert '"skills": []' in prompt
    assert "never propose years of experience" in prompt.lower()
    assert "never claim that the candidate previously used" in prompt.lower()
    assert "Figma" in prompt


def test_work_and_project_prompts_require_star_contracts_and_counts():
    work = (ROOT / "tailor_work.jinja").read_text()
    projects = (ROOT / "tailor_projects.jinja").read_text()
    for field in (
        "situation_task",
        "action",
        "result",
        "text",
        "source_ids",
        "impact_type",
        "impact_claim",
    ):
        assert f'"{field}"' in work
        assert f'"{field}"' in projects
    assert "4/3/3" in work
    assert "exactly two" in projects
    assert "Do not return project name, dates, URL, technologies" in projects
    assert "TRANSFERABLE_SKILLS_RESERVED_FOR_SKILLS_SECTION" in work
    assert "TRANSFERABLE_SKILLS_RESERVED_FOR_SKILLS_SECTION" in projects


def test_holistic_prompt_owns_semantic_plausibility_review_without_summary_edits():
    review = (ROOT / "holistic_review.jinja").read_text().lower()
    assert "one and only" in review
    assert "evidence_plan" in review
    assert "egregiously inflated" in review
    assert "summary:" not in review


def test_action_verb_dictionary_preserves_every_category():
    verbs = (ROOT / "_action_verbs.jinja").read_text()
    categories_and_rare_verbs = {
        "Building and Implementation": "Fabricated",
        "Design and Architecture": "Conceptualized",
        "Integration and Systems Work": "Orchestrated",
        "Improvement and Optimization": "Refactored",
        "Testing and Quality": "Benchmarked",
        "Debugging and Problem Resolution": "Remediated",
        "Data and Analysis": "Tabulated",
        "Research and Discovery": "Concluded",
        "Automation and Process Improvement": "Operationalized",
        "Reliability and Maintenance": "Hardened",
        "Leadership and Ownership": "Spearheaded",
        "Collaboration and Cross-Functional Work": "Liaised",
        "Communication and Documentation": "Translated",
        "User, Customer, or Stakeholder Impact": "Empowered",
    }
    for category, rare_verb in categories_and_rare_verbs.items():
        assert f"### {category}" in verbs
        assert f"* {rare_verb}" in verbs
    assert "## Verb Restrictions" in verbs
    for restricted, condition in {
        "Architected": "high-level structural or system-design decisions",
        "Spearheaded": "initiated and led a significant effort",
        "Drove": "measurable result",
        "Deployed": "confirmed target environment",
    }.items():
        assert f"**{restricted}**" in verbs
        assert condition in verbs
    assert "better reflects the evidence" in verbs


def test_bullet_guide_rules_preserve_core_content():
    rules = (ROOT / "_bullet_guide_rules.jinja").read_text()
    assert "### Core Rule" in rules
    assert "### Writing Rules" in rules
    assert "Do not:" in rules
    assert "### Ownership Calibration" in rules
    for level in (
        "Supported",
        "Contributed",
        "Implemented",
        "Co-developed",
        "Developed",
        "Led",
        "Owned",
    ):
        assert f"**{level}**" in rules
    assert "### Bullet Templates" in rules
    assert "### Final Bullet Test" in rules
    assert "every bullet as a concise, evidence-backed accomplishment" in rules


def test_bullet_guide_is_included_in_every_bullet_authoring_stage():
    for name in ("tailor_work.jinja", "tailor_projects.jinja", "holistic_review.jinja"):
        prompt = (ROOT / name).read_text()
        assert '{% include "_bullet_guide_rules.jinja" %}' in prompt
        assert '{% include "_action_verbs.jinja" %}' in prompt
