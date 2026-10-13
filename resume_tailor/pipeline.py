"""High-level tailoring pipeline with observable stage boundaries."""

from __future__ import annotations

import json
import inspect
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from models import (
    BulletConcision,
    CandidateSelection,
    CompanyHiringSignals,
    CompanyStackResearch,
    ConcisionAudit,
    EvidencePlan,
    HolisticReview,
    JDProfile,
    JSONResume,
    ProjectRewriteItem,
    ProjectRewriteResponse,
    RequirementProxyPlan,
    TailoredSkills,
    TransferableSkillPlan,
    WorkRewriteItem,
    WorkRewriteResponse,
)
from keyword_coverage import (
    attach_proxies,
    forbidden_claim_terms,
    missing_requirements,
    placement_findings,
    priority_proxies,
    prompt_requirement_map,
    requirement_map,
    resume_coverage,
    sanitize_jd_profile,
    supported_tech_requirements,
)
from llm_utils import (
    ModelRouter,
    describe_api_error,
    is_model_unavailable,
    is_persistent_unavailability,
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
    scan_metric_quality,
    scan_unsupported_technology,
    transferable_skill_injections,
    waive_cross_entry_objections,
)
from .config import (
    DEFAULT_MODEL,
    FALLBACK_MODELS,
    MODEL_PARAMETERS,
    OPENROUTER_MODEL_PREFIX,
    PLANNING_MODELS,
)
from .evidence import (
    RESEARCH_THIN_JD_SIGNAL_THRESHOLD,
    ContractError,
    SelectedEvidence,
    align_inference_provenance,
    bullet_text_problems,
    choose_selected,
    global_evidence_payload,
    jd_signal_is_thin,
    jd_signal_strength,
    master_fact_index,
    proxy_coverage_gaps,
    repair_allocation_provenance,
    salvage_project_item,
    salvage_work_item,
    sanitize_target_terms,
    technologies_in_experience,
    transferable_plan_from_proxies,
    validate_evidence_plan,
    validate_concise_bullet,
    validate_project_item,
    validate_requirement_proxy_plan,
    validate_skills,
    validate_transferable_skill_plan,
    validate_work_item,
    work_bullet_targets,
)
from .llm import (
    ChatProvider,
    LLMExtractionError,
    call_llm_with_retry,
    initialize_llm_provider,
)
from .progress import JobContext, ProgressReporter, ProgressTracker, Stage
from .bullet_review import live_flags, persist_bullet_review
from .checkpoints import CheckpointStore, run_fingerprint
from .fit_recovery import (
    FitRecoveryRequired,
    persist_fit_recovery,
)
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
    ModelUnavailableError,
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
    "research_company_stack": Stage.RESEARCH_COMPANY_STACK,
    "research_company_signals": Stage.RESEARCH_COMPANY_SIGNALS,
    "select_work": Stage.SELECT_WORK,
    "select_projects": Stage.SELECT_PROJECTS,
    "plan_evidence": Stage.PLAN_EVIDENCE,
    "plan_requirement_coverage": Stage.MAP_REQUIREMENTS,
    "tailor_skills": Stage.TAILOR_SKILLS,
    "tailor_work": Stage.REWRITE_WORK,
    "tailor_projects": Stage.REWRITE_PROJECTS,
    "holistic_review": Stage.HOLISTIC_REVIEW,
    "concise_bullet": Stage.EMERGENCY_CONCISION,
    "audit_concision": Stage.CONCISION_AUDIT,
    "regenerate_bullet": Stage.BULLET_REVIEW,
}


# Reasoning-heavy stages run on the planning chain (stronger models first).
PLANNING_TEMPLATES = frozenset(
    {
        "plan_requirement_coverage",
        "select_work",
        "select_projects",
        "plan_evidence",
        "holistic_review",
    }
)
_DETERMINISTIC_TEMPLATES = frozenset(
    {
        "jd_parse",
        "plan_requirement_coverage",
        "select_work",
        "select_projects",
        "plan_evidence",
        "tailor_skills",
        "holistic_review",
        "audit_concision",
    }
)
_PLANNING_MAX_OUTPUT_TOKENS = 32768
# A model that is merely overloaded (503) or slow is retried after this many
# seconds; a retired model or exhausted quota stays skipped for the run.
TRANSIENT_COOLDOWN_SECONDS = 90.0
# Rewrites get one strict attempt (technology-support check on, with feedback)
# plus two lenient ones, so the stricter first pass never costs the run.
REWRITE_ATTEMPTS = 3
# When every model in a chain is only overloaded or slow, wait and run the
# whole chain again instead of stopping the job.
CHAIN_RETRY_DELAYS_SECONDS = (30.0, 60.0)
# With a fallback available, a model gets one transport try, and an optional
# stronger planning model gets a shorter timeout than the default model: a
# hanging model (Google can take minutes to answer 504) must not stall a stage.
PLANNING_MODEL_TIMEOUT_MS = 60_000


def _dedupe(models: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(model for model in models if model))


def _dump_optional(value: BaseModel | None) -> object:
    return value.model_dump(mode="json") if value is not None else None


def _restore_optional[_M: BaseModel](
    model: type[_M],
) -> Callable[[Any], _M | None]:
    return lambda payload: model.model_validate(payload) if payload else None


def _provider_supports_grounding(model: str) -> bool:
    """Gemini's web-search grounding tool has no Ollama equivalent."""
    return model.startswith("gemini")


