"""Durable, user-directed recovery for resumes that still exceed one page."""

from __future__ import annotations

import math
import secrets
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from models import JSONResume, ScoredBullet
from render import ScoredResume, count_pages, render, scored_to_plain

from .qualifications import recheck_on_page

from .runtime import write_json


FIT_RECOVERY_FILENAME = ".fit_recovery.json"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class FitRecoveryCandidate(_StrictModel):
    candidate_id: str = Field(min_length=1)
    kind: Literal["work_bullet", "project_bullet", "skill_group"]
    group: Literal["Work", "Projects", "Skills"]
    label: str = Field(min_length=1)
    text: str = Field(min_length=1)
    relevance: int = Field(ge=0, le=100)
    estimated_lines: int = Field(ge=1)
    recommendation: Literal["recommended", "consider", "keep_if_possible"]
    reason: str = Field(min_length=1)


class FitCandidateLocation(_StrictModel):
    section: Literal["work", "projects", "skills"]
    item_index: int = Field(ge=0)
    bullet_index: int | None = Field(default=None, ge=0)


class FitRecoveryBundle(_StrictModel):
    revision: int = Field(ge=1)
    page_count: int = Field(ge=2)
    concision_attempts: int = Field(ge=0)
    candidates: list[FitRecoveryCandidate]
    recommended_candidate_ids: list[str]
    scored_resume: ScoredResume
    pending_report: dict[str, object]
    trim_log: list[str]
    concision_log: list[dict[str, object]]
    candidate_locations: dict[str, FitCandidateLocation]


class FitRecoveryRequired(RuntimeError):
    """The automatic fitter exhausted all safe rewrites and needs user input."""

    def __init__(
        self,
        scored_resume: ScoredResume,
        page_count: int,
        trim_log: Sequence[str],
        concision_log: Sequence[dict[str, object]],
    ) -> None:
        self.scored_resume = scored_resume.model_copy(deep=True)
        self.page_count = page_count
        self.trim_log = list(trim_log)
        self.concision_log = [dict(item) for item in concision_log]
        super().__init__(
            "The resume still spans multiple pages after all safe automatic "
            "trims and emergency concision attempts."
        )


class FitRecoverySelectionError(ValueError):
    """A manual recovery selection is empty, duplicated, or stale."""


def _candidate_id() -> str:
    return f"fit_{secrets.token_urlsafe(12)}"


def _estimated_lines(text: str) -> int:
    return max(1, math.ceil(len(text) / 96))


def _candidate_rows(
    resume: ScoredResume,
) -> tuple[list[FitRecoveryCandidate], dict[str, FitCandidateLocation]]:
    candidates: list[FitRecoveryCandidate] = []
    locations: dict[str, FitCandidateLocation] = {}

    def add(
        *,
        kind: Literal["work_bullet", "project_bullet", "skill_group"],
        group: Literal["Work", "Projects", "Skills"],
        label: str,
        text: str,
        relevance: int,
        location: FitCandidateLocation,
    ) -> None:
        candidate_id = _candidate_id()
        candidates.append(
            FitRecoveryCandidate(
                candidate_id=candidate_id,
                kind=kind,
                group=group,
                label=label,
                text=text,
                relevance=relevance,
                estimated_lines=_estimated_lines(text),
                recommendation="consider",
                reason="Available for user-directed removal if more space is needed.",
            )
        )
        locations[candidate_id] = location

    for item_index, item in enumerate(resume.work or []):
        label = " · ".join(value for value in (item.position, item.name) if value)
        for bullet_index, bullet in enumerate(item.highlights or []):
            add(
                kind="work_bullet",
                group="Work",
                label=label or f"Work entry {item_index + 1}",
                text=bullet.text,
                relevance=bullet.relevance,
                location=FitCandidateLocation(
                    section="work",
                    item_index=item_index,
                    bullet_index=bullet_index,
                ),
            )
    for item_index, item in enumerate(resume.projects or []):
        for bullet_index, bullet in enumerate(item.highlights or []):
            add(
                kind="project_bullet",
                group="Projects",
                label=item.name or f"Project {item_index + 1}",
                text=bullet.text,
                relevance=bullet.relevance,
                location=FitCandidateLocation(
                    section="projects",
                    item_index=item_index,
                    bullet_index=bullet_index,
                ),
            )
    for item_index, item in enumerate(resume.skills or []):
        text = f"{item.name}: {', '.join(item.keywords)}"
        add(
            kind="skill_group",
            group="Skills",
            label=item.name,
            text=text,
            relevance=item.relevance,
            location=FitCandidateLocation(section="skills", item_index=item_index),
        )
    return candidates, locations


