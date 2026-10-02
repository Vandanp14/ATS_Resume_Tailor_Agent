"""Durable, user-directed review of bullets the model could not get right.

When a rewrite stage still breaks a check after its retries, the pipeline does
not fail. It finishes with a safe version of each flawed bullet (the flagged
term cut out, or the bullet written from its master fact) and, in the web app,
pauses before rendering so the user can choose per bullet: keep the model's
text, use the safe version, or regenerate just that bullet.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from render import ScoredResume, fit_to_one_page, render, scored_to_plain

from .fit_recovery import FitRecoveryRequired, persist_fit_recovery
from .runtime import write_json


BULLET_REVIEW_FILENAME = ".bullet_review.json"
ReviewChoice = Literal["keep", "safe", "regenerate"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class BulletFlag(_StrictModel):
    flag_id: str = Field(min_length=1)
    section: Literal["work", "projects"]
    source_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    assignment_id: str | None = None
    issues: list[str] = Field(min_length=1)
    original_text: str | None = None
    safe_text: str = Field(min_length=1)
    safe_kind: Literal["edited", "source_fact"]
    can_keep: bool
    source_fact_ids: list[str]
    source_facts: list[str] = Field(default_factory=list)


class BulletReviewBundle(_StrictModel):
    revision: int = Field(ge=1)
    flags: list[BulletFlag] = Field(min_length=1)
    scored_resume: ScoredResume
    pending_report: dict[str, object]
    no_pdf: bool
    jd_profile_json: str
    forbidden_terms: list[str]
    tech_requirements: list[list[object]] = Field(default_factory=list)


class BulletReviewSelectionError(ValueError):
    """A review decision names an unknown flag or an unavailable choice."""


def _entries(resume: ScoredResume, section: str) -> list:
    return list((resume.work if section == "work" else resume.projects) or [])


def live_flags(resume: ScoredResume, flags: Sequence[Mapping]) -> list[dict]:
    """Flags whose safe bullet survived later stages (a reviewer edit may replace it)."""

    present = {
        (section, item.source_id, bullet.text)
        for section in ("work", "projects")
        for item in _entries(resume, section)
        for bullet in item.highlights or []
    }
    return [
        dict(flag)
        for flag in flags
        if (flag["section"], flag["source_id"], flag["safe_text"]) in present
    ]


def persist_bullet_review(
    job_dir: Path,
    scored_resume: ScoredResume,
    flags: Sequence[Mapping],
    *,
    pending_report: dict[str, object],
    no_pdf: bool,
    jd_profile_json: str,
    forbidden_terms: Sequence[str],
    tech_requirements: Sequence[tuple[str, Sequence[str]]],
    fact_index: Mapping[str, dict],
) -> BulletReviewBundle:
    bundle = BulletReviewBundle(
        revision=1,
        flags=[
            BulletFlag(
                flag_id=f"rev_{secrets.token_urlsafe(9)}",
                source_facts=[
                    fact_index[fact_id]["text"]
                    for fact_id in flag["source_fact_ids"]
                    if fact_id in fact_index
                ],
                **flag,
            )
            for flag in flags
        ],
        scored_resume=scored_resume,
        pending_report=pending_report,
        no_pdf=no_pdf,
        jd_profile_json=jd_profile_json,
        forbidden_terms=list(forbidden_terms),
        tech_requirements=[[term, list(variants)] for term, variants in tech_requirements],
    )
    write_json(Path(job_dir) / BULLET_REVIEW_FILENAME, bundle)
    return bundle


def load_bullet_review(job_dir: Path) -> BulletReviewBundle:
    path = Path(job_dir) / BULLET_REVIEW_FILENAME
    return BulletReviewBundle.model_validate_json(path.read_text(encoding="utf-8"))


def _raise_fit_recovery(resume: ScoredResume, pages: int, trim_log: tuple[str, ...]):
    raise FitRecoveryRequired(resume, pages, trim_log, [])


def apply_bullet_review(
    job_dir: Path,
    decisions: Mapping[str, ReviewChoice],
    *,
    regenerate: Callable[[BulletFlag, BulletReviewBundle], str | None] | None = None,
    page_counter: Callable[..., int] | None = None,
    progress: Callable[[str], None] | None = None,
) -> int:
    """Apply the user's choices, then render; 0 = done, 2 = needs fit recovery."""

    job_dir = Path(job_dir)
    bundle = load_bullet_review(job_dir)
    flags = {flag.flag_id: flag for flag in bundle.flags}
    unknown = set(decisions) - set(flags)
    if unknown:
        raise BulletReviewSelectionError(
            f"Unknown or stale review items: {sorted(unknown)}"
        )
    resume = bundle.scored_resume.model_copy(deep=True)
    applied: list[dict[str, object]] = []
    for flag in bundle.flags:
        choice = decisions.get(flag.flag_id, "safe")
        if choice == "keep" and not flag.can_keep:
            raise BulletReviewSelectionError(
                f"'{flag.label}' cannot be kept as written: {flag.issues[0]}"
            )
        text = flag.safe_text
        outcome = "safe"
        if choice == "keep":
            text, outcome = flag.original_text or flag.safe_text, "kept"
        elif choice == "regenerate":
            if progress:
                progress(f"Regenerating a bullet for {flag.label}")
            regenerated = regenerate(flag, bundle) if regenerate else None
            if regenerated:
                text, outcome = regenerated, "regenerated"
            else:
                outcome = "regenerate_failed_used_safe"
        for item in _entries(resume, flag.section):
            if item.source_id != flag.source_id:
                continue
            for bullet in item.highlights or []:
                if bullet.text == flag.safe_text:
                    bullet.text = text
                    break
        applied.append(
            {
                "label": flag.label,
                "issues": flag.issues,
                "choice": choice,
                "outcome": outcome,
                "final_text": text,
            }
        )

    report = dict(bundle.pending_report)
    report["bullet_review_decisions"] = applied
    try:
        if bundle.no_pdf:
            plain = scored_to_plain(resume)
            render(plain, job_dir, False)
        else:
            plain = fit_to_one_page(
                resume,
                job_dir,
                page_counter=page_counter,
                progress_callback=progress,
                exhaustion_handler=_raise_fit_recovery,
            )
    except FitRecoveryRequired as recovery:
        report["pipeline_status"] = "action_required"
        persist_fit_recovery(
            job_dir,
            recovery.scored_resume,
            page_count=recovery.page_count,
            pending_report=report,
            trim_log=recovery.trim_log,
            concision_log=[],
            page_counter=page_counter,
        )
        (job_dir / BULLET_REVIEW_FILENAME).unlink(missing_ok=True)
        for name in ("resume.tex", "resume.pdf"):
            (job_dir / name).unlink(missing_ok=True)
        return 2
    write_json(job_dir / "tailored.json", plain)
    report["pipeline_status"] = "completed_with_bullet_review"
    write_json(job_dir / "match_report.json", report)
    write_json(job_dir / ".done", {"pdf": not bundle.no_pdf})
    (job_dir / BULLET_REVIEW_FILENAME).unlink(missing_ok=True)
    return 0


__all__ = [
    "BULLET_REVIEW_FILENAME",
    "BulletFlag",
    "BulletReviewBundle",
    "BulletReviewSelectionError",
    "apply_bullet_review",
    "live_flags",
    "load_bullet_review",
    "persist_bullet_review",
]