class _ConcisionController:
    """One-bullet-at-a-time recovery invoked only at renderer exhaustion."""

    def __init__(
        self,
        pipeline: "TailorPipeline",
        fact_index: dict[str, dict],
        evidence_plan: EvidencePlan,
    ) -> None:
        self.pipeline = pipeline
        self.fact_index = fact_index
        self.assignments = {
            item.assignment_id: item for item in evidence_plan.assignments
        }
        self.attempted: set[str] = set()
        self.log: list[dict[str, object]] = []
        self._audited = False

    @staticmethod
    def _candidate_id(section: str, item_index: int, bullet_index: int) -> str:
        return f"{section}:{item_index}:{bullet_index}"

    def _next_candidate(self, resume: object):
        candidates = []
        for section_index, (section, entries) in enumerate(
            (("work", resume.work or []), ("projects", resume.projects or []))
        ):
            for item_index, item in enumerate(entries):
                for bullet_index, bullet in enumerate(item.highlights or []):
                    candidate_id = self._candidate_id(section, item_index, bullet_index)
                    word_count = len(bullet.text.split())
                    if candidate_id in self.attempted or word_count <= 10:
                        continue
                    candidates.append(
                        (
                            bullet.relevance,
                            -word_count,
                            section_index,
                            item_index,
                            bullet_index,
                            candidate_id,
                            bullet,
                        )
                    )
        return min(candidates) if candidates else None

    def audit(self) -> None:
        if self._audited or not self.log:
            return
        expected = [str(item["candidate_id"]) for item in self.log]

        def validate(result: ConcisionAudit) -> None:
            actual = [item.candidate_id for item in result.items]
            if actual != expected:
                raise ContractError(
                    f"concision audit IDs changed: expected={expected}, actual={actual}"
                )
            unsupported = [
                f"{item.candidate_id}: {item.reason}"
                for item in result.items
                if not item.supported
            ]
            if unsupported:
                raise ContractError(
                    "concision audit rejected rewrite(s): " + "; ".join(unsupported)
                )

        source_ids = {
            source_id for item in self.log for source_id in item.get("source_ids", [])
        }
        self.pipeline._simple_stage(
            "audit_concision",
            ConcisionAudit,
            selected_ids=expected,
            validator=validate,
            changes_json=json.dumps(self.log, indent=2),
            source_facts_json=json.dumps(
                [self.fact_index[source_id] for source_id in sorted(source_ids)],
                indent=2,
            ),
        )
        self._audited = True

    def __call__(self, resume, pages: int, trim_log: tuple[str, ...]) -> str | None:
        candidate = self._next_candidate(resume)
        if candidate is None:
            self.audit()
            if self.pipeline.allow_fit_recovery:
                raise FitRecoveryRequired(resume, pages, trim_log, self.log)
            return None

        (
            relevance,
            negative_words,
            _section_index,
            item_index,
            bullet_index,
            candidate_id,
            bullet,
        ) = candidate
        del negative_words
        self.attempted.add(candidate_id)
        original_text = bullet.text
        original_words = len(original_text.split())
        target_words = min(24, max(10, int(original_words * 0.75)))
        source_facts = [self.fact_index[item] for item in bullet.source_ids]
        assignment = self.assignments.get(bullet.evidence_assignment_id or "")
        section = candidate_id.replace(":", "[", 1).replace(":", "] bullet ", 1)

        def validate(result: BulletConcision) -> None:
            result.text = " ".join(result.text.split())
            validate_concise_bullet(
                bullet,
                result.text,
                max_words=target_words,
                fact_index=self.fact_index,
                assignment=assignment,
                section=section,
            )

        self.pipeline.tracker.detail(
            "One-page fit exhausted protected trims; invoking emergency concision"
        )
        result = self.pipeline._simple_stage(
            "concise_bullet",
            BulletConcision,
            selected_ids=[candidate_id],
            validator=validate,
            target_words=target_words,
            original_bullet_json=json.dumps(bullet.model_dump(mode="json"), indent=2),
            source_facts_json=json.dumps(source_facts, indent=2),
        )
        bullet.text = result.text
        final_words = len(result.text.split())
        self.log.append(
            {
                "candidate_id": candidate_id,
                "section": candidate_id.split(":", 1)[0],
                "item_index": item_index,
                "bullet_index": bullet_index,
                "relevance": relevance,
                "original_text": original_text,
                "final_text": result.text,
                "original_words": original_words,
                "final_words": final_words,
                "source_ids": list(bullet.source_ids),
            }
        )
        return (
            f"emergency concision {candidate_id} (rel={relevance}, "
            f"{original_words} -> {final_words} words)"
        )