def _apply_locations(
    resume: ScoredResume, locations: Sequence[FitCandidateLocation]
) -> None:
    ordered = sorted(
        locations,
        key=lambda item: (
            item.section,
            item.item_index,
            item.bullet_index if item.bullet_index is not None else -1,
        ),
        reverse=True,
    )
    for location in ordered:
        if location.section == "skills":
            if resume.skills is not None:
                resume.skills.pop(location.item_index)
            continue
        entries = resume.work if location.section == "work" else resume.projects
        if entries is None or location.bullet_index is None:
            continue
        highlights = entries[location.item_index].highlights
        if highlights is not None:
            highlights.pop(location.bullet_index)


def _real_page_counter(job_dir: Path) -> Callable[[JSONResume], int]:
    def counter(plain: JSONResume) -> int:
        result = render(plain, job_dir, compile_pdf=True)
        if result.pdf is None:
            raise RuntimeError("PDF compilation returned no PDF path")
        return count_pages(result.pdf)

    return counter


def _recommend(
    resume: ScoredResume,
    candidates: list[FitRecoveryCandidate],
    locations: dict[str, FitCandidateLocation],
    page_counter: Callable[[JSONResume], int],
) -> tuple[list[FitRecoveryCandidate], list[str]]:
    ranked = sorted(
        candidates,
        key=lambda item: (item.relevance, -item.estimated_lines),
    )
    recommended: list[str] = []
    fits = False
    for candidate in ranked:
        recommended.append(candidate.candidate_id)
        simulation = resume.model_copy(deep=True)
        _apply_locations(simulation, [locations[item] for item in recommended])
        if page_counter(scored_to_plain(simulation)) == 1:
            fits = True
            break

    selected = set(recommended)
    rows: list[FitRecoveryCandidate] = []
    for candidate in candidates:
        if candidate.candidate_id in selected:
            suffix = "; this verified set reaches one page" if fits else ""
            rows.append(
                candidate.model_copy(
                    update={
                        "recommendation": "recommended",
                        "reason": (
                            f"Low relevance ({candidate.relevance}/100) with an "
                            f"estimated {candidate.estimated_lines}-line saving{suffix}."
                        ),
                    }
                )
            )
        elif candidate.relevance >= 80:
            rows.append(
                candidate.model_copy(
                    update={
                        "recommendation": "keep_if_possible",
                        "reason": (
                            f"High relevance ({candidate.relevance}/100); keep unless "
                            "lower-relevance choices are insufficient."
                        ),
                    }
                )
            )
        else:
            rows.append(
                candidate.model_copy(
                    update={
                        "recommendation": "consider",
                        "reason": (
                            f"Moderate relevance ({candidate.relevance}/100); not needed "
                            "by the smallest ranked recommendation set."
                        ),
                    }
                )
            )
    return rows, recommended


