#!/usr/bin/env python
"""ATS Resume Tailor — orchestration pipeline + CLI (Task E).

Pipeline (spec Sec. Architecture)::

    parse JD -> tailor 4 sections (summary/skills/work/projects; education is a
    verbatim passthrough, no LLM) -> assemble -> match-score -> iterate ONLY the
    weak/violating sections with gap/violation feedback (max 2 passes total,
    coverage threshold default 80) -> fit to one page (unless --no-pdf) -> render.

Two entry points:

* Single-JD    ``python tailor.py master.json jd.txt -o out/ [flags]``
* Batch folder ``python tailor.py batch [--jd-dir jds/] [--out-dir output/] [flags]``

A free-tier *pacer* (``--call-interval``, default 4.5 s) throttles every LLM call
so a full batch stays under the Gemini free-tier 15 RPM limit by construction.

Truth floor: if the scorer still reports fabricated content after the maximum
passes, the run exits non-zero and renders nothing — it never emits a resume
with invented facts.

The renderer (``render.py``) is imported lazily inside thin wrappers so unit
tests can mock rendering (and avoid requiring a LaTeX toolchain).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from models import (
    Basics,
    JDProfile,
    JSONResume,
    MatchReport,
    TailoredProjects,
    TailoredSkills,
    TailoredSummary,
    TailoredWork,
    strip_relevance_project,
    strip_relevance_skill,
    strip_relevance_work,
)
from llm_utils import LLMExtractionError, call_llm_with_retry, initialize_llm_provider
from prompt import DEFAULT_MODEL, MODEL_PARAMETERS
from prompts.template_manager import TemplateManager
from render import RenderError  # exception type only; the render/fit calls stay lazy

# ResourceExhausted escapes the provider's own backoff only when quota is truly
# gone; it is NOT caught by call_llm_with_retry (which only handles bad output),
# so it propagates up to the batch loop. Guarded so the module imports even where
# google-api-core is unavailable.
try:  # pragma: no cover - import shape only
    from google.api_core.exceptions import ResourceExhausted
except Exception:  # pragma: no cover

    class ResourceExhausted(Exception):  # type: ignore[no-redef]
        """Fallback stand-in when google-api-core is not importable."""


logger = logging.getLogger("tailor")

_REPO_ROOT = Path(__file__).resolve().parent
_TEMPLATE_DIR = str(_REPO_ROOT / "prompts" / "templates")

DEFAULT_HIRING_AGENT_PATH = "~/Desktop/hackerank_ats/hiring-agent"
DEFAULT_CALL_INTERVAL = 4.5
DEFAULT_THRESHOLD = 80.0
DEFAULT_MAX_PASSES = 2
QUOTA_EXIT_CODE = 75  # EX_TEMPFAIL — signals "transient; wait and re-run"

# The sections we can actually re-tailor. Education is a passthrough (never
# fabricated by us), basics are contact facts — neither is re-runnable.
TAILORABLE_SECTIONS = ("summary", "skills", "work", "projects")

# Substring/synonym needles for canonicalizing a loosely-named section from the
# (deliberately weak) scorer — e.g. "Work Experience", "profile", "projects[0]".
# Order matters: first match wins. Keeps the spec's "truth violations always
# trigger a re-run of the offending section" guarantee from silently dead-ending
# when the scorer returns a non-canonical label.
_SECTION_SYNONYMS = (
    ("summary", ("summary", "profile", "objective")),
    ("skills", ("skill", "technolog", "competenc")),
    ("work", ("work", "experience", "employment", "professional")),
    ("projects", ("project", "portfolio")),
)


def _canonical_section(name: str) -> Optional[str]:
    """Map a possibly-loose scorer section label to a canonical tailorable name.

    Returns one of ``TAILORABLE_SECTIONS`` or ``None`` when nothing matches (so
    callers can fall back to re-running all sections rather than aborting).
    """
    canon = (name or "").strip().lower()
    if not canon:
        return None
    if canon in TAILORABLE_SECTIONS:
        return canon
    for section, needles in _SECTION_SYNONYMS:
        if any(needle in canon for needle in needles):
            return section
    return None


def _ensure_tectonic() -> None:
    """Preflight: raise ``render.RenderError`` if tectonic is not on PATH.

    Kept as a thin, monkeypatchable seam so PDF-mode runs fail fast before any
    paced LLM spend on a machine that cannot compile the PDF.
    """
    from render import ensure_tectonic

    ensure_tectonic()


class _PacedProvider:
    """Wrap an LLM provider so the free-tier pacer gates EVERY physical request.

    ``call_llm_with_retry`` may fire up to two correction retries per invocation;
    pacing at the provider seam (rather than once per invocation) keeps all of
    those requests under the free-tier RPM ceiling, honoring the documented
    "≤ 14 requests/min by construction" guarantee even on the retry path.
    """

    def __init__(self, provider: Any, pacer: "RatePacer"):
        self._provider = provider
        self._pacer = pacer

    def chat(self, *args: Any, **kwargs: Any) -> Any:
        self._pacer.wait()
        return self._provider.chat(*args, **kwargs)


# ---------------------------------------------------------------------------
# Free-tier pacer
# ---------------------------------------------------------------------------


class RatePacer:
    """Minimum-interval throttle applied immediately before every LLM call.

    Guarantees consecutive calls are at least ``min_interval`` seconds apart.
    ``min_interval <= 0`` disables throttling entirely (paid tier). The first
    call never waits; each subsequent call sleeps only for the shortfall.
    """

    def __init__(self, min_interval: float):
        self.min_interval = float(min_interval)
        self._next_allowed: Optional[float] = None

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        now = time.monotonic()
        if self._next_allowed is not None and now < self._next_allowed:
            time.sleep(self._next_allowed - now)
        self._next_allowed = time.monotonic() + self.min_interval


# ---------------------------------------------------------------------------
# Lazy renderer wrappers (mocked wholesale in unit tests)
# ---------------------------------------------------------------------------


def _render_resume(resume: JSONResume, out_dir: Path, compile_pdf: bool) -> Any:
    """Write ``out_dir/resume.tex`` (and ``resume.pdf`` when ``compile_pdf``)."""
    from render import render

    return render(resume, out_dir, compile_pdf)


def _fit_to_one_page(scored_resume: Any, out_dir: Path) -> JSONResume:
    """Run the deterministic one-page trim loop; returns the trimmed plain resume."""
    from render import fit_to_one_page

    return fit_to_one_page(scored_resume, out_dir)


def _new_scored_resume(**fields: Any) -> Any:
    """Construct the renderer's ``ScoredResume`` container (relevance preserved)."""
    from render import ScoredResume

    return ScoredResume(**fields)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class TailorPipeline:
    """Orchestrates one master+JD -> tailored, ATS-optimized resume run."""

    def __init__(
        self,
        model: Optional[str] = None,
        threshold: float = DEFAULT_THRESHOLD,
        max_passes: int = DEFAULT_MAX_PASSES,
        call_interval: float = DEFAULT_CALL_INTERVAL,
        provider: Any = None,
        template_manager: Optional[TemplateManager] = None,
    ):
        self.model = model or DEFAULT_MODEL
        self.threshold = float(threshold)
        self.max_passes = max(1, int(max_passes))
        self.pacer = RatePacer(call_interval)
        self.tm = template_manager or TemplateManager(template_dir=_TEMPLATE_DIR)
        self.options: Dict[str, Any] = {
            "stream": False,
            **MODEL_PARAMETERS.get(self.model, {"temperature": 0.1, "top_p": 0.9}),
        }
        raw_provider = (
            provider if provider is not None else initialize_llm_provider(self.model)
        )
        # Pace at the provider seam so retries inside call_llm_with_retry are
        # throttled too (see _PacedProvider).
        self.provider = _PacedProvider(raw_provider, self.pacer)

    # -- LLM plumbing --------------------------------------------------------

    def _call(self, template_name: str, response_model: Any, stage: str, **kwargs: Any):
        """Render the stage prompt, pace, and call the retrying LLM helper."""
        system = self.tm.render_template("system_message", stage=stage)
        user = self.tm.render_template(template_name, **kwargs)
        if user is None:
            raise RuntimeError(f"template {template_name!r} failed to render")
        messages = [
            {"role": "system", "content": system or ""},
            {"role": "user", "content": user},
        ]
        # NB: pacing happens inside self.provider (a _PacedProvider), so every
        # physical request — including call_llm_with_retry's correction retries —
        # is throttled, not just the first request of each invocation.
        return call_llm_with_retry(
            self.provider,
            self.model,
            messages=messages,
            response_model=response_model,
            options=self.options,
        )

    # -- Stages --------------------------------------------------------------

    def _parse_jd(self, jd_text: str) -> JDProfile:
        return self._call("jd_parse", JDProfile, "JD parse", jd_text=jd_text)

    def _tailor_summary(
        self, jd_json: str, master_json: str, feedback: Optional[str] = None
    ) -> TailoredSummary:
        return self._call(
            "tailor_summary",
            TailoredSummary,
            "summary tailor",
            jd_profile_json=jd_json,
            master_json=master_json,
            feedback=feedback,
        )

    def _tailor_skills(
        self, jd_json: str, master_skills_json: str, feedback: Optional[str] = None
    ) -> TailoredSkills:
        return self._call(
            "tailor_skills",
            TailoredSkills,
            "skills tailor",
            jd_profile_json=jd_json,
            master_skills_json=master_skills_json,
            feedback=feedback,
        )

    def _tailor_work(
        self, jd_json: str, master_work_json: str, feedback: Optional[str] = None
    ) -> TailoredWork:
        return self._call(
            "tailor_work",
            TailoredWork,
            "work tailor",
            jd_profile_json=jd_json,
            master_work_json=master_work_json,
            feedback=feedback,
        )

    def _tailor_projects(
        self, jd_json: str, master_projects_json: str, feedback: Optional[str] = None
    ) -> TailoredProjects:
        return self._call(
            "tailor_projects",
            TailoredProjects,
            "projects tailor",
            jd_profile_json=jd_json,
            master_projects_json=master_projects_json,
            feedback=feedback,
        )

    def _score(self, jd_json: str, plain: JSONResume, master_json: str) -> MatchReport:
        tailored_json = json.dumps(plain.model_dump(exclude_none=True), indent=2)
        return self._call(
            "match_score",
            MatchReport,
            "match score",
            jd_profile_json=jd_json,
            tailored_resume_json=tailored_json,
            master_json=master_json,
        )

    # -- Assembly ------------------------------------------------------------

    @staticmethod
    def _tailored_basics(master: JSONResume, summary: str) -> Basics:
        """Master basics with the tailored summary swapped in; contact facts intact."""
        if master.basics is not None:
            return master.basics.model_copy(update={"summary": summary})
        return Basics(name="", summary=summary)

    def _plain_resume(
        self, master: JSONResume, components: Dict[str, Any]
    ) -> JSONResume:
        """Plain JSON Resume (relevance stripped) for scoring / --no-pdf output.

        Education is passed through byte-identically from the master; nothing in
        this method touches the renderer.
        """
        work = [strip_relevance_work(w) for w in components["work"].work] or None
        skills = [strip_relevance_skill(s) for s in components["skills"].skills] or None
        projects = [
            strip_relevance_project(p) for p in components["projects"].projects
        ] or None
        return JSONResume(
            basics=self._tailored_basics(master, components["summary"].summary),
            education=master.education,
            work=work,
            skills=skills,
            projects=projects,
            # Passthrough sections: carried verbatim from the master so no master
            # facts are lost from tailored.json / the --ats-score input. The LaTeX
            # template ignores them (Jake's v1 scope), so the PDF is unaffected.
            volunteer=master.volunteer,
            awards=master.awards,
            certificates=master.certificates,
            publications=master.publications,
            languages=master.languages,
            interests=master.interests,
            references=master.references,
        )

    def _scored_resume(self, master: JSONResume, components: Dict[str, Any]) -> Any:
        """Renderer ``ScoredResume`` (relevance preserved) for the one-page fit loop."""
        return _new_scored_resume(
            basics=self._tailored_basics(master, components["summary"].summary),
            education=master.education,
            work=list(components["work"].work),
            skills=list(components["skills"].skills),
            projects=list(components["projects"].projects),
            # Passthrough sections (never trimmed by the fit loop; see render.py).
            volunteer=master.volunteer,
            awards=master.awards,
            certificates=master.certificates,
            publications=master.publications,
            languages=master.languages,
            interests=master.interests,
            references=master.references,
        )

    # -- Iteration control ---------------------------------------------------

    def _needs_rerun(self, report: MatchReport) -> bool:
        return report.coverage_pct < self.threshold or bool(report.truth_violations)

    def _rerun_sections(self, report: MatchReport) -> Set[str]:
        """Which tailorable sections to re-run: weak (if under threshold) + violating.

        Section labels are canonicalized leniently (``_canonical_section``) so a
        weak scorer naming "Work Experience"/"profile"/"projects[0]" still maps to
        a re-runnable section. When there is a reason to re-run but nothing maps to
        an actionable section, fall back to re-running ALL tailorable sections
        rather than aborting untried — this preserves the spec guarantee that a
        truth violation always triggers a corrective re-run.
        """
        sections: Set[str] = set()
        low_coverage = report.coverage_pct < self.threshold
        if low_coverage:
            for name in report.weak_sections:
                canon = _canonical_section(name)
                if canon:
                    sections.add(canon)
        for violation in report.truth_violations:
            canon = _canonical_section(violation.section)
            if canon:
                sections.add(canon)
        if not sections and (low_coverage or report.truth_violations):
            sections = set(TAILORABLE_SECTIONS)
        return sections

    def _build_feedback(self, section: str, report: MatchReport) -> str:
        """Compose the per-section revision feedback appended to its re-run prompt."""
        lines: List[str] = []
        if report.coverage_pct < self.threshold:
            lines.append(
                f"Overall JD coverage was {report.coverage_pct:.0f}% but the target "
                f"is at least {self.threshold:.0f}%."
            )
            if report.missing_must_haves:
                lines.append(
                    "Surface these missing must-have skills wherever the master "
                    "genuinely supports them (never fabricate): "
                    + ", ".join(report.missing_must_haves)
                    + "."
                )
        for violation in report.truth_violations:
            canon = _canonical_section(violation.section)
            # Attach the claim to its mapped section; if the label was too loose
            # to map (canon is None), surface it in every re-run section so the
            # offending claim is still named somewhere.
            if canon == section or canon is None:
                lines.append(
                    f'REMOVE or CORRECT this fabricated claim: "{violation.claim}" '
                    f"— {violation.reason}"
                )
        if report.notes:
            lines.append(f"Reviewer notes: {report.notes}")
        if not lines:
            lines.append(
                "This section under-sells relevant experience; strengthen its "
                "alignment to the job using only facts present in the master."
            )
        return "\n".join(lines)

    def _tailor_or_empty(
        self,
        section: str,
        master: JSONResume,
        jd_json: str,
        master_json: str,
        master_skills_json: str,
        master_work_json: str,
        master_projects_json: str,
        feedback: Optional[str] = None,
    ) -> Any:
        """Tailor one section, or short-circuit to an empty result with no LLM call.

        When the master's slice for skills/work/projects is empty there is
        nothing to tailor: calling the LLM would only waste a paced call/quota
        slot and hand a weak model an empty list next to a keyword-rich JD —
        a needless fabrication surface. Summary always runs (it draws on the
        whole master).
        """
        if section == "summary":
            return self._tailor_summary(jd_json, master_json, feedback=feedback)
        if section == "skills":
            if not master.skills:
                return TailoredSkills(skills=[])
            return self._tailor_skills(jd_json, master_skills_json, feedback=feedback)
        if section == "work":
            if not master.work:
                return TailoredWork(work=[])
            return self._tailor_work(jd_json, master_work_json, feedback=feedback)
        if section == "projects":
            if not master.projects:
                return TailoredProjects(projects=[])
            return self._tailor_projects(
                jd_json, master_projects_json, feedback=feedback
            )
        raise ValueError(f"unknown section {section!r}")

    # -- Output --------------------------------------------------------------

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def _write_report(self, out_dir: Path, report: MatchReport) -> None:
        self._write_json(out_dir / "match_report.json", report.model_dump())

    # -- Orchestration -------------------------------------------------------

    def run(
        self,
        master: JSONResume,
        jd_text: str,
        out_dir: Path,
        *,
        no_pdf: bool = False,
        ats_score: bool = False,
        hiring_agent_path: str = DEFAULT_HIRING_AGENT_PATH,
    ) -> int:
        """Run the full pipeline for one master+JD. Returns a process exit code."""
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # Preflight: in PDF mode, fail fast if tectonic is missing BEFORE spending
        # any paced LLM calls (their output would otherwise be discarded when the
        # render stage later discovers the missing binary).
        if not no_pdf:
            try:
                _ensure_tectonic()
            except RenderError as exc:
                _print_render_failure(exc, out_dir)
                return 1

        master_json = json.dumps(master.model_dump(exclude_none=True), indent=2)
        master_skills_json = json.dumps(
            [s.model_dump(exclude_none=True) for s in (master.skills or [])], indent=2
        )
        master_work_json = json.dumps(
            [w.model_dump(exclude_none=True) for w in (master.work or [])], indent=2
        )
        master_projects_json = json.dumps(
            [p.model_dump(exclude_none=True) for p in (master.projects or [])], indent=2
        )

        logger.info("[1/5] Parsing job description ...")
        jd_profile = self._parse_jd(jd_text)
        jd_json = json.dumps(jd_profile.model_dump(), indent=2)

        logger.info("[2/5] Tailoring sections (summary, skills, work, projects) ...")
        components: Dict[str, Any] = {
            section: self._tailor_or_empty(
                section,
                master,
                jd_json,
                master_json,
                master_skills_json,
                master_work_json,
                master_projects_json,
            )
            for section in TAILORABLE_SECTIONS
        }

        logger.info("[3/5] Scoring JD match ...")
        plain = self._plain_resume(master, components)
        report = self._score(jd_json, plain, master_json)

        passes_done = 1
        while passes_done < self.max_passes and self._needs_rerun(report):
            sections = self._rerun_sections(report)
            if not sections:
                break
            ordered = [s for s in TAILORABLE_SECTIONS if s in sections]
            logger.info(
                "[4/5] Pass %d: coverage=%.0f%%, violations=%d -> re-tailoring %s",
                passes_done + 1,
                report.coverage_pct,
                len(report.truth_violations),
                ordered,
            )
            for section in ordered:
                components[section] = self._tailor_or_empty(
                    section,
                    master,
                    jd_json,
                    master_json,
                    master_skills_json,
                    master_work_json,
                    master_projects_json,
                    feedback=self._build_feedback(section, report),
                )
            passes_done += 1
            plain = self._plain_resume(master, components)
            report = self._score(jd_json, plain, master_json)

        # Truth-floor gate: fabricated content after the max passes is fatal.
        if report.truth_violations:
            self._write_report(out_dir, report)
            # Clear any prior successful run's artifacts so the directory state
            # matches the "No resume was written" message (no stale resume.pdf/
            # tailored.json sitting next to a violation-bearing report).
            _clear_stale_artifacts(out_dir)
            _print_violation_failure(report, out_dir)
            return 1

        # Persist the machine-readable artifacts BEFORE rendering so a render/fit
        # failure never discards completed (paid) LLM work. tailored.json holds
        # the pre-fit plain resume; the fit stage overwrites it with the trimmed
        # version once the PDF actually renders.
        self._write_report(out_dir, report)
        self._write_json(out_dir / "tailored.json", plain.model_dump(exclude_none=True))

        logger.info("[5/5] Rendering ...")
        try:
            if no_pdf:
                logger.warning(
                    "--no-pdf: skipping PDF compilation and the one-page fit loop; "
                    "the resume may exceed one page."
                )
                final = plain
                _render_resume(final, out_dir, False)
            else:
                scored = self._scored_resume(master, components)
                final = _fit_to_one_page(scored, out_dir)
                self._write_json(
                    out_dir / "tailored.json", final.model_dump(exclude_none=True)
                )
        except RenderError as exc:
            # Per-JD isolation: the tailored content is already persisted, so
            # return non-zero (batch marks the JD failed and continues) instead
            # of crashing the whole run/batch with a traceback.
            _print_render_failure(exc, out_dir)
            return 1

        logger.info("Done: coverage=%.0f%%, wrote %s", report.coverage_pct, out_dir)

        if ats_score:
            _run_ats_score(final, hiring_agent_path, self.pacer)

        return 0


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def _clear_stale_artifacts(out_dir: Path) -> None:
    """Remove any prior run's resume artifacts from ``out_dir``.

    Used on the truth-floor abort path so a failed run never leaves an outdated
    tailored.json / resume.tex / resume.pdf next to a violation-bearing report.
    ``match_report.json`` is intentionally NOT removed (it is the diagnostic).
    """
    for name in ("tailored.json", "resume.tex", "resume.pdf"):
        (out_dir / name).unlink(missing_ok=True)


