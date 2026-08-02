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
