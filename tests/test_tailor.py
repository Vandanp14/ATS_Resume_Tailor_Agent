"""Unit tests for the tailoring orchestrator (tailor.py).

Every LLM call (``tailor.call_llm_with_retry``) and every renderer entry point
(``tailor._render_resume`` / ``tailor._fit_to_one_page``) is mocked, so these run
with no network and no LaTeX toolchain. The LLM stub dispatches on the requested
``response_model`` and records each call, which lets the tests assert *which*
section templates were (re-)invoked and *what* feedback rode along.

Coverage:
* happy single pass (no re-run);
* low coverage -> exactly one targeted re-run of only the weak section, with
  gap feedback passed through;
* a persisting truth violation blocks rendering and exits non-zero;
* education passthrough is byte-identical to the master;
* the free-tier pacer sleeps ~call-interval between calls (and 0 disables it);
* the PDF path routes through the one-page fit loop, not a bare render;
* batch: 3 JDs -> 3 dirs; re-run skips ``.done``; ``--force`` reprocesses; a
  mid-batch ResourceExhausted exits 75 with correct completed/remaining lists.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import tailor
from tailor import ResourceExhausted
from models import (
    JDProfile,
    JSONResume,
    KeywordWeight,
    MatchReport,
    ScoredBullet,
    ScoredProject,
    ScoredSkill,
    ScoredWork,
    TailoredProjects,
    TailoredSkills,
    TailoredSummary,
    TailoredWork,
    TruthViolation,
)


# ---------------------------------------------------------------------------
# Fixtures / stubs
# ---------------------------------------------------------------------------

MASTER = {
    "basics": {
        "name": "Jordan Doe",
        "email": "jordan@example.com",
        "summary": "Software engineer, 4 years.",
    },
    "education": [
        {
            "institution": "State University",
            "area": "Computer Science",
            "studyType": "BS",
            "startDate": "2015",
            "endDate": "2019",
        }
    ],
    "work": [
        {
            "name": "Acme Payments",
            "position": "Software Engineer",
            "startDate": "2021-01",
            "highlights": ["Built the billing service"],
        }
    ],
    "skills": [{"name": "Languages", "keywords": ["Python", "Go"]}],
    "projects": [
        {
            "name": "kafka-python",
            "url": "https://github.com/x/kafka-python",
            "technologies": ["Python"],
        }
    ],
}


def _good_report() -> MatchReport:
    return MatchReport(
        coverage_pct=95.0,
        missing_must_haves=[],
        weak_sections=[],
        truth_violations=[],
    )


def _low_report() -> MatchReport:
    return MatchReport(
        coverage_pct=60.0,
        missing_must_haves=["Kubernetes"],
        weak_sections=["skills"],
        truth_violations=[],
    )


def _violation_report() -> MatchReport:
    return MatchReport(
        coverage_pct=70.0,
        missing_must_haves=[],
        weak_sections=[],
        truth_violations=[
            TruthViolation(
                section="work",
                claim="Led a team of 8 engineers",
                reason="The master lists this role as an individual contributor.",
            )
        ],
    )


class LLMStub:
    """Stand-in for ``call_llm_with_retry`` that dispatches on ``response_model``."""

    def __init__(self, reports, raise_resource_on=None):
        self.reports = list(reports)
        self._report_idx = 0
        self.calls = []
        self.raise_resource_on = raise_resource_on

        self.jd = JDProfile(
            role="Backend Engineer",
            seniority=None,
            domain="payments",
            must_have_skills=["Python", "Kubernetes"],
            nice_to_have_skills=["Go"],
            keywords=[KeywordWeight(term="Python", weight=5)],
        )
        self.summary = TailoredSummary(
            summary="Backend engineer who built payments services."
        )
        self.skills = TailoredSkills(
            skills=[
                ScoredSkill(name="Languages", keywords=["Python", "Go"], relevance=90)
            ]
        )
        self.work = TailoredWork(
            work=[
                ScoredWork(
                    name="Acme Payments",
                    position="Software Engineer",
                    startDate="2021-01",
                    relevance=90,
                    highlights=[
                        ScoredBullet(text="Built the billing service", relevance=85)
                    ],
                )
            ]
        )
        self.projects = TailoredProjects(
            projects=[
                ScoredProject(
                    name="kafka-python",
                    url="https://github.com/x/kafka-python",
                    technologies=["Python"],
                    relevance=80,
                )
            ]
        )

    def __call__(
        self,
        provider,
        model,
        messages=None,
        response_model=None,
        options=None,
        max_retries=2,
    ):
        user = messages[-1]["content"] if messages else ""
        self.calls.append(
            {"response_model": response_model, "messages": messages, "user": user}
        )
        if response_model is JDProfile:
            if self.raise_resource_on and self.raise_resource_on in user:
                raise ResourceExhausted("quota exhausted")
            return self.jd
        if response_model is TailoredSummary:
            return self.summary
        if response_model is TailoredSkills:
            return self.skills
        if response_model is TailoredWork:
            return self.work
        if response_model is TailoredProjects:
            return self.projects
        if response_model is MatchReport:
            report = self.reports[min(self._report_idx, len(self.reports) - 1)]
            self._report_idx += 1
            return report
        raise AssertionError(f"unexpected response_model: {response_model}")

    def count(self, model) -> int:
        return sum(1 for c in self.calls if c["response_model"] is model)

    def calls_for(self, model):
        return [c for c in self.calls if c["response_model"] is model]


@pytest.fixture(autouse=True)
def _no_real_provider(monkeypatch):
    """Never build a real LLM provider during unit tests."""
    monkeypatch.setattr(
        tailor, "initialize_llm_provider", lambda model: MagicMock(name="provider")
    )


def _master() -> JSONResume:
    return JSONResume.model_validate(MASTER)


def _run(
    monkeypatch,
    out_dir: Path,
    reports,
    *,
    no_pdf=True,
    max_passes=2,
    call_interval=0.0,
    threshold=80.0,
    fit_return=None,
):
    """Wire mocks, run one pipeline, return (rc, stub, render_mock, fit_mock)."""
    stub = LLMStub(reports)
    render_mock = MagicMock(name="render")
    fit_mock = MagicMock(name="fit", return_value=fit_return or _master())
    monkeypatch.setattr(tailor, "call_llm_with_retry", stub)
    monkeypatch.setattr(tailor, "_render_resume", render_mock)
    monkeypatch.setattr(tailor, "_fit_to_one_page", fit_mock)

    pipeline = tailor.TailorPipeline(
        model="gemini-3.1-flash-lite",
        threshold=threshold,
        max_passes=max_passes,
        call_interval=call_interval,
        provider=MagicMock(),
    )
    rc = pipeline.run(
        _master(), "Hiring a Backend Engineer. Need Python.", out_dir, no_pdf=no_pdf
    )
    return rc, stub, render_mock, fit_mock


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_single_pass(monkeypatch, tmp_path):
    out = tmp_path / "out"
    rc, stub, render_mock, fit_mock = _run(
        monkeypatch, out, [_good_report()], no_pdf=True
    )

    assert rc == 0
    # 1 JD parse + 4 section tailors + 1 score = 6 calls, no re-run.
    assert len(stub.calls) == 6
    assert stub.count(JDProfile) == 1
    assert stub.count(TailoredSummary) == 1
    assert stub.count(TailoredSkills) == 1
    assert stub.count(TailoredWork) == 1
    assert stub.count(TailoredProjects) == 1
    assert stub.count(MatchReport) == 1

    # no-pdf path renders (compile disabled) and never runs the fit loop.
    assert render_mock.call_count == 1
    assert render_mock.call_args.args[2] is False
    fit_mock.assert_not_called()

    assert (out / "tailored.json").is_file()
    assert (out / "match_report.json").is_file()
    report = json.loads((out / "match_report.json").read_text())
    assert report["coverage_pct"] == 95.0


def test_pdf_path_uses_fit_loop_not_bare_render(monkeypatch, tmp_path):
    out = tmp_path / "out"
    fit_result = _master()
    rc, stub, render_mock, fit_mock = _run(
        monkeypatch, out, [_good_report()], no_pdf=False, fit_return=fit_result
    )

    assert rc == 0
    # PDF path trims to one page via fit_to_one_page (which renders internally);
    # tailor.py does not also call the bare renderer.
    fit_mock.assert_called_once()
    render_mock.assert_not_called()
    # The ScoredResume handed to the fit loop preserves relevance fields.
    scored_arg = fit_mock.call_args.args[0]
    assert scored_arg.work[0].relevance == 90
    assert scored_arg.work[0].highlights[0].relevance == 85
    assert (out / "tailored.json").is_file()


# ---------------------------------------------------------------------------
# Bounded iteration
# ---------------------------------------------------------------------------


def test_low_coverage_triggers_one_targeted_rerun(monkeypatch, tmp_path):
    out = tmp_path / "out"
    rc, stub, render_mock, fit_mock = _run(
        monkeypatch, out, [_low_report(), _good_report()], no_pdf=True
    )

    assert rc == 0
    # Only the weak section (skills) is re-run; the others are tailored once.
    assert stub.count(TailoredSkills) == 2
    assert stub.count(TailoredSummary) == 1
    assert stub.count(TailoredWork) == 1
    assert stub.count(TailoredProjects) == 1
    # Two scoring passes (initial + re-score).
    assert stub.count(MatchReport) == 2

    skills_calls = stub.calls_for(TailoredSkills)
    # First attempt carries no revision feedback ...
    assert "Revision feedback" not in skills_calls[0]["user"]
    # ... the re-run does, and names the coverage gap (missing must-have).
    assert "Revision feedback" in skills_calls[1]["user"]
    assert "Kubernetes" in skills_calls[1]["user"]

    assert (out / "tailored.json").is_file()
    render_mock.assert_called_once()


def test_no_rerun_when_first_pass_meets_threshold(monkeypatch, tmp_path):
    out = tmp_path / "out"
    _, stub, _, _ = _run(monkeypatch, out, [_good_report()], no_pdf=True)
    # No section is tailored more than once.
    for model in (TailoredSummary, TailoredSkills, TailoredWork, TailoredProjects):
        assert stub.count(model) == 1


def test_rerun_capped_by_max_passes(monkeypatch, tmp_path):
    # Coverage stays low; with max_passes=2 exactly one re-run pass happens.
    out = tmp_path / "out"
    rc, stub, _, _ = _run(
        monkeypatch, out, [_low_report(), _low_report()], no_pdf=True, max_passes=2
    )
    assert rc == 0  # low coverage alone is not fatal (only truth violations are)
    assert stub.count(TailoredSkills) == 2  # re-run once, then stop
    assert stub.count(MatchReport) == 2


# ---------------------------------------------------------------------------
# Truth floor
# ---------------------------------------------------------------------------


def test_truth_violation_blocks_render_and_exits_nonzero(monkeypatch, tmp_path):
    out = tmp_path / "out"
    # Every score reports the same unresolved violation in "work".
    rc, stub, render_mock, fit_mock = _run(
        monkeypatch,
        out,
        [_violation_report(), _violation_report()],
        no_pdf=True,
        max_passes=2,
    )

    assert rc == 1
    # The offending section was re-run once with the violation named ...
    assert stub.count(TailoredWork) == 2
    work_rerun = stub.calls_for(TailoredWork)[1]["user"]
    assert "Led a team of 8 engineers" in work_rerun
    # ... but the violation persisted, so nothing was rendered.
    render_mock.assert_not_called()
    fit_mock.assert_not_called()
    assert not (out / "tailored.json").exists()
    assert not (out / "resume.tex").exists()
    # A diagnostic report is still written.
    assert (out / "match_report.json").is_file()


# ---------------------------------------------------------------------------
# Education passthrough
# ---------------------------------------------------------------------------


def test_education_passthrough_byte_identical(monkeypatch, tmp_path):
    out = tmp_path / "out"
    _run(monkeypatch, out, [_good_report()], no_pdf=True)
    tailored = json.loads((out / "tailored.json").read_text())
    assert tailored["education"] == MASTER["education"]


# ---------------------------------------------------------------------------
# Free-tier pacer
# ---------------------------------------------------------------------------


def test_pacer_sleeps_between_calls(monkeypatch, tmp_path):
    sleep_mock = MagicMock()
    monkeypatch.setattr(tailor.time, "sleep", sleep_mock)

    out = tmp_path / "out"
    _run(monkeypatch, out, [_good_report()], no_pdf=True, call_interval=4.5)

    # 6 LLM calls -> the first is free, the other 5 are spaced by a sleep.
    assert sleep_mock.call_count == 5
    for call in sleep_mock.call_args_list:
        assert call.args[0] == pytest.approx(4.5, abs=0.5)


def test_pacer_disabled_when_interval_zero(monkeypatch, tmp_path):
    sleep_mock = MagicMock()
    monkeypatch.setattr(tailor.time, "sleep", sleep_mock)

    out = tmp_path / "out"
    _run(monkeypatch, out, [_good_report()], no_pdf=True, call_interval=0.0)

    sleep_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Batch mode
# ---------------------------------------------------------------------------


def _write_batch_fixture(tmp_path, jd_texts):
    master_path = tmp_path / "master.json"
    master_path.write_text(json.dumps(MASTER), encoding="utf-8")
    jd_dir = tmp_path / "jds"
    jd_dir.mkdir()
    for name, text in jd_texts.items():
        (jd_dir / f"{name}.txt").write_text(text, encoding="utf-8")
    return master_path, jd_dir, tmp_path / "output"


def _batch_argv(master_path, jd_dir, out_dir, *extra):
    return [
        "batch",
        "--master",
        str(master_path),
        "--jd-dir",
        str(jd_dir),
        "--out-dir",
        str(out_dir),
        "--no-pdf",
        "--call-interval",
        "0",
        *extra,
    ]


def test_batch_three_jds_three_dirs(monkeypatch, tmp_path):
    master_path, jd_dir, out_dir = _write_batch_fixture(
        tmp_path,
        {"01": "JD one Python", "02": "JD two Python", "03": "JD three Python"},
    )
    stub = LLMStub([_good_report()])
    monkeypatch.setattr(tailor, "call_llm_with_retry", stub)
    monkeypatch.setattr(tailor, "_render_resume", MagicMock())

    rc = tailor.main(_batch_argv(master_path, jd_dir, out_dir))

    assert rc == 0
    for stem in ("01", "02", "03"):
        d = out_dir / stem
        assert (d / "tailored.json").is_file()
        assert (d / "match_report.json").is_file()
        assert (d / ".done").is_file()


def test_batch_rerun_skips_done(monkeypatch, tmp_path):
    master_path, jd_dir, out_dir = _write_batch_fixture(
        tmp_path, {"01": "JD one", "02": "JD two"}
    )
    monkeypatch.setattr(tailor, "_render_resume", MagicMock())

    first = LLMStub([_good_report()])
    monkeypatch.setattr(tailor, "call_llm_with_retry", first)
    assert tailor.main(_batch_argv(master_path, jd_dir, out_dir)) == 0
    assert len(first.calls) > 0

    # Second run: every JD has a .done marker, so no LLM calls happen.
    second = LLMStub([_good_report()])
    monkeypatch.setattr(tailor, "call_llm_with_retry", second)
    assert tailor.main(_batch_argv(master_path, jd_dir, out_dir)) == 0
    assert second.calls == []


def test_batch_force_reprocesses(monkeypatch, tmp_path):
    master_path, jd_dir, out_dir = _write_batch_fixture(tmp_path, {"01": "JD one"})
    monkeypatch.setattr(tailor, "_render_resume", MagicMock())

    first = LLMStub([_good_report()])
    monkeypatch.setattr(tailor, "call_llm_with_retry", first)
    tailor.main(_batch_argv(master_path, jd_dir, out_dir))

    forced = LLMStub([_good_report()])
    monkeypatch.setattr(tailor, "call_llm_with_retry", forced)
    assert tailor.main(_batch_argv(master_path, jd_dir, out_dir, "--force")) == 0
    assert len(forced.calls) > 0  # reprocessed despite the .done marker


def test_batch_mid_batch_resource_exhausted_exits_75(monkeypatch, tmp_path, capsys):
    master_path, jd_dir, out_dir = _write_batch_fixture(
        tmp_path,
        {"01": "First JD text", "02": "MARK_TWO second JD", "03": "Third JD text"},
    )
    # Quota dies while parsing JD 02.
    stub = LLMStub([_good_report()], raise_resource_on="MARK_TWO")
    monkeypatch.setattr(tailor, "call_llm_with_retry", stub)
    monkeypatch.setattr(tailor, "_render_resume", MagicMock())

    rc = tailor.main(_batch_argv(master_path, jd_dir, out_dir))

    assert rc == 75  # EX_TEMPFAIL
    assert (out_dir / "01" / ".done").is_file()  # completed before the failure
    assert not (out_dir / "02" / ".done").exists()  # died mid-JD
    assert not (out_dir / "03" / ".done").exists()  # never reached

    err = capsys.readouterr().err
    assert "wait and re-run" in err
    assert "01" in err  # completed list
    assert "02" in err and "03" in err  # remaining list