def _print_render_failure(exc: Exception, out_dir: Path) -> None:
    bar = "!" * 72
    print("\n" + bar, file=sys.stderr)
    print(
        "RENDER FAILURE — the tailored resume could not be rendered to a "
        "one-page PDF.",
        file=sys.stderr,
    )
    print(f"  {exc}", file=sys.stderr)
    print(
        f"Tailored content was still saved to {out_dir / 'tailored.json'} and "
        f"{out_dir / 'match_report.json'} (no LLM work lost). Compile the .tex "
        "elsewhere (e.g. Overleaf), or resolve the issue and re-run.",
        file=sys.stderr,
    )
    print(bar + "\n", file=sys.stderr)


def _print_violation_failure(report: MatchReport, out_dir: Path) -> None:
    bar = "!" * 72
    print("\n" + bar, file=sys.stderr)
    print(
        "TRUTH FLOOR VIOLATION — refusing to render a resume with fabricated "
        "content.",
        file=sys.stderr,
    )
    print(
        f"{len(report.truth_violations)} unresolved violation(s) remain after the "
        "maximum tailoring passes:",
        file=sys.stderr,
    )
    for violation in report.truth_violations:
        print(f"  - [{violation.section}] {violation.claim}", file=sys.stderr)
        print(f"      reason: {violation.reason}", file=sys.stderr)
    print(
        "No resume was written. Fix the master resume (or its input) and re-run — "
        "the pipeline will not emit fabricated content.",
        file=sys.stderr,
    )
    print(
        f"(Diagnostic report written to {out_dir / 'match_report.json'}.)",
        file=sys.stderr,
    )
    print(bar + "\n", file=sys.stderr)