def persist_fit_recovery(
    job_dir: Path,
    scored_resume: ScoredResume,
    *,
    page_count: int,
    pending_report: dict[str, object],
    trim_log: Sequence[str],
    concision_log: Sequence[dict[str, object]],
    revision: int = 1,
    page_counter: Callable[[JSONResume], int] | None = None,
) -> FitRecoveryBundle:
    """Build recommendations, persist private state, and return the bundle."""
    job_dir = Path(job_dir)
    candidates, locations = _candidate_rows(scored_resume)
    if page_counter is None:
        with tempfile.TemporaryDirectory(prefix="fit-recovery-", dir=job_dir) as raw:
            rows, recommended = _recommend(
                scored_resume,
                candidates,
                locations,
                _real_page_counter(Path(raw)),
            )
    else:
        rows, recommended = _recommend(
            scored_resume, candidates, locations, page_counter
        )
    bundle = FitRecoveryBundle(
        revision=revision,
        page_count=page_count,
        concision_attempts=len(concision_log),
        candidates=rows,
        recommended_candidate_ids=recommended,
        scored_resume=scored_resume,
        pending_report=pending_report,
        trim_log=list(trim_log),
        concision_log=[dict(item) for item in concision_log],
        candidate_locations=locations,
    )
    write_json(job_dir / FIT_RECOVERY_FILENAME, bundle)
    return bundle


def load_fit_recovery(job_dir: Path) -> FitRecoveryBundle:
    path = Path(job_dir) / FIT_RECOVERY_FILENAME
    return FitRecoveryBundle.model_validate_json(path.read_text(encoding="utf-8"))


def apply_fit_recovery(
    job_dir: Path,
    candidate_ids: list[str],
    *,
    page_counter: Callable[[JSONResume], int] | None = None,
) -> int:
    """Apply a validated manual selection; return 0 on completion or 2 if still large."""
    if not candidate_ids:
        raise FitRecoverySelectionError("Select at least one removal candidate.")
    if len(candidate_ids) != len(set(candidate_ids)):
        raise FitRecoverySelectionError("Removal candidate IDs must be unique.")
    job_dir = Path(job_dir)
    bundle = load_fit_recovery(job_dir)
    unknown = set(candidate_ids) - set(bundle.candidate_locations)
    if unknown:
        raise FitRecoverySelectionError(
            f"Unknown or stale removal candidate IDs: {sorted(unknown)}"
        )

    updated = bundle.scored_resume.model_copy(deep=True)
    _apply_locations(
        updated, [bundle.candidate_locations[item] for item in candidate_ids]
    )
    plain = scored_to_plain(updated)
    counter = page_counter or _real_page_counter(job_dir)
    pages = counter(plain)
    removals = [
        candidate.model_dump(mode="json")
        for candidate in bundle.candidates
        if candidate.candidate_id in set(candidate_ids)
    ]
    report = dict(bundle.pending_report)
    report["manual_fit_removals"] = [
        *(report.get("manual_fit_removals", [])),
        *removals,
    ]

    if pages == 1:
        if page_counter is not None:
            render(plain, job_dir, compile_pdf=False)
        if report.get("qualification_coverage"):
            report["qualification_coverage"] = recheck_on_page(
                report["qualification_coverage"], updated, plain
            )
        write_json(job_dir / "tailored.json", plain)
        report["pipeline_status"] = "completed_with_manual_fit"
        write_json(job_dir / "match_report.json", report)
        write_json(job_dir / ".done", {"pdf": page_counter is None})
        (job_dir / FIT_RECOVERY_FILENAME).unlink(missing_ok=True)
        return 0

    report["pipeline_status"] = "action_required"
    persist_fit_recovery(
        job_dir,
        updated,
        page_count=pages,
        pending_report=report,
        trim_log=bundle.trim_log,
        concision_log=bundle.concision_log,
        revision=bundle.revision + 1,
        page_counter=page_counter,
    )
    for name in ("resume.tex", "resume.pdf"):
        (job_dir / name).unlink(missing_ok=True)
    return 2


__all__ = [
    "FIT_RECOVERY_FILENAME",
    "FitRecoveryBundle",
    "FitRecoveryCandidate",
    "FitRecoveryRequired",
    "FitRecoverySelectionError",
    "apply_fit_recovery",
    "load_fit_recovery",
    "persist_fit_recovery",
]
