"""High-level tailoring pipeline with observable stage boundaries."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from models import (
    CandidateSelection,
    EvidencePlan,
    HolisticReview,
    JDProfile,
    JSONResume,
    ProjectRewriteItem,
    ProjectRewriteResponse,
    TailoredSkills,
    TransferableSkillPlan,
    WorkRewriteItem,
    WorkRewriteResponse,
)
from prompts.template_manager import TemplateManager

from .assembly import (
    PipelineComponents,
    apply_review_edits,
    assemble_scored,
    cross_entry_attributions,
    inferred_metrics,
    partition_review_truth_violations,
    scan_bullet_style,
    transferable_skill_injections,
)
from .config import DEFAULT_MODEL, MODEL_PARAMETERS
from .evidence import (
    ContractError,
    SelectedEvidence,
    choose_selected,
    global_evidence_payload,
    master_fact_index,
    project_evidence,
    validate_evidence_plan,
    validate_project_item,
    validate_skills,
    validate_transferable_skill_plan,
    validate_work_item,
    work_bullet_targets,
    work_evidence,
)
from .llm import (
    ChatProvider,
    LLMExtractionError,
    call_llm_with_retry,
    initialize_llm_provider,
)
from .progress import JobContext, ProgressReporter, ProgressTracker, Stage
from .rendering import (
    RenderError,
    ensure_tectonic,
    fit_to_one_page,
    render,
    scored_to_plain,
)
from .runtime import (
    DEFAULT_CALL_INTERVAL,
    MAX_SELECTED_PROJECTS,
    MAX_SELECTED_WORK,
    PROJECT_REWRITE_BATCH_SIZE,
    PacedProvider,
    RatePacer,
    StageFailure,
    clear_artifacts,
    write_json,
)
from .stages import StageExecutor


_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE_DIR = _ROOT / "prompts" / "templates"
_TEMPLATE_STAGES = {
    "jd_parse": Stage.PARSE_JD,
    "select_work": Stage.SELECT_WORK,
    "select_projects": Stage.SELECT_PROJECTS,
    "plan_evidence": Stage.PLAN_EVIDENCE,
    "plan_skill_bridges": Stage.PLAN_TRANSFERABLE_SKILLS,
    "tailor_skills": Stage.TAILOR_SKILLS,
    "tailor_work": Stage.REWRITE_WORK,
    "tailor_projects": Stage.REWRITE_PROJECTS,
    "holistic_review": Stage.HOLISTIC_REVIEW,
}


class TailorPipeline:
    """One parse/select/rewrite/assemble/review/render pass."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        call_interval: float = DEFAULT_CALL_INTERVAL,
        provider: ChatProvider | None = None,
        reporter: ProgressReporter | None = None,
        bridge_skills: bool = False,
    ) -> None:
        self.model = model
        self.bridge_skills = bridge_skills
        self.tracker = ProgressTracker(reporter)
        self.stage_executor = StageExecutor(self.tracker)
        raw_provider = provider or initialize_llm_provider(
            model, progress_callback=lambda message: self.tracker.detail(message)
        )
        self.provider: ChatProvider = PacedProvider(
            raw_provider, RatePacer(call_interval, self.tracker)
        )
        self.templates = TemplateManager(str(_TEMPLATE_DIR))
        self.options = MODEL_PARAMETERS.get(model, {"temperature": 0.1, "top_p": 0.9})

    def _messages(self, template_name: str, **context: object) -> list[dict[str, str]]:
        stage = {
            "jd_parse": "JD parse",
            "holistic_review": "holistic review",
        }.get(template_name, template_name.replace("_", " "))
        system = self.templates.render_template("system_message", stage=stage)
        prompt = self.templates.render_template(template_name, **context)
        if not prompt:
            raise StageFailure(
                template_name, 0, [], None, "prompt template unavailable"
            )
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _call_once[_Result: BaseModel](
        self,
        template_name: str,
        response_model: type[_Result],
        **context: object,
    ) -> _Result:
        options = dict(self.options)
        if template_name in {
            "jd_parse",
            "select_work",
            "select_projects",
            "plan_evidence",
            "plan_skill_bridges",
            "tailor_skills",
            "holistic_review",
        }:
            options.update({"temperature": 0.0, "top_p": 1.0})
        return call_llm_with_retry(
            self.provider,
            self.model,
            self._messages(template_name, **context),
            response_model,
            options=options,
            max_retries=0,
        )  # type: ignore[return-value]

    def _retry(self, template_name: str, attempt: int, error: object) -> None:
        self.tracker.retry(
            _TEMPLATE_STAGES[template_name],
            attempt=attempt,
            max_attempts=2,
            message=str(error),
        )

    def _simple_stage[_Result: BaseModel](
        self,
        template_name: str,
        response_model: type[_Result],
        selected_ids: Sequence[str] = (),
        validator: Any | None = None,
        **context: object,
    ) -> _Result:
        def operation(attempt: int, prior_error: Exception | None) -> _Result:
            call_context = dict(context)
            if attempt > 1:
                call_context["feedback"] = "Correct the previous response. " + str(
                    prior_error
                )
            return self._call_once(template_name, response_model, **call_context)

        return self.stage_executor.run(
            name=template_name,
            stage=_TEMPLATE_STAGES[template_name],
            operation=operation,
            selected_ids=selected_ids,
            validator=validator,
        )

    def _parse_jd(self, jd_text: str) -> JDProfile:
        return self._simple_stage("jd_parse", JDProfile, jd_text=jd_text)

    @staticmethod
    def _partial_entries(
        values: Sequence[Any], expected: dict[str, dict], validator: Any
    ) -> tuple[dict[str, Any], set[str], list[str]]:
        grouped: dict[str, list[Any]] = {}
        unknown: list[str] = []
        for value in values:
            if value.source_id not in expected:
                unknown.append(value.source_id)
            else:
                grouped.setdefault(value.source_id, []).append(value)
        accepted: dict[str, Any] = {}
        invalid: set[str] = set()
        errors: list[str] = []
        for source_id, items in grouped.items():
            if len(items) != 1:
                invalid.add(source_id)
                errors.append(f"duplicate source_id {source_id}")
                continue
            try:
                validator(items[0], expected[source_id])
                accepted[source_id] = items[0]
            except ContractError as exc:
                invalid.add(source_id)
                errors.append(str(exc))
        if unknown:
            errors.append(f"unknown source IDs: {sorted(unknown)}")
        unresolved = set(expected) - set(accepted)
        return accepted, unresolved | invalid, errors

    def _select(
        self,
        template: str,
        section: str,
        jd_json: str,
        evidence: Sequence[dict],
        cap: int,
    ) -> list[dict]:
        del section
        if not evidence:
            return []
        expected = {item["source_id"]: item for item in evidence}
        accepted: dict[str, Any] = {}
        last: object = None
        errors: list[str] = []
        pending = list(expected)
        for attempt in (1, 2):
            subset = [expected[source_id] for source_id in pending]
            try:
                result = self._call_once(
                    template,
                    CandidateSelection,
                    jd_profile_json=jd_json,
                    candidates_json=json.dumps(subset, indent=2),
                    feedback=(
                        None
                        if attempt == 1
                        else "Return only these missing or invalid source IDs exactly once: "
                        + ", ".join(pending)
                    ),
                )
                last = result
            except LLMExtractionError as exc:
                last = exc.raw_response
                errors.append(str(exc))
                if attempt == 2:
                    break
                self._retry(template, 2, exc)
                pending = list(expected)
                continue
            partial, unresolved, partial_errors = self._partial_entries(
                result.candidates,
                {source_id: expected[source_id] for source_id in pending},
                lambda _candidate, _source: None,
            )
            if any(error.startswith("unknown source IDs") for error in partial_errors):
                raise StageFailure(
                    template, attempt, list(expected), result, "; ".join(partial_errors)
                )
            errors.extend(partial_errors)
            accepted.update(partial)
            pending = [source_id for source_id in pending if source_id in unresolved]
            if not pending:
                try:
                    return choose_selected(accepted, evidence, cap)
                except ContractError as exc:
                    errors.append(str(exc))
                    if attempt == 1:
                        self._retry(template, 2, exc)
                        accepted.clear()
                        pending = list(expected)
                        continue
                    break
            if attempt == 1:
                self._retry(template, 2, "; ".join(partial_errors) or "missing entries")
        raise StageFailure(template, 2, list(expected), last, "; ".join(errors))

    def _rewrite_work(
        self,
        jd_json: str,
        sources: Sequence[dict],
        evidence_plan: EvidencePlan,
        transferable_skill_plan: TransferableSkillPlan,
        fact_index: dict[str, dict],
    ) -> list[WorkRewriteItem]:
        if not sources:
            return []
        expected = {item["source_id"]: item for item in sources}
        accepted: dict[str, WorkRewriteItem] = {}
        pending = list(expected)
        last: object = None
        errors: list[str] = []
        for attempt in (1, 2):
            subset = [expected[source_id] for source_id in pending]
            try:
                result = self._call_once(
                    "tailor_work",
                    WorkRewriteResponse,
                    jd_profile_json=jd_json,
                    selected_work_json=json.dumps(subset, indent=2),
                    evidence_assignments_json=json.dumps(
                        [
                            assignment.model_dump(mode="json")
                            for assignment in evidence_plan.assignments
                            if assignment.destination_work_id in pending
                        ],
                        indent=2,
                    ),
                    transferable_skill_keywords_json=json.dumps(
                        [item.keyword for item in transferable_skill_plan.skills]
                    ),
                    feedback=(
                        None
                        if attempt == 1
                        else "Rewrite only these missing or invalid source IDs: "
                        + ", ".join(pending)
                    ),
                )
                last = result
            except LLMExtractionError as exc:
                last = exc.raw_response
                errors.append(str(exc))
                if attempt == 2:
                    break
                self._retry("tailor_work", 2, exc)
                pending = list(expected)
                accepted.clear()
                continue
            partial, unresolved, partial_errors = self._partial_entries(
                result.work,
                {source_id: expected[source_id] for source_id in pending},
                lambda item, source: validate_work_item(
                    item,
                    source,
                    evidence_plan,
                    fact_index,
                    transferable_skill_plan,
                ),
            )
            if any(error.startswith("unknown source IDs") for error in partial_errors):
                raise StageFailure(
                    "tailor_work",
                    attempt,
                    list(expected),
                    result,
                    "; ".join(partial_errors),
                )
            accepted.update(partial)
            errors.extend(partial_errors)
            pending = [source_id for source_id in pending if source_id in unresolved]
            if not pending:
                return [accepted[item["source_id"]] for item in sources]
            if attempt == 1:
                self._retry(
                    "tailor_work", 2, "; ".join(partial_errors) or "missing entries"
                )
        raise StageFailure("tailor_work", 2, list(expected), last, "; ".join(errors))

    def _rewrite_project_batch(
        self,
        jd_json: str,
        sources: Sequence[dict],
        batch_number: int,
        batch_total: int,
        transferable_skill_plan: TransferableSkillPlan,
        fact_index: dict[str, dict],
    ) -> list[ProjectRewriteItem]:
        self.tracker.detail(
            f"Project rewrite batch {batch_number}/{batch_total}", verbose_only=False
        )
        expected = {item["source_id"]: item for item in sources}
        accepted: dict[str, ProjectRewriteItem] = {}
        pending = list(expected)
        last: object = None
        errors: list[str] = []
        for attempt in (1, 2):
            subset = [expected[source_id] for source_id in pending]
            try:
                result = self._call_once(
                    "tailor_projects",
                    ProjectRewriteResponse,
                    jd_profile_json=jd_json,
                    selected_projects_json=json.dumps(subset, indent=2),
                    transferable_skill_keywords_json=json.dumps(
                        [item.keyword for item in transferable_skill_plan.skills]
                    ),
                    feedback=(
                        None
                        if attempt == 1
                        else "Rewrite only these missing or invalid source IDs: "
                        + ", ".join(pending)
                    ),
                )
                last = result
            except LLMExtractionError as exc:
                last = exc.raw_response
                errors.append(str(exc))
                if attempt == 2:
                    break
                self._retry("tailor_projects", 2, exc)
                pending = list(expected)
                accepted.clear()
                continue
            partial, unresolved, partial_errors = self._partial_entries(
                result.projects,
                {source_id: expected[source_id] for source_id in pending},
                lambda item, source: validate_project_item(
                    item, source, fact_index, transferable_skill_plan
                ),
            )
            if any(error.startswith("unknown source IDs") for error in partial_errors):
                raise StageFailure(
                    f"tailor_projects.batch_{batch_number}",
                    attempt,
                    list(expected),
                    result,
                    "; ".join(partial_errors),
                )
            accepted.update(partial)
            errors.extend(partial_errors)
            pending = [source_id for source_id in pending if source_id in unresolved]
            if not pending:
                return [accepted[item["source_id"]] for item in sources]
            if attempt == 1:
                self._retry(
                    "tailor_projects",
                    2,
                    "; ".join(partial_errors) or "missing entries",
                )
        raise StageFailure(
            f"tailor_projects.batch_{batch_number}",
            2,
            list(expected),
            last,
            "; ".join(errors),
        )

    def _rewrite_projects(
        self,
        jd_json: str,
        sources: Sequence[dict],
        transferable_skill_plan: TransferableSkillPlan,
        fact_index: dict[str, dict],
    ) -> list[ProjectRewriteItem]:
        rewritten: list[ProjectRewriteItem] = []
        batch_total = max(
            1,
            (len(sources) + PROJECT_REWRITE_BATCH_SIZE - 1)
            // PROJECT_REWRITE_BATCH_SIZE,
        )
        for start in range(0, len(sources), PROJECT_REWRITE_BATCH_SIZE):
            batch = sources[start : start + PROJECT_REWRITE_BATCH_SIZE]
            rewritten.extend(
                self._rewrite_project_batch(
                    jd_json,
                    batch,
                    start // PROJECT_REWRITE_BATCH_SIZE + 1,
                    batch_total,
                    transferable_skill_plan,
                    fact_index,
                )
            )
        return rewritten

    def run(
        self,
        master: JSONResume,
        jd_text: str,
        out_dir: Path,
        no_pdf: bool = False,
        job: JobContext | None = None,
    ) -> int:
        out_dir = Path(out_dir)
        self.tracker.job = job
        try:
            with self.tracker.stage(Stage.PREFLIGHT):
                self.tracker.detail(f"Model: {self.model}")
                clear_artifacts(out_dir)
                if not no_pdf:
                    ensure_tectonic()

            with self.tracker.stage(Stage.PARSE_JD):
                jd = self._parse_jd(jd_text)
                jd_json = jd.model_dump_json(indent=2)

            all_work = work_evidence(master)
            all_projects = project_evidence(master)
            with self.tracker.stage(Stage.SELECT_WORK):
                selected_work = tuple(
                    self._select(
                        "select_work", "work", jd_json, all_work, MAX_SELECTED_WORK
                    )
                )
            with self.tracker.stage(Stage.SELECT_PROJECTS):
                selected_projects = tuple(
                    self._select(
                        "select_projects",
                        "projects",
                        jd_json,
                        all_projects,
                        MAX_SELECTED_PROJECTS,
                    )
                )
            selected = SelectedEvidence(work=selected_work, projects=selected_projects)

            facts = master_fact_index(master)
            targets = work_bullet_targets(selected.work)
            with self.tracker.stage(Stage.PLAN_EVIDENCE):
                evidence_plan = self._simple_stage(
                    "plan_evidence",
                    EvidencePlan,
                    selected_ids=list(targets),
                    validator=lambda value: validate_evidence_plan(
                        value, selected.work, facts
                    ),
                    jd_profile_json=jd_json,
                    global_evidence_json=json.dumps(
                        global_evidence_payload(master), indent=2
                    ),
                    selected_work_destinations_json=json.dumps(
                        [
                            {
                                "source_id": item["source_id"],
                                "name": item.get("name"),
                                "position": item.get("position"),
                                "startDate": item.get("startDate"),
                                "endDate": item.get("endDate"),
                                "required_bullets": targets[item["source_id"]],
                                "selection_relevance": item.get("selection_relevance"),
                                "matched_requirements": item.get(
                                    "selection_matched_requirements", []
                                ),
                            }
                            for item in selected.work
                        ],
                        indent=2,
                    ),
                    bullet_targets_json=json.dumps(targets, indent=2),
                )

            transferable_skill_plan = TransferableSkillPlan(skills=[])
            if self.bridge_skills:
                with self.tracker.stage(Stage.PLAN_TRANSFERABLE_SKILLS):
                    transferable_skill_plan = self._simple_stage(
                        "plan_skill_bridges",
                        TransferableSkillPlan,
                        validator=lambda value: validate_transferable_skill_plan(
                            value, jd, master, facts
                        ),
                        jd_profile_json=jd_json,
                        global_evidence_json=json.dumps(
                            global_evidence_payload(master), indent=2
                        ),
                        master_skill_keywords_json=json.dumps(
                            [
                                keyword
                                for group in master.skills or []
                                for keyword in group.keywords or []
                            ],
                            indent=2,
                        ),
                    )

            with self.tracker.stage(Stage.TAILOR_SKILLS):
                skills: TailoredSkills | None = None
                if master.skills or transferable_skill_plan.skills:
                    skills = self._simple_stage(
                        "tailor_skills",
                        TailoredSkills,
                        validator=lambda value: validate_skills(
                            value, master, transferable_skill_plan
                        ),
                        jd_profile_json=jd_json,
                        master_skills_json=json.dumps(
                            [
                                item.model_dump(mode="json")
                                for item in master.skills or []
                            ],
                            indent=2,
                        ),
                        transferable_skill_plan_json=(
                            transferable_skill_plan.model_dump_json(indent=2)
                        ),
                    )
            with self.tracker.stage(Stage.REWRITE_WORK):
                work = tuple(
                    self._rewrite_work(
                        jd_json,
                        selected.work,
                        evidence_plan,
                        transferable_skill_plan,
                        facts,
                    )
                )
            with self.tracker.stage(Stage.REWRITE_PROJECTS):
                projects = tuple(
                    self._rewrite_projects(
                        jd_json,
                        selected.projects,
                        transferable_skill_plan,
                        facts,
                    )
                )
            components = PipelineComponents(
                skills=skills,
                work=work,
                projects=projects,
                selected=selected,
                evidence_plan=evidence_plan,
                transferable_skill_plan=transferable_skill_plan,
            )
            with self.tracker.stage(Stage.ASSEMBLE):
                draft = assemble_scored(master, components)
                draft_plain = scored_to_plain(draft)

            with self.tracker.stage(Stage.HOLISTIC_REVIEW):
                review = self._simple_stage(
                    "holistic_review",
                    HolisticReview,
                    jd_profile_json=jd_json,
                    master_json=master.model_dump_json(indent=2),
                    tailored_resume_json=draft_plain.model_dump_json(indent=2),
                    evidence_plan_json=evidence_plan.model_dump_json(indent=2),
                    transferable_skill_plan_json=(
                        transferable_skill_plan.model_dump_json(indent=2)
                    ),
                    generated_components_json=json.dumps(
                        {
                            "skills": (
                                skills.model_dump(mode="json") if skills else None
                            ),
                            "work": [item.model_dump(mode="json") for item in work],
                            "projects": [
                                item.model_dump(mode="json") for item in projects
                            ],
                        },
                        indent=2,
                    ),
                    selection_metadata_json=json.dumps(
                        {
                            "work": [item["source_id"] for item in selected.work],
                            "projects": [
                                item["source_id"] for item in selected.projects
                            ],
                            "work_bullet_targets": targets,
                            "project_bullet_target": 2,
                        },
                        indent=2,
                    ),
                )

            with self.tracker.stage(Stage.VALIDATE_REVIEW):
                jd_keywords = [
                    *jd.must_have_skills,
                    *jd.nice_to_have_skills,
                    *(item.term for item in jd.keywords),
                ]
                edited_components, rejected_edits = apply_review_edits(
                    review, master, components, jd_keywords=jd_keywords
                )
                final_scored = assemble_scored(
                    master, edited_components, jd_keywords=jd_keywords
                )
                for style_message in scan_bullet_style(final_scored):
                    self.tracker.warn(f"Bullet style: {style_message}")
                report_payload = review.model_dump(mode="json")
                report_payload["rejected_section_edits"] = rejected_edits
                report_payload["cross_entry_attributions"] = cross_entry_attributions(
                    evidence_plan, facts
                )
                report_payload["inferred_metrics"] = inferred_metrics(evidence_plan)
                report_payload["transferable_skill_injections"] = (
                    transferable_skill_injections(transferable_skill_plan)
                )
                unresolved_violations, resolved_violations = (
                    partition_review_truth_violations(review, final_scored)
                )
                report_payload["truth_violations"] = [
                    item.model_dump(mode="json") for item in unresolved_violations
                ]
                report_payload["resolved_truth_violations"] = [
                    item.model_dump(mode="json") for item in resolved_violations
                ]

            if unresolved_violations:
                report_payload["pipeline_status"] = "blocked_truth_violations"
                write_json(out_dir / "match_report.json", report_payload)
                return 1
            for message in rejected_edits:
                self.tracker.warn(f"Reviewer edit rejected: {message}")

            with self.tracker.stage(Stage.RENDER):
                if no_pdf:
                    final_plain = scored_to_plain(final_scored)
                    render(final_plain, out_dir, False)
                else:
                    final_plain = fit_to_one_page(
                        final_scored,
                        out_dir,
                        progress_callback=lambda message: self.tracker.detail(message),
                    )
            with self.tracker.stage(Stage.WRITE_ARTIFACTS):
                write_json(out_dir / "tailored.json", final_plain)
                report_payload["pipeline_status"] = (
                    "completed_with_rejected_edits" if rejected_edits else "completed"
                )
                write_json(out_dir / "match_report.json", report_payload)
                write_json(out_dir / ".done", {"pdf": not no_pdf})
            return 0
        except StageFailure as exc:
            write_json(out_dir / "diagnostic_report.json", exc.diagnostic())
            raise
        except (ContractError, LLMExtractionError) as exc:
            failure = StageFailure("pipeline_validation", 1, [], None, exc)
            write_json(out_dir / "diagnostic_report.json", failure.diagnostic())
            raise failure from exc
        except RenderError as exc:
            failure = StageFailure("render", 1, [], None, exc)
            clear_artifacts(out_dir)
            write_json(out_dir / "diagnostic_report.json", failure.diagnostic())
            raise failure from exc