def _print_quota_exhausted(completed: List[str], remaining: List[str]) -> None:
    print("\n=== Gemini quota exhausted ===", file=sys.stderr)
    print(
        f"Completed ({len(completed)}): {', '.join(completed) or '(none)'}",
        file=sys.stderr,
    )
    print(
        f"Remaining ({len(remaining)}): {', '.join(remaining) or '(none)'}",
        file=sys.stderr,
    )
    print(
        "Gemini quota exhausted — wait and re-run the same command; completed JDs "
        "will be skipped.",
        file=sys.stderr,
    )


def _print_batch_summary(
    completed: List[str], skipped: List[str], failed: List[str]
) -> None:
    print("\n=== Batch complete ===")
    print(f"  Completed: {len(completed)} {completed}")
    print(f"  Skipped (already done): {len(skipped)} {skipped}")
    if failed:
        print(f"  Failed (no .done — will retry next run): {len(failed)} {failed}")


# ---------------------------------------------------------------------------
# Optional ATS scoring via the sibling hiring-agent evaluator
# ---------------------------------------------------------------------------


def _is_conflicting_module(name: str) -> bool:
    """Module names this repo and the hiring-agent BOTH define (different code)."""
    return name in ("models", "llm_utils", "prompt", "prompts") or name.startswith(
        "prompts."
    )


