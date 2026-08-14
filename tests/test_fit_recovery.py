"""Durable manual one-page recovery contracts."""

from models import Basics, ScoredBullet, ScoredSkill, ScoredWork
from render import ScoredResume
from resume_tailor.fit_recovery import (
    FIT_RECOVERY_FILENAME,
    FitRecoverySelectionError,
    apply_fit_recovery,
    load_fit_recovery,
    persist_fit_recovery,
)


def _resume() -> ScoredResume:
    return ScoredResume(
        basics=Basics(name="Overflow"),
        work=[
            ScoredWork(
                name="Acme",
                position="Engineer",
                relevance=80,
                highlights=[
                    ScoredBullet(text="Lowest relevance bullet", relevance=10),
                    ScoredBullet(text="Moderate relevance bullet", relevance=40),
                    ScoredBullet(text="Highest relevance bullet", relevance=90),
                ],
            )
        ],
        skills=[ScoredSkill(name="Languages", keywords=["Python"], relevance=70)],
    )


def _bullet_counter(plain):
    return 1 if sum(len(item.highlights or []) for item in plain.work or []) <= 1 else 2


def test_persist_recovery_builds_private_strict_bundle(tmp_path):
    bundle = persist_fit_recovery(
        tmp_path,
        _resume(),
        page_count=2,
        pending_report={"coverage_pct": 90},
        trim_log=["tier-b: skill group"],
        concision_log=[{"candidate_id": "work:0:0"}],
        page_counter=_bullet_counter,
    )

    assert (tmp_path / FIT_RECOVERY_FILENAME).is_file()
    assert bundle.revision == 1
    assert bundle.concision_attempts == 1
    assert bundle.recommended_candidate_ids
    assert set(bundle.candidate_locations) == {
        item.candidate_id for item in bundle.candidates
    }
    assert load_fit_recovery(tmp_path) == bundle
    assert bundle.candidates[0].candidate_id.startswith("fit_")
    assert bundle.candidates[0].recommendation == "recommended"


def test_apply_recommended_removals_completes_and_audits(tmp_path):
    bundle = persist_fit_recovery(
        tmp_path,
        _resume(),
        page_count=2,
        pending_report={"pipeline_status": "action_required"},
        trim_log=[],
        concision_log=[],
        page_counter=_bullet_counter,
    )

    result = apply_fit_recovery(
        tmp_path,
        bundle.recommended_candidate_ids,
        page_counter=_bullet_counter,
    )

    assert result == 0
    assert not (tmp_path / FIT_RECOVERY_FILENAME).exists()
    assert (tmp_path / "tailored.json").is_file()
    assert (tmp_path / "match_report.json").is_file()
    assert (tmp_path / ".done").is_file()


def test_apply_insufficient_selection_increments_revision(tmp_path):
    bundle = persist_fit_recovery(
        tmp_path,
        _resume(),
        page_count=2,
        pending_report={},
        trim_log=[],
        concision_log=[],
        page_counter=lambda plain: (
            1
            if sum(len(item.highlights or []) for item in plain.work or []) == 0
            else 2
        ),
    )
    (tmp_path / "resume.tex").write_text("partial", encoding="utf-8")
    (tmp_path / "resume.pdf").write_bytes(b"partial")

    result = apply_fit_recovery(
        tmp_path,
        [bundle.recommended_candidate_ids[0]],
        page_counter=lambda plain: (
            1
            if sum(len(item.highlights or []) for item in plain.work or []) == 0
            else 2
        ),
    )

    assert result == 2
    assert load_fit_recovery(tmp_path).revision == 2
    assert not (tmp_path / "resume.tex").exists()
    assert not (tmp_path / "resume.pdf").exists()


def test_apply_rejects_empty_duplicate_and_stale_ids(tmp_path):
    bundle = persist_fit_recovery(
        tmp_path,
        _resume(),
        page_count=2,
        pending_report={},
        trim_log=[],
        concision_log=[],
        page_counter=_bullet_counter,
    )
    candidate_id = bundle.candidates[0].candidate_id

    for ids in ([], [candidate_id, candidate_id], ["fit_stale"]):
        try:
            apply_fit_recovery(tmp_path, ids, page_counter=_bullet_counter)
        except FitRecoverySelectionError:
            pass
        else:  # pragma: no cover - assertion branch
            raise AssertionError(f"selection should have failed: {ids}")