class TailorPipeline:
    """One parse/select/rewrite/assemble/review/render pass."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        call_interval: float = DEFAULT_CALL_INTERVAL,
        provider: ChatProvider | None = None,
        reporter: ProgressReporter | None = None,
        bridge_skills: bool = False,
        allow_fit_recovery: bool = False,
        research_company: bool = False,
        planning_models: Sequence[str] | None = None,
        fallback_models: Sequence[str] | None = None,
    ) -> None:
        self.model = model
        self.bridge_skills = bridge_skills
        self.allow_fit_recovery = allow_fit_recovery
        self.research_company = research_company
        self.tracker = ProgressTracker(reporter)
        self.stage_executor = StageExecutor(self.tracker)
        raw_provider = provider or ModelRouter(
            model, progress_callback=lambda message: self.tracker.detail(message)
        )
        self.provider: ChatProvider = PacedProvider(
            raw_provider, RatePacer(call_interval, self.tracker)
        )
        self.templates = TemplateManager(str(_TEMPLATE_DIR))
        self.options = MODEL_PARAMETERS.get(model, {"temperature": 0.1, "top_p": 0.9})
        # Model chains apply only to Gemini through the real client (built here,
        # or wrapped by a provider that declares ``supports_model_chain``, like
        # the web scheduler). Other injected providers stay on ``model`` alone.
        real_client = provider is None or (
            getattr(type(provider), "supports_model_chain", False) is True
        )
        chains_enabled = real_client and model.startswith(
            ("gemini", OPENROUTER_MODEL_PREFIX)
        )
        if planning_models is None:
            planning_models = PLANNING_MODELS if chains_enabled else ()
        if fallback_models is None:
            fallback_models = FALLBACK_MODELS if chains_enabled else ()
        self.default_chain = _dedupe([model, *fallback_models])
        self.planning_chain = _dedupe([*planning_models, *self.default_chain])
        self.planning_only_models = frozenset(self.planning_chain) - frozenset(
            self.default_chain
        )
        # Web-search grounding exists only on Gemini, so company research uses
        # the first Gemini model in the chain even when another provider leads.
        self.grounding_model = next(
            (
                name
                for name in (*self.default_chain, *self.planning_chain)
                if _provider_supports_grounding(name)
            ),
            None,
        )
        # model -> (API error text, skip-until monotonic time or None for the run)
        self._unavailable_models: dict[str, tuple[str, float | None]] = {}
        self._bullet_flags: list[dict] = []
        self._checkpoints: CheckpointStore | None = None
        self._resuming = False
        self._reused: list[str] = []
        self._grounding_exhausted = False

    def _messages(self, template_name: str, **context: object) -> list[dict[str, str]]:
        stage = {
            "jd_parse": "JD parse",
            "holistic_review": "holistic review",
            "research_company_stack": "company research",
            "research_company_signals": "company research",
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

    def _chain_for(self, template_name: str) -> tuple[str, ...]:
        return (
            self.planning_chain
            if template_name in PLANNING_TEMPLATES
            else self.default_chain
        )

    def _salvage(
        self,
        stage_name: str,
        sources: Sequence[dict],
        accepted: dict[str, Any],
        pending: Sequence[str],
        errors: Sequence[str],
        last: object,
        salvage: Any,
    ) -> list[Any]:
        """Finish entries the model never got valid instead of failing the run.

        Each flawed bullet becomes a safe version and a review flag; the web
        app later lets the user keep, accept, or regenerate it.
        """

        try:
            for source in sources:
                source_id = source["source_id"]
                if source_id not in pending:
                    continue
                item, flags = salvage(source)
                accepted[source_id] = item
                self._bullet_flags.extend(flags)
                for flag in flags:
                    self.tracker.warn(
                        f"Needs review: {flag['label']}: {flag['issues'][0]} "
                        f"Using safe version: {flag['safe_text'][:90]!r}"
                    )
        except ContractError as exc:
            raise StageFailure(
                stage_name,
                REWRITE_ATTEMPTS,
                list(pending),
                last,
                "; ".join([*errors, f"salvage failed: {exc}"]),
            ) from exc
        return [accepted[source["source_id"]] for source in sources]

    def _repaired(self, notes: Sequence[str]) -> None:
        for note in notes:
            self.tracker.detail(f"Repaired provenance: {note}")

    def _checkpointed[_T](
        self,
        name: str,
        compute: Callable[[], _T],
        dump: Callable[[_T], object],
        restore: Callable[[Any], _T],
    ) -> _T:
        """Reuse a stage result saved by an earlier failed run, else compute and save.

        Reuse stops at the first stage that must run again, so every later
        stage is rebuilt from fresh inputs.
        """

        store = self._checkpoints
        if store is not None and self._resuming:
            cached = store.load(name)
            if cached is not None:
                self._reused.append(name)
                self.tracker.detail("Reused from the earlier run", verbose_only=False)
                return restore(cached["payload"])
            self._resuming = False
            if self._reused:
                self.tracker.detail(
                    f"Resuming here; reused {len(self._reused)} earlier stage(s)",
                    verbose_only=False,
                )
        value = compute()
        if store is not None:
            store.save(name, dump(value))
        return value

    def _checkpointed_rewrite[_Item: BaseModel](
        self,
        name: str,
        item_model: type[_Item],
        compute: Callable[[], list[_Item]],
    ) -> list[_Item]:
        """Checkpoint rewrites together with the review flags their salvage added."""

        start = len(self._bullet_flags)

        def restore(payload: dict) -> list[_Item]:
            self._bullet_flags.extend(payload["flags"])
            return [item_model.model_validate(item) for item in payload["items"]]

        return self._checkpointed(
            name,
            compute,
            lambda items: {
                "items": [item.model_dump(mode="json") for item in items],
                "flags": self._bullet_flags[start:],
            },
            restore,
        )

    def _round_order(self, chain: Sequence[str]) -> list[str]:
        """Models to try this round: healthy ones in chain order, then cooling ones.

        A model that was merely busy a moment ago is still worth one more try
        before the whole stage sleeps; only retired or quota-exhausted models
        are left out.
        """

        healthy = [model for model in chain if not self._skipped(model)]
        cooling = sorted(
            (
                model
                for model in chain
                if model not in healthy
                and self._unavailable_models[model][1] is not None
            ),
            key=lambda model: self._unavailable_models[model][1] or 0.0,
        )
        return healthy + cooling

    def _skipped(self, model: str) -> bool:
        entry = self._unavailable_models.get(model)
        if entry is None:
            return False
        _, until = entry
        if until is not None and time.monotonic() >= until:
            del self._unavailable_models[model]
            return False
        return True

    def _call_once[_Result: BaseModel](
        self,
        template_name: str,
        response_model: type[_Result],
        **context: object,
    ) -> _Result:
        """One structured call, walking the stage's model chain on API outages.

        A model that is overloaded, rate-limited, or retired is skipped for the
        rest of the run. Errors every model shares (bad key, bad request) stop
        the run immediately; so does exhausting the chain. Both surface the
        API's own error text.
        """

        messages = self._messages(template_name, **context)
        chain = self._chain_for(template_name)
        rounds = len(CHAIN_RETRY_DELAYS_SECONDS) + 1 if len(chain) > 1 else 1
        failures: list[tuple[str, str]] = []
        for round_number in range(1, rounds + 1):
            ordered = self._round_order(chain)
            failures = [
                (model, self._unavailable_models[model][0])
                for model in chain
                if model not in ordered
            ]
            for position, model in enumerate(ordered):
                options = dict(MODEL_PARAMETERS.get(model, self.options))
                if template_name in _DETERMINISTIC_TEMPLATES:
                    options.update({"temperature": 0.0, "top_p": 1.0})
                if template_name in PLANNING_TEMPLATES and model != self.model:
                    options["max_output_tokens"] = _PLANNING_MAX_OUTPUT_TOKENS
                if len(chain) > 1:
                    options["transport_attempts"] = 1
                    if model in self.planning_only_models:
                        options["timeout_ms"] = PLANNING_MODEL_TIMEOUT_MS
                    self.tracker.detail(f"{template_name}: calling {model}")
                try:
                    result = call_llm_with_retry(
                        self.provider,
                        model,
                        messages,
                        response_model,
                        options=options,
                        max_retries=0,
                    )
                except LLMExtractionError:
                    raise
                except Exception as exc:  # noqa: BLE001 - classified below
                    if not is_model_unavailable(exc):
                        if len(chain) == 1:
                            raise
                        raise ModelUnavailableError(
                            template_name, [(model, describe_api_error(exc))]
                        ) from exc
                    if len(chain) == 1:
                        raise
                    error = describe_api_error(exc)
                    self._unavailable_models[model] = (
                        error,
                        (
                            None
                            if is_persistent_unavailability(exc)
                            else time.monotonic() + TRANSIENT_COOLDOWN_SECONDS
                        ),
                    )
                    failures.append((model, error))
                    remaining = ordered[position + 1 :]
                    self.tracker.warn(
                        f"{model} unavailable for {template_name} ({error}); "
                        + (
                            f"falling back to {remaining[0]}"
                            if remaining
                            else "no fallback model left this round"
                        )
                    )
                    continue
                if model != self.model:
                    self.tracker.detail(f"{template_name} answered by {model}")
                return result  # type: ignore[return-value]
            transient = [
                model
                for model in chain
                if model in self._unavailable_models
                and self._unavailable_models[model][1] is not None
            ]
            if round_number == rounds or not transient:
                break
            delay = CHAIN_RETRY_DELAYS_SECONDS[round_number - 1]
            self.tracker.warn(
                f"Every model is busy for {template_name}; waiting {delay:.0f}s "
                f"and retrying the chain (round {round_number + 1}/{rounds})"
            )
            time.sleep(delay)
            for model in transient:
                self._unavailable_models.pop(model, None)
        raise ModelUnavailableError(template_name, failures)

    def _retry(
        self, template_name: str, attempt: int, error: object, max_attempts: int = 2
    ) -> None:
        self.tracker.retry(
            _TEMPLATE_STAGES[template_name],
            attempt=attempt,
            max_attempts=max_attempts,
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

    def _map_requirements(
        self,
        jd_json: str,
        requirements: list[dict],
        facts: dict[str, dict],
        global_evidence_json: str,
    ) -> tuple[list[dict], RequirementProxyPlan]:
        """Find the closest real evidence for each JD requirement the master lacks.

        Direct matches are decided in code; the model only classifies gaps.
        No gaps means no call. A planner that cannot produce a valid map
        degrades to "no proxies" with a warning instead of failing the run.
        """

        empty = RequirementProxyPlan(proxies=[])
        gaps = [
            item
            for item in missing_requirements(requirements)
            if item.get("category") not in {"soft_skill", "responsibility"}
        ]
        if not gaps:
            self.tracker.detail("Every JD requirement is stated in the master")
            return requirements, empty
        attempts = 0
        repaired: list[str] = []

        def validate(value: RequirementProxyPlan) -> None:
            # Strict first, so the retry gets precise feedback; on the retry,
            # drop only the unsupported proxies or terms and keep the rest.
            nonlocal attempts
            attempts += 1
            repaired[:] = validate_requirement_proxy_plan(
                value, requirements, facts, repair=attempts > 1
            )

        try:
            plan = self._simple_stage(
                "plan_requirement_coverage",
                RequirementProxyPlan,
                validator=validate,
                jd_profile_json=jd_json,
                missing_requirements_json=json.dumps(
                    [
                        {
                            "id": item["id"],
                            "term": item["term"],
                            "requirement_type": item["requirement_type"],
                            "weight": item["weight"],
                            "category": item.get("category"),
                        }
                        for item in gaps
                    ],
                    indent=2,
                ),
                stated_requirements_json=json.dumps(
                    [
                        item["term"]
                        for item in requirements
                        if item["status"] == "direct"
                    ]
                ),
                global_evidence_json=global_evidence_json,
            )
        except ModelUnavailableError:
            raise
        except StageFailure as exc:
            self.tracker.warn(
                f"Requirement gap mapping failed; continuing without proxies: {exc}"
            )
            return requirements, empty
        for note in repaired:
            self.tracker.warn(f"Dropped unsupported proxy evidence: {note}")
        return attach_proxies(requirements, plan.proxies), plan

    def regenerate_review_bullet(self, flag: Any, bundle: Any) -> str | None:
        """Rewrite one flagged bullet from its own facts; None keeps the safe text."""

        facts_text = "\n".join(flag.source_facts)
        tech = [
            (str(term), list(variants)) for term, variants in bundle.tech_requirements
        ]

        def validate(result: BulletConcision) -> None:
            result.text = " ".join(result.text.split())
            problems = bullet_text_problems(
                result.text,
                facts_text,
                bundle.forbidden_terms,
                tech,
                allowed_numbers_text=flag.safe_text,
            )
            if problems:
                raise ContractError("regenerated bullet " + "; ".join(problems))

        try:
            result = self._simple_stage(
                "regenerate_bullet",
                BulletConcision,
                selected_ids=[flag.flag_id],
                validator=validate,
                jd_profile_json=bundle.jd_profile_json,
                label=flag.label,
                source_facts_json=json.dumps(flag.source_facts, indent=2),
                issues_json=json.dumps(flag.issues, indent=2),
                original_text=flag.original_text or "(the model wrote no bullet)",
                forbidden_terms_json=json.dumps(bundle.forbidden_terms),
            )
        except StageFailure as exc:
            self.tracker.warn(
                f"Could not regenerate the bullet for {flag.label}; keeping the "
                f"safe version ({exc})"
            )
            return None
        return result.text

    def _parse_jd(self, jd_text: str) -> JDProfile:
        return self._simple_stage("jd_parse", JDProfile, jd_text=jd_text)

    def _call_grounded[_Result: BaseModel](
        self,
        template_name: str,
        response_model: type[_Result],
        **context: object,
    ) -> _Result | None:
        """Best-effort grounded call: never fails the run, degrades to no context."""
        try:
            return call_llm_with_retry(
                self.provider,
                self.grounding_model or self.model,
                self._messages(template_name, **context),
                response_model,
                options={**self.options, "temperature": 0.0, "top_p": 1.0},
                max_retries=1,
                grounding=True,
            )
        except Exception as exc:  # noqa: BLE001 - best-effort enrichment, never fatal
            if is_persistent_unavailability(exc):
                self._grounding_exhausted = True
            self.tracker.warn(
                f"{template_name} failed, continuing without company research: "
                f"{describe_api_error(exc)}"
            )
            return None

    def _research_company_stack(self, jd: JDProfile) -> CompanyStackResearch | None:
        return self._call_grounded(
            "research_company_stack",
            CompanyStackResearch,
            company_name=jd.company_name,
            jd_profile_json=jd.model_dump_json(indent=2),
        )

    def _research_company_signals(self, jd: JDProfile) -> CompanyHiringSignals | None:
        return self._call_grounded(
            "research_company_signals",
            CompanyHiringSignals,
            company_name=jd.company_name,
            jd_profile_json=jd.model_dump_json(indent=2),
        )

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
        company_stack_json: str | None = None,
        company_signals_json: str | None = None,
        requirements: Sequence[dict] | None = None,
        fact_index: dict[str, dict] | None = None,
        jd: JDProfile | None = None,
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
                    company_stack_json=company_stack_json,
                    company_signals_json=company_signals_json,
                    requirement_map_json=(
                        json.dumps(prompt_requirement_map(requirements), indent=2)
                        if requirements is not None
                        else None
                    ),
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
                    return choose_selected(
                        accepted,
                        evidence,
                        cap,
                        requirements=requirements,
                        fact_index=fact_index,
                        jd=jd,
                    )
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
        company_stack_json: str | None = None,
        company_signals_json: str | None = None,
        requirement_map_json: str | None = None,
        forbidden_terms: Sequence[str] = (),
        tech_requirements: Sequence[tuple[str, Sequence[str]]] = (),
    ) -> list[WorkRewriteItem]:
        if not sources:
            return []
        expected = {item["source_id"]: item for item in sources}
        accepted: dict[str, WorkRewriteItem] = {}
        last_items: dict[str, WorkRewriteItem] = {}
        pending = list(expected)
        last: object = None
        errors: list[str] = []
        for attempt in range(1, REWRITE_ATTEMPTS + 1):
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
                        sorted(
                            {item.keyword for item in transferable_skill_plan.skills}
                            | set(forbidden_terms)
                        )
                    ),
                    company_stack_json=company_stack_json,
                    company_signals_json=company_signals_json,
                    requirement_map_json=requirement_map_json,
                    feedback=(
                        None
                        if attempt == 1
                        else "Rewrite only these missing or invalid source IDs: "
                        + ", ".join(pending)
                        + (f". Errors: {'; '.join(errors[-3:])}" if errors else "")
                    ),
                )
                last = result
                for item in result.work:
                    if item.source_id in expected:
                        last_items[item.source_id] = item
            except LLMExtractionError as exc:
                last = exc.raw_response
                errors.append(str(exc))
                if attempt == REWRITE_ATTEMPTS:
                    break
                self._retry("tailor_work", attempt + 1, exc, REWRITE_ATTEMPTS)
                pending = list(expected)
                accepted.clear()
                continue
            partial, unresolved, partial_errors = self._partial_entries(
                result.work,
                {source_id: expected[source_id] for source_id in pending},
                lambda item, source: self._repaired(
                    repair_allocation_provenance(item, evidence_plan)
                )
                or validate_work_item(
                    item,
                    source,
                    evidence_plan,
                    fact_index,
                    transferable_skill_plan,
                    forbidden_terms,
                    # Strict once (with feedback), advisory afterwards: the
                    # reviewer sees any remaining hits and fixes them.
                    tech_requirements if attempt == 1 else (),
                ),
            )
            for error in partial_errors:
                if error.startswith("unknown source IDs"):
                    self.tracker.detail(
                        f"Ignored entries for unselected roles: {error}"
                    )
            accepted.update(partial)
            errors.extend(partial_errors)
            pending = [source_id for source_id in pending if source_id in unresolved]
            if not pending:
                return [accepted[item["source_id"]] for item in sources]
            if attempt < REWRITE_ATTEMPTS:
                self._retry(
                    "tailor_work",
                    attempt + 1,
                    "; ".join(partial_errors) or "missing entries",
                    REWRITE_ATTEMPTS,
                )
        return self._salvage(
            "tailor_work",
            sources,
            accepted,
            pending,
            errors,
            last,
            lambda source: salvage_work_item(
                last_items.get(source["source_id"]),
                source,
                evidence_plan,
                fact_index,
                forbidden_terms,
            ),
        )

    def _rewrite_project_batch(
        self,
        jd_json: str,
        sources: Sequence[dict],
        batch_number: int,
        batch_total: int,
        transferable_skill_plan: TransferableSkillPlan,
        fact_index: dict[str, dict],
        company_stack_json: str | None = None,
        company_signals_json: str | None = None,
        requirement_map_json: str | None = None,
        forbidden_terms: Sequence[str] = (),
        tech_requirements: Sequence[tuple[str, Sequence[str]]] = (),
    ) -> list[ProjectRewriteItem]:
        self.tracker.detail(
            f"Project rewrite batch {batch_number}/{batch_total}", verbose_only=False
        )
        expected = {item["source_id"]: item for item in sources}
        accepted: dict[str, ProjectRewriteItem] = {}
        last_items: dict[str, ProjectRewriteItem] = {}
        pending = list(expected)
        last: object = None
        errors: list[str] = []
        for attempt in range(1, REWRITE_ATTEMPTS + 1):
            subset = [expected[source_id] for source_id in pending]
            try:
                result = self._call_once(
                    "tailor_projects",
                    ProjectRewriteResponse,
                    jd_profile_json=jd_json,
                    selected_projects_json=json.dumps(subset, indent=2),
                    transferable_skill_keywords_json=json.dumps(
                        sorted(
                            {item.keyword for item in transferable_skill_plan.skills}
                            | set(forbidden_terms)
                        )
                    ),
                    company_stack_json=company_stack_json,
                    company_signals_json=company_signals_json,
                    requirement_map_json=requirement_map_json,
                    feedback=(
                        None
                        if attempt == 1
                        else "Rewrite only these missing or invalid source IDs: "
                        + ", ".join(pending)
                        + (f". Errors: {'; '.join(errors[-3:])}" if errors else "")
                    ),
                )
                last = result
                for item in result.projects:
                    if item.source_id in expected:
                        last_items[item.source_id] = item
            except LLMExtractionError as exc:
                last = exc.raw_response
                errors.append(str(exc))
                if attempt == REWRITE_ATTEMPTS:
                    break
                self._retry("tailor_projects", attempt + 1, exc, REWRITE_ATTEMPTS)
                pending = list(expected)
                accepted.clear()
                continue
            partial, unresolved, partial_errors = self._partial_entries(
                result.projects,
                {source_id: expected[source_id] for source_id in pending},
                lambda item, source: validate_project_item(
                    item,
                    source,
                    fact_index,
                    transferable_skill_plan,
                    forbidden_terms,
                    # Strict once (with feedback), advisory afterwards: the
                    # reviewer sees any remaining hits and fixes them.
                    tech_requirements if attempt == 1 else (),
                ),
            )
            for error in partial_errors:
                if error.startswith("unknown source IDs"):
                    self.tracker.detail(
                        f"Ignored entries for unselected projects: {error}"
                    )
            accepted.update(partial)
            errors.extend(partial_errors)
            pending = [source_id for source_id in pending if source_id in unresolved]
            if not pending:
                return [accepted[item["source_id"]] for item in sources]
            if attempt < REWRITE_ATTEMPTS:
                self._retry(
                    "tailor_projects",
                    attempt + 1,
                    "; ".join(partial_errors) or "missing entries",
                    REWRITE_ATTEMPTS,
                )
        return self._salvage(
            f"tailor_projects.batch_{batch_number}",
            sources,
            accepted,
            pending,
            errors,
            last,
            lambda source: salvage_project_item(
                last_items.get(source["source_id"]),
                source,
                fact_index,
                forbidden_terms,
            ),
        )

    def _rewrite_projects(
        self,
        jd_json: str,
        sources: Sequence[dict],
        transferable_skill_plan: TransferableSkillPlan,
        fact_index: dict[str, dict],
        company_stack_json: str | None = None,
        company_signals_json: str | None = None,
        requirement_map_json: str | None = None,
        forbidden_terms: Sequence[str] = (),
        tech_requirements: Sequence[tuple[str, Sequence[str]]] = (),
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
                    company_stack_json,
                    company_signals_json,
                    requirement_map_json,
                    forbidden_terms,
                    tech_requirements,
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
        resume: bool = False,
    ) -> int:
        out_dir = Path(out_dir)
        self.tracker.job = job
        self._unavailable_models = {}
        self._bullet_flags = []
        self._reused = []
        self._grounding_exhausted = False
        self._checkpoints = CheckpointStore(
            out_dir,
            run_fingerprint(
                master.model_dump_json(),
                jd_text,
                bridge_skills=self.bridge_skills,
                research_company=self.research_company,
                allow_fit_recovery=self.allow_fit_recovery,
            ),
        )
        self._resuming = resume
        try:
            with self.tracker.stage(Stage.PREFLIGHT):
                self.tracker.detail(f"Model: {self.model}")
                clear_artifacts(out_dir)
                if not resume:
                    self._checkpoints.clear()
                if not no_pdf:
                    ensure_tectonic()

            with self.tracker.stage(Stage.PARSE_JD):
                jd = self._checkpointed(
                    "jd_parse",
                    lambda: self._parse_jd(jd_text),
                    lambda value: value.model_dump(mode="json"),
                    JDProfile.model_validate,
                )
                jd, dropped_keywords = sanitize_jd_profile(jd, jd_text)
                if dropped_keywords:
                    self.tracker.warn(
                        "Dropped JD keywords the posting never states: "
                        + ", ".join(dropped_keywords)
                    )
                jd_json = jd.model_dump_json(indent=2)

            company_stack_json: str | None = None
            company_signals_json: str | None = None
            if self.research_company:
                provider_ok = self.grounding_model is not None
                thin = jd_signal_is_thin(jd)
                has_company = bool(jd.company_name)

                def _skip_reason() -> str | None:
                    if not provider_ok:
                        return (
                            "active provider does not support Gemini web-search "
                            "grounding"
                        )
                    if not has_company:
                        return (
                            "could not identify a company name in the job description"
                        )
                    if not thin:
                        return (
                            f"JD signal is sufficient ({jd_signal_strength(jd)} "
                            f"> {RESEARCH_THIN_JD_SIGNAL_THRESHOLD})"
                        )
                    return None

                with self.tracker.stage(Stage.RESEARCH_COMPANY_STACK):
                    reason = _skip_reason()
                    if reason:
                        self.tracker.detail(f"Skipping company research: {reason}")
                    else:
                        stack = self._checkpointed(
                            "research_company_stack",
                            lambda: self._research_company_stack(jd),
                            _dump_optional,
                            _restore_optional(CompanyStackResearch),
                        )
                        company_stack_json = (
                            stack.model_dump_json(indent=2) if stack else None
                        )

                with self.tracker.stage(Stage.RESEARCH_COMPANY_SIGNALS):
                    reason = _skip_reason()
                    if not reason and self._grounding_exhausted:
                        reason = "web-search quota is exhausted for this run"
                    if reason:
                        self.tracker.detail(f"Skipping company research: {reason}")
                    else:
                        signals = self._checkpointed(
                            "research_company_signals",
                            lambda: self._research_company_signals(jd),
                            _dump_optional,
                            _restore_optional(CompanyHiringSignals),
                        )
                        company_signals_json = (
                            signals.model_dump_json(indent=2) if signals else None
                        )

            evidence = global_evidence_payload(master)
            facts = master_fact_index(master, evidence=evidence)
            global_evidence_json = json.dumps(evidence, indent=2)
            with self.tracker.stage(Stage.MAP_REQUIREMENTS):
                requirements, proxy_plan = self._checkpointed(
                    "requirement_map",
                    lambda: self._map_requirements(
                        jd_json, requirement_map(jd, facts), facts, global_evidence_json
                    ),
                    lambda value: {
                        "requirements": value[0],
                        "proxy_plan": value[1].model_dump(mode="json"),
                    },
                    lambda payload: (
                        payload["requirements"],
                        RequirementProxyPlan.model_validate(payload["proxy_plan"]),
                    ),
                )
                transferable_skill_plan = TransferableSkillPlan(skills=[])
                if self.bridge_skills and proxy_plan.proxies:
                    candidate_plan = transferable_plan_from_proxies(proxy_plan)
                    try:
                        validate_transferable_skill_plan(
                            candidate_plan, jd, master, facts
                        )
                        transferable_skill_plan = candidate_plan
                    except ContractError as exc:
                        self.tracker.warn(f"Transferable skills group skipped: {exc}")
                forbidden_terms = forbidden_claim_terms(requirements)
                tech_requirements = supported_tech_requirements(requirements)
                priority = priority_proxies(requirements, facts)
                requirement_map_json = json.dumps(
                    prompt_requirement_map(requirements), indent=2
                )
                counts = {
                    status: sum(1 for item in requirements if item["status"] == status)
                    for status in ("direct", "proxy", "missing")
                }
                self.tracker.detail(
                    f"Requirements: {counts['direct']} stated, {counts['proxy']} "
                    f"bridged by adjacent evidence, {counts['missing']} unsupported"
                )
                for item in requirements:
                    if item["status"] == "proxy":
                        self.tracker.detail(
                            f"Gap {item['term']!r} -> closest evidence "
                            f"{', '.join(item['proxy_terms'])} "
                            f"({', '.join(item['proxy_fact_ids'])})"
                        )

            all_work = evidence["work"]
            all_projects = evidence["projects"]
            with self.tracker.stage(Stage.SELECT_WORK):
                selected_work = tuple(
                    self._checkpointed(
                        "select_work",
                        lambda: self._select(
                            "select_work",
                            "work",
                            jd_json,
                            all_work,
                            MAX_SELECTED_WORK,
                            company_stack_json,
                            company_signals_json,
                            requirements=requirements,
                            fact_index=facts,
                            jd=jd,
                        ),
                        list,
                        list,
                    )
                )
            with self.tracker.stage(Stage.SELECT_PROJECTS):
                selected_projects = tuple(
                    self._checkpointed(
                        "select_projects",
                        lambda: self._select(
                            "select_projects",
                            "projects",
                            jd_json,
                            all_projects,
                            MAX_SELECTED_PROJECTS,
                            company_stack_json,
                            company_signals_json,
                            requirements=requirements,
                            fact_index=facts,
                            jd=jd,
                        ),
                        list,
                        list,
                    )
                )
            selected = SelectedEvidence(work=selected_work, projects=selected_projects)

            targets = work_bullet_targets(selected.work)
            proxy_warnings: list[str] = []
            dropped_target_terms: list[str] = []
            plan_attempts = 0

            def validate_plan(value: EvidencePlan) -> None:
                # Truth and shape errors always retry. Unplaced proxy evidence
                # retries once with a precise instruction, then degrades to a
                # warning so a stubborn model cannot fail the whole run.
                nonlocal plan_attempts
                plan_attempts += 1
                align_inference_provenance(value)
                validate_evidence_plan(value, selected.work, facts)
                dropped_target_terms[:] = sanitize_target_terms(
                    value, requirements, forbidden_terms, facts
                )
                gaps = proxy_coverage_gaps(value, priority, selected.projects, facts)
                if gaps and plan_attempts == 1:
                    raise ContractError(
                        "evidence plan omits closest evidence for missing "
                        "requirements: " + " | ".join(gaps)
                    )
                proxy_warnings[:] = gaps

            def plan_evidence() -> EvidencePlan:
                return self._simple_stage(
                    "plan_evidence",
                    EvidencePlan,
                    selected_ids=list(targets),
                    validator=validate_plan,
                    jd_profile_json=jd_json,
                    global_evidence_json=global_evidence_json,
                    requirement_map_json=requirement_map_json,
                    priority_proxies_json=json.dumps(
                        [
                            {
                                "requirement_id": item["id"],
                                "requirement": item["term"],
                                "proxy_terms": item["proxy_terms"],
                                "proxy_fact_ids": item["proxy_fact_ids"],
                            }
                            for item in priority
                        ],
                        indent=2,
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
                                "covered_requirement_ids": item.get(
                                    "selection_covered_requirement_ids", []
                                ),
                            }
                            for item in selected.work
                        ],
                        indent=2,
                    ),
                    selected_projects_json=json.dumps(
                        [
                            {"source_id": item["source_id"], "name": item.get("name")}
                            for item in selected.projects
                        ],
                        indent=2,
                    ),
                    bullet_targets_json=json.dumps(targets, indent=2),
                )

            def restore_plan(payload: dict) -> EvidencePlan:
                proxy_warnings[:] = payload["proxy_warnings"]
                dropped_target_terms[:] = payload["dropped_target_terms"]
                return EvidencePlan.model_validate(payload["plan"])

            with self.tracker.stage(Stage.PLAN_EVIDENCE):
                evidence_plan = self._checkpointed(
                    "plan_evidence",
                    plan_evidence,
                    lambda value: {
                        "plan": value.model_dump(mode="json"),
                        "proxy_warnings": list(proxy_warnings),
                        "dropped_target_terms": list(dropped_target_terms),
                    },
                    restore_plan,
                )
                for message in proxy_warnings:
                    self.tracker.warn(f"Proxy evidence not placed: {message}")
                if dropped_target_terms:
                    self.tracker.detail(
                        "Ignored unsupported target terms: "
                        + ", ".join(dropped_target_terms)
                    )

            with self.tracker.stage(Stage.TAILOR_SKILLS):
                skills: TailoredSkills | None = None
                if master.skills or transferable_skill_plan.skills:
                    skills = self._checkpointed(
                        "tailor_skills",
                        lambda: self._simple_stage(
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
                            experience_technologies_json=json.dumps(
                                technologies_in_experience(master), indent=2
                            ),
                            transferable_skill_plan_json=(
                                transferable_skill_plan.model_dump_json(indent=2)
                            ),
                            requirement_map_json=requirement_map_json,
                        ),
                        lambda value: value.model_dump(mode="json"),
                        TailoredSkills.model_validate,
                    )
            with self.tracker.stage(Stage.REWRITE_WORK):
                work = tuple(
                    self._checkpointed_rewrite(
                        "rewrite_work",
                        WorkRewriteItem,
                        lambda: self._rewrite_work(
                            jd_json,
                            selected.work,
                            evidence_plan,
                            transferable_skill_plan,
                            facts,
                            company_stack_json,
                            company_signals_json,
                            requirement_map_json,
                            forbidden_terms,
                            tech_requirements,
                        ),
                    )
                )
            with self.tracker.stage(Stage.REWRITE_PROJECTS):
                projects = tuple(
                    self._checkpointed_rewrite(
                        "rewrite_projects",
                        ProjectRewriteItem,
                        lambda: self._rewrite_projects(
                            jd_json,
                            selected.projects,
                            transferable_skill_plan,
                            facts,
                            company_stack_json,
                            company_signals_json,
                            requirement_map_json,
                            forbidden_terms,
                            tech_requirements,
                        ),
                    )
                )
            components = PipelineComponents(
                skills=skills,
                work=work,
                projects=projects,
                selected=selected,
                evidence_plan=evidence_plan,
                transferable_skill_plan=transferable_skill_plan,
                forbidden_terms=forbidden_terms,
            )
            with self.tracker.stage(Stage.ASSEMBLE):
                draft = assemble_scored(master, components)
                draft_plain = scored_to_plain(draft)
                draft_dump = draft_plain.model_dump(mode="json")
                draft_coverage = resume_coverage(draft_dump, requirements)
                self.tracker.detail(
                    f"Draft keyword coverage {draft_coverage['computed_coverage_pct']}% "
                    f"(stated requirements: {draft_coverage['supported_coverage_pct']}%)"
                )

            def holistic_review() -> HolisticReview:
                return self._simple_stage(
                    "holistic_review",
                    HolisticReview,
                    jd_profile_json=jd_json,
                    master_json=master.model_dump_json(indent=2),
                    tailored_resume_json=draft_plain.model_dump_json(indent=2),
                    evidence_plan_json=evidence_plan.model_dump_json(indent=2),
                    transferable_skill_plan_json=(
                        transferable_skill_plan.model_dump_json(indent=2)
                    ),
                    requirement_map_json=requirement_map_json,
                    computed_keyword_gaps_json=json.dumps(
                        {
                            "computed_coverage_pct": draft_coverage[
                                "computed_coverage_pct"
                            ],
                            "stated_in_master_but_missing_from_draft": draft_coverage[
                                "missing_supported_terms"
                            ],
                            "gaps_whose_proxy_evidence_is_missing_from_draft": (
                                draft_coverage["proxied_terms_without_proxy_on_page"]
                            ),
                            "never_claim_in_bullets": list(forbidden_terms),
                            "bullets_naming_technology_their_facts_lack": (
                                scan_unsupported_technology(
                                    draft, facts, tech_requirements
                                )
                            ),
                            "placement_findings": placement_findings(
                                draft_dump, requirements, coverage=draft_coverage
                            ),
                        },
                        indent=2,
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

            with self.tracker.stage(Stage.HOLISTIC_REVIEW):
                review = self._checkpointed(
                    "holistic_review",
                    holistic_review,
                    lambda value: value.model_dump(mode="json"),
                    HolisticReview.model_validate,
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
                for metric_message in scan_metric_quality(final_scored):
                    self.tracker.warn(f"Metric quality: {metric_message}")
                unsupported_technology = scan_unsupported_technology(
                    final_scored, facts, tech_requirements
                )
                for message in unsupported_technology:
                    self.tracker.warn(f"Unsupported technology: {message}")
                report_payload = review.model_dump(mode="json")
                report_payload["evidence_plan"] = evidence_plan.model_dump(mode="json")
                report_payload["source_facts"] = facts
                report_payload["rejected_section_edits"] = rejected_edits
                report_payload["cross_entry_attributions"] = cross_entry_attributions(
                    evidence_plan, facts
                )
                report_payload["inferred_metrics"] = inferred_metrics(evidence_plan)
                report_payload["transferable_skill_injections"] = (
                    transferable_skill_injections(transferable_skill_plan)
                )
                report_payload["jd_profile"] = jd.model_dump(mode="json")
                report_payload["requirement_map"] = requirements
                report_payload["requirement_proxies"] = proxy_plan.model_dump(
                    mode="json"
                )["proxies"]
                report_payload["unplaced_proxy_evidence"] = proxy_warnings
                report_payload["unsupported_technology_mentions"] = (
                    unsupported_technology
                )
                final_dump = scored_to_plain(final_scored).model_dump(mode="json")
                keyword_coverage = resume_coverage(final_dump, requirements)
                report_payload["keyword_coverage"] = keyword_coverage
                report_payload["placement_findings"] = placement_findings(
                    final_dump, requirements, coverage=keyword_coverage
                )
                self.tracker.detail(
                    "Final keyword coverage "
                    f"{keyword_coverage['computed_coverage_pct']}% "
                    f"(stated requirements: {keyword_coverage['supported_coverage_pct']}%)"
                )
                for finding in report_payload["placement_findings"]:
                    self.tracker.warn(f"Keyword placement: {finding}")
                unresolved_violations, resolved_violations = (
                    partition_review_truth_violations(review, final_scored)
                )
                unresolved_violations, waived_violations = waive_cross_entry_objections(
                    unresolved_violations, final_scored, evidence_plan, facts
                )
                for violation in waived_violations:
                    self.tracker.warn(
                        "Reviewer objected to planned cross-entry attribution "
                        f"(policy allows it): {violation.claim[:90]!r}"
                    )
                report_payload["waived_cross_entry_violations"] = [
                    item.model_dump(mode="json") for item in waived_violations
                ]
                report_payload["truth_violations"] = [
                    item.model_dump(mode="json") for item in unresolved_violations
                ]
                report_payload["resolved_truth_violations"] = [
                    item.model_dump(mode="json") for item in resolved_violations
                ]

            if unresolved_violations:
                report_payload["pipeline_status"] = "blocked_truth_violations"
                write_json(out_dir / "match_report.json", report_payload)
                # A retry should get a fresh review, not the one that blocked.
                self._checkpoints.discard("holistic_review")
                return 1
            for message in rejected_edits:
                self.tracker.warn(f"Reviewer edit rejected: {message}")

            flagged = live_flags(final_scored, self._bullet_flags)
            report_payload["auto_safe_fixes"] = flagged
            if flagged and self.allow_fit_recovery:
                # Web runs pause here so the user decides each flagged bullet;
                # CLI runs keep the safe versions and list them in the report.
                report_payload["pipeline_status"] = "review_required"
                persist_bullet_review(
                    out_dir,
                    final_scored,
                    flagged,
                    pending_report=report_payload,
                    no_pdf=no_pdf,
                    jd_profile_json=jd_json,
                    forbidden_terms=forbidden_terms,
                    tech_requirements=tech_requirements,
                    fact_index=facts,
                )
                self.tracker.detail(
                    f"{len(flagged)} bullet(s) need your review before rendering"
                )
                return 2

            with self.tracker.stage(Stage.RENDER):
                if no_pdf:
                    final_plain = scored_to_plain(final_scored)
                    render(final_plain, out_dir, False)
                else:
                    concision = _ConcisionController(self, facts, evidence_plan)
                    try:
                        fit_kwargs: dict[str, object] = {
                            "progress_callback": lambda message: self.tracker.detail(
                                message
                            )
                        }
                        if (
                            "exhaustion_handler"
                            in inspect.signature(fit_to_one_page).parameters
                        ):
                            fit_kwargs["exhaustion_handler"] = concision
                        final_plain = fit_to_one_page(
                            final_scored, out_dir, **fit_kwargs
                        )
                        concision.audit()
                    except FitRecoveryRequired as recovery:
                        report_payload["automatic_concisions"] = recovery.concision_log
                        report_payload["pipeline_status"] = "action_required"
                        persist_fit_recovery(
                            out_dir,
                            recovery.scored_resume,
                            page_count=recovery.page_count,
                            pending_report=report_payload,
                            trim_log=recovery.trim_log,
                            concision_log=recovery.concision_log,
                        )
                        for name in ("resume.tex", "resume.pdf"):
                            (out_dir / name).unlink(missing_ok=True)
                        return 2
                    except StageFailure:
                        for name in ("resume.tex", "resume.pdf"):
                            (out_dir / name).unlink(missing_ok=True)
                        raise
                    report_payload["automatic_concisions"] = concision.log
            with self.tracker.stage(Stage.WRITE_ARTIFACTS):
                write_json(out_dir / "tailored.json", final_plain)
                report_payload["pipeline_status"] = (
                    "completed_with_rejected_edits" if rejected_edits else "completed"
                )
                write_json(out_dir / "match_report.json", report_payload)
                write_json(out_dir / ".done", {"pdf": not no_pdf})
                self._checkpoints.clear()
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
