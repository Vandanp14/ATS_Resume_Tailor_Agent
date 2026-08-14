"""
Template Manager for Resume Tailoring Prompts

This module provides functionality to load and render Jinja templates for
the tailoring pipeline (JD parsing, per-section tailoring, and match scoring).
The template registry is intentionally empty here; Wave 2 (Task B) fills it.
"""

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, Template


logger = logging.getLogger(__name__)


class TemplateManager:
    """
    Manages Jinja templates for the resume tailoring pipeline.

    This class provides functionality to load and render templates for the
    tailoring stages (JD parse, evidence planning, skills/work/projects, and
    holistic review).
    """

    def __init__(self, template_dir: str = "prompts/templates"):
        """
        Initialize the template manager.

        Args:
            template_dir (str): Directory containing Jinja templates
        """
        self.template_dir = Path(template_dir)
        self.env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._templates: dict[str, Template] = {}
        self._load_templates()

    def _load_templates(self) -> None:
        """Load all available templates.

        Each entry maps a logical template name to its ``.jinja`` filename
        under ``self.template_dir``. ``_tailoring_rules.jinja`` is intentionally
        NOT registered here: it is a shared partial (truth floor + ATS-rubric
        pressure) pulled in via ``{% include %}`` by the tailor_* and
        holistic_review template, never rendered standalone.
        """
        template_files: dict[str, str] = {
            "jd_parse": "jd_parse.jinja",
            "research_company_stack": "research_company_stack.jinja",
            "research_company_signals": "research_company_signals.jinja",
            "plan_evidence": "plan_evidence.jinja",
            "plan_skill_bridges": "plan_skill_bridges.jinja",
            "tailor_skills": "tailor_skills.jinja",
            "tailor_work": "tailor_work.jinja",
            "tailor_projects": "tailor_projects.jinja",
            "select_work": "select_work.jinja",
            "select_projects": "select_projects.jinja",
            "holistic_review": "holistic_review.jinja",
            "concise_bullet": "concise_bullet.jinja",
            "audit_concision": "audit_concision.jinja",
            "system_message": "system_message.jinja",
        }

        for section_name, filename in template_files.items():
            try:
                template_path = self.template_dir / filename
                if template_path.exists():
                    self._templates[section_name] = self.env.get_template(filename)
                else:
                    logger.warning("Template file not found: %s", template_path)
            except Exception:
                logger.exception("Error loading template %s", filename)

    def get_available_sections(self) -> list[str]:
        """
        Get list of available section names.

        Returns:
            list: Available section names.
        """
        return list(self._templates.keys())

    def render_template(self, section_name: str, **kwargs: object) -> str | None:
        """
        Render a template for a specific section.

        Args:
            section_name (str): Name of the section (basics, work, education, etc.)
            **kwargs: Template variables (e.g., text_content)

        Returns:
            str | None: Rendered template string, or None if unavailable.
        """
        if section_name not in self._templates:
            logger.error(
                "Template not found for section %s; available=%s",
                section_name,
                self.get_available_sections(),
            )
            return None

        try:
            template = self._templates[section_name]
            return template.render(**kwargs)
        except Exception:
            logger.exception("Error rendering template for %s", section_name)
            return None
