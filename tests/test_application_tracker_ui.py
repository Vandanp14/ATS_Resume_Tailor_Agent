"""Static contract for the application tracking dashboard and editor."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_application_dashboard_and_editor_are_accessible():
    index = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")

    assert 'id="apps-dashboard" aria-labelledby="apps-title"' in index
    assert 'id="apps-download-csv" href="/api/applications.csv"' in index
    assert '<label for="apps-search">Search applications</label>' in index
    assert '<label for="apps-filter">Application status</label>' in index
    assert 'id="job-application-card"' in index
    assert '<dialog class="application-editor-dialog"' in index
    assert 'id="application-editor-description"' in index
    assert 'id="app-applied-on-field" hidden' in index
    assert 'id="reload-application-editor" type="button" hidden' in index


def test_application_client_uses_safe_api_and_state_contracts():
    app_js = (REPO_ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert 'fetchJson("/api/applications")' in app_js
    assert "Array.isArray(body.items)" in app_js
    assert 'method: "PUT"' in app_js
    assert 'kind === "job_application_updated"' in app_js
    assert "error.status = response.status" in app_js
    assert "job.application_tracking_available === false" in app_js
    assert "innerHTML" not in app_js
    assert "insertAdjacentHTML" not in app_js
    assert '$("#' not in app_js


def test_application_styles_cover_status_responsive_and_focus_states():
    app_css = (REPO_ROOT / "static" / "app.css").read_text(encoding="utf-8")

    assert ".application-badge.applied" in app_css
    assert ".application-badge.not_applied" in app_css
    assert ".job-application-card" in app_css
    assert ".application-editor-dialog" in app_css
    assert "@media (max-width: 32rem)" in app_css
    assert ":focus-visible" in app_css
    assert "prefers-reduced-motion" in app_css
