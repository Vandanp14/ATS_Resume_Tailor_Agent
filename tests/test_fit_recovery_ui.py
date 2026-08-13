"""Static contract for the guided one-page fit recovery interface."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_fit_recovery_shell_is_native_and_accessible():
    index = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")

    assert 'id="fit-recovery-card"' in index
    assert '<dialog class="recovery-dialog"' in index
    assert 'id="fit-recovery-form"' in index
    assert 'id="recovery-options"' in index
    assert 'id="recovery-selection-error" role="alert"' in index
    assert 'id="recovery-submit-status" role="status" aria-live="polite"' in index
    assert "Your master resume will not change" in index


def test_fit_recovery_client_uses_safe_rendering_and_api_contract():
    app_js = (REPO_ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert "job_action_required" in app_js
    assert "/fit-recovery`" in app_js
    assert "recommended_candidate_ids" in app_js
    assert 'name = "candidate_ids"' in app_js
    assert '"Idempotency-Key": state.recovery.idempotencyKey' in app_js
    assert "crypto.randomUUID()" in app_js
    assert "innerHTML" not in app_js
    assert "insertAdjacentHTML" not in app_js


def test_fit_recovery_styles_cover_status_mobile_focus_and_motion():
    app_css = (REPO_ROOT / "static" / "app.css").read_text(encoding="utf-8")

    assert ".status-pill.action_required" in app_css
    assert ".job-state-mark.action_required" in app_css
    assert ".fit-recovery-card" in app_css
    assert ".recovery-dialog" in app_css
    assert "block-size: 100dvh" in app_css
    assert ":focus-visible" in app_css
    assert "prefers-reduced-motion" in app_css