def _print_ats_scores(result: Any) -> None:
    scores = result.scores
    print("\n=== ATS evaluator score (sibling hiring-agent rubric) ===")
    rows = (
        ("Open source", scores.open_source),
        ("Self projects", scores.self_projects),
        ("Production", scores.production),
        ("Technical skills", scores.technical_skills),
    )
    total = 0.0
    for label, cat in rows:
        print(f"  {label:<17}: {cat.score:>5.1f} / {cat.max}")
        total += cat.score
    print(f"  {'Bonus':<17}: {result.bonus_points.total:>5.1f} / 20")
    print(f"  {'Deductions':<17}: {-result.deductions.total:>5.1f}")
    total += result.bonus_points.total - result.deductions.total
    print(f"  {'TOTAL':<17}: {total:>5.1f}")


def _run_ats_score(
    tailored: JSONResume, hiring_agent_path: str, pacer: Optional[RatePacer] = None
) -> None:
    """Run the hiring-agent's evaluator on ``tailored``; degrade gracefully.

    The hiring-agent ships its own ``models``/``llm_utils``/``prompt``/``prompts``
    modules that collide with ours in ``sys.modules``, and its ``TemplateManager``
    loads templates relative to the CWD. So we resolve paths first, snapshot and
    evict the conflicting modules, ``chdir`` into the checkout, import fresh, and
    restore everything in ``finally`` — mirroring bootstrap_master.py's pattern.
    """
    ha_dir = Path(hiring_agent_path).expanduser().resolve()
    if not (ha_dir / "evaluator.py").is_file():
        print(
            f"[--ats-score] hiring-agent evaluator not found at {ha_dir}; skipping.\n"
            "  Point --hiring-agent-path at your hiring-agent checkout.",
            file=sys.stderr,
        )
        return

    resume_dict = tailored.model_dump(exclude_none=True)
    original_cwd = os.getcwd()
    original_path = list(sys.path)
    saved_modules = {
        name: mod
        for name, mod in list(sys.modules.items())
        if _is_conflicting_module(name)
    }
    try:
        for name in saved_modules:
            del sys.modules[name]
        sys.path.insert(0, str(ha_dir))
        os.chdir(ha_dir)

        import importlib

        ha_models = importlib.import_module("models")
        ha_transform = importlib.import_module("transform")
        ha_evaluator = importlib.import_module("evaluator")

        ha_resume = ha_models.JSONResume(**resume_dict)
        resume_text = ha_transform.convert_json_resume_to_text(ha_resume)
        evaluator = ha_evaluator.ResumeEvaluator()
        if pacer is not None:
            pacer.wait()
        result = evaluator.evaluate_resume(resume_text)
        _print_ats_scores(result)
    except Exception as exc:  # broad on purpose: this is optional, never fatal
        print(
            f"[--ats-score] could not run the hiring-agent evaluator: {exc}\n"
            "  This is optional and does not affect the tailored resume. Common "
            "causes: the hiring-agent's dependencies or its .env (GEMINI_API_KEY) "
            "are not set up. See the README 'Bootstrap' section.",
            file=sys.stderr,
        )
    finally:
        os.chdir(original_cwd)
        sys.path[:] = original_path
        for name in [
            n
            for n in list(sys.modules)
            if _is_conflicting_module(n) and n not in saved_modules
        ]:
            del sys.modules[name]
        sys.modules.update(saved_modules)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _load_master(path: Path) -> JSONResume:
    data = json.loads(path.read_text(encoding="utf-8"))
    return JSONResume.model_validate(data)


def _add_common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="LLM model to use (default: %(default)s)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help="Minimum JD coverage %%; below it, weak sections are re-tailored "
        "(default: %(default)s)",
    )
    parser.add_argument(
        "--max-passes",
        type=int,
        default=DEFAULT_MAX_PASSES,
        dest="max_passes",
        help="Total tailoring passes cap — bounded iteration (default: %(default)s)",
    )
    parser.add_argument(
        "--no-pdf",
        action="store_true",
        dest="no_pdf",
        help="Skip PDF compilation and the one-page fit loop (no tectonic needed)",
    )
    parser.add_argument(
        "--ats-score",
        action="store_true",
        dest="ats_score",
        help="Also run the sibling hiring-agent evaluator and print category scores",
    )
    parser.add_argument(
        "--call-interval",
        type=float,
        default=DEFAULT_CALL_INTERVAL,
        dest="call_interval",
        help="Free-tier pacer: minimum seconds between LLM calls; 0 disables "
        "(default: %(default)s)",
    )
    parser.add_argument(
        "--hiring-agent-path",
        default=DEFAULT_HIRING_AGENT_PATH,
        dest="hiring_agent_path",
        help="hiring-agent checkout for --ats-score (default: %(default)s)",
    )


def run_single(args: argparse.Namespace) -> int:
    master_path = Path(args.master).expanduser()
    jd_path = Path(args.jd).expanduser()
    if not master_path.is_file():
        print(f"error: master resume not found: {master_path}", file=sys.stderr)
        return 2
    if not jd_path.is_file():
        print(f"error: job description not found: {jd_path}", file=sys.stderr)
        return 2

    master = _load_master(master_path)
    jd_text = jd_path.read_text(encoding="utf-8")

    pipeline = TailorPipeline(
        model=args.model,
        threshold=args.threshold,
        max_passes=args.max_passes,
        call_interval=args.call_interval,
    )
    return pipeline.run(
        master,
        jd_text,
        Path(args.out_dir).expanduser(),
        no_pdf=args.no_pdf,
        ats_score=args.ats_score,
        hiring_agent_path=args.hiring_agent_path,
    )


def run_batch(args: argparse.Namespace) -> int:
    master_path = Path(args.master).expanduser()
    jd_dir = Path(args.jd_dir).expanduser()
    out_dir = Path(args.out_dir).expanduser()

    if not master_path.is_file():
        print(f"error: master resume not found: {master_path}", file=sys.stderr)
        return 2
    if not jd_dir.is_dir():
        print(f"error: JD directory not found: {jd_dir}", file=sys.stderr)
        return 2

    master = _load_master(master_path)
    jds = sorted(jd_dir.glob("*.txt"))
    if not jds:
        print(f"No *.txt job descriptions found in {jd_dir}. Nothing to do.")
        return 0

    # One pipeline (and one pacer) spans the whole batch so the min-interval
    # spacing holds across JD boundaries too.
    pipeline = TailorPipeline(
        model=args.model,
        threshold=args.threshold,
        max_passes=args.max_passes,
        call_interval=args.call_interval,
    )

    completed: List[str] = []
    skipped: List[str] = []
    failed: List[str] = []

    for index, jd_path in enumerate(jds):
        stem = jd_path.stem
        jd_out = out_dir / stem
        if (jd_out / ".done").exists() and not args.force:
            logger.info("Skipping %s (already done).", stem)
            skipped.append(stem)
            continue

        # Invalidate any stale completion marker up front so a failed or
        # interrupted (re-)run — e.g. --force after editing the master — never
        # leaves the JD masked as "done" for later plain runs. Combined with
        # writing .done only on rc==0 below, this restores idempotent resume.
        (jd_out / ".done").unlink(missing_ok=True)

        logger.info("Processing %s ...", stem)
        jd_text = jd_path.read_text(encoding="utf-8")
        try:
            rc = pipeline.run(
                master,
                jd_text,
                jd_out,
                no_pdf=args.no_pdf,
                ats_score=args.ats_score,
                hiring_agent_path=args.hiring_agent_path,
            )
        except ResourceExhausted:
            # Force-aware: a stale .done from a prior run must NOT count a JD as
            # complete this run, so compute "remaining" from what we actually
            # finished/skipped this pass rather than from on-disk markers.
            done_now = set(completed) | set(skipped)
            remaining = [p.stem for p in jds if p.stem not in done_now]
            _print_quota_exhausted(completed, remaining)
            return QUOTA_EXIT_CODE
        except LLMExtractionError as exc:
            logger.error("JD %s failed (%s); continuing to the next JD.", stem, exc)
            failed.append(stem)
            continue

        if rc == 0:
            (jd_out / ".done").write_text("", encoding="utf-8")
            completed.append(stem)
        else:
            logger.warning(
                "JD %s did not complete (exit %d); no .done marker written.", stem, rc
            )
            failed.append(stem)

        if args.delay_seconds and index < len(jds) - 1:
            time.sleep(args.delay_seconds)

    _print_batch_summary(completed, skipped, failed)
    # Non-zero when any JD failed so scripted/cron callers can detect it; 0 for
    # all-completed/skipped, 75 reserved for quota exhaustion (returned above).
    return 1 if failed else 0


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if argv and argv[0] == "batch":
        parser = argparse.ArgumentParser(
            prog="tailor.py batch",
            description="Tailor a master resume to every *.txt JD in a folder.",
        )
        parser.add_argument(
            "--master",
            default="master.json",
            help="Master resume JSON, JSON Resume format (default: %(default)s)",
        )
        parser.add_argument(
            "--jd-dir",
            default="jds",
            dest="jd_dir",
            help="Folder scanned for *.txt job descriptions (default: %(default)s)",
        )
        parser.add_argument(
            "--out-dir",
            default="output",
            dest="out_dir",
            help="Where per-JD output directories are written (default: %(default)s)",
        )
        parser.add_argument(
            "--delay-seconds",
            type=float,
            default=0.0,
            dest="delay_seconds",
            help="Extra pause between JDs (default: %(default)s)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Ignore .done markers and re-process every JD",
        )
        _add_common_flags(parser)
        return run_batch(parser.parse_args(argv[1:]))

    parser = argparse.ArgumentParser(
        prog="tailor.py",
        description="Tailor a master resume to a single job description.",
    )
    parser.add_argument("master", help="Master resume JSON (JSON Resume format)")
    parser.add_argument("jd", help="Job description text file")
    parser.add_argument(
        "-o",
        "--out-dir",
        dest="out_dir",
        required=True,
        help="Output directory for tailored.json / resume.tex / resume.pdf / "
        "match_report.json",
    )
    _add_common_flags(parser)
    return run_single(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
