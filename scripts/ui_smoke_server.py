"""Serve the web UI against a fake pipeline for browser smoke tests.

No Gemini calls are made. Everything lives in a throwaway folder (a temp dir,
or the path given as the first argument): a seeded old command-line folder and
two finished jobs, so History, the done screen, and the delete flow all have
something to show.

    .venv/bin/python scripts/ui_smoke_server.py [data-dir]

Then open http://127.0.0.1:8765 and follow scripts/ui_smoke.md.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import uvicorn  # noqa: E402

from resume_tailor.progress import Stage  # noqa: E402
from resume_tailor.web.app import webapp_factory  # noqa: E402
from tests.conftest import FakePipe  # noqa: E402

HOST, PORT = "127.0.0.1", 8765

# A sample match report so the done screen shows a percentage and an amber note.
REPORT = {
    "coverage_pct": 80,
    "keyword_coverage": {"computed_coverage_pct": 55.6, "missing_supported_terms": []},
    "qualification_coverage": [
        {
            "text": "Strong understanding of Section 508/ADA Accessibility compliance.",
            "type": "technical",
            "required": True,
            "status": "unsupported",
            "reason": "not in your resume: Section 508, ADA (tick it in the skill check if you know it)",
        }
    ],
}

SEED_JOBS = [
    ("HCLTech", "Full Stack Engineer", "HCLTech is hiring an Associate Full Stack Developer: React.js, Core Java, Spring Boot, AWS."),
    ("Whatnot", "Software Engineer", "Whatnot is hiring a Software Engineer to build live-stream features with React and Python."),
]


def _sample_pdf() -> bytes | None:
    """Newest real resume PDF on this machine, so the preview renders; else None."""
    pdfs = sorted((REPO / "resumepdfs").glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    return pdfs[0].read_bytes() if pdfs else None


SAMPLE_PDF = _sample_pdf()


# The stages a plain run reports, in order; research and the conditional
# fit/review stages are left out, as in a default run.
SMOKE_STAGES = [
    Stage.PREFLIGHT, Stage.PARSE_JD, Stage.MAP_REQUIREMENTS, Stage.SELECT_WORK,
    Stage.SELECT_PROJECTS, Stage.PLAN_EVIDENCE, Stage.TAILOR_SKILLS, Stage.REWRITE_WORK,
    Stage.REWRITE_PROJECTS, Stage.ASSEMBLE, Stage.HOLISTIC_REVIEW, Stage.VALIDATE_REVIEW,
    Stage.WRITE_SUMMARY, Stage.RENDER, Stage.WRITE_ARTIFACTS,
]
STAGE_SECONDS = 0.6


class SmokePipe(FakePipe):
    skill_chips = ("Figma", "Adobe XD", "Siteimprove")

    def run(self, master, jd_text, out_dir, no_pdf, job, resume=False):
        self.tracker.job = job
        for stage in SMOKE_STAGES:
            with self.tracker.stage(stage):
                if stage is Stage.SELECT_WORK:
                    # Held longer so the plain "backup model" note can be seen.
                    self.tracker.warn("gemini-3-flash unavailable (503); falling back to gemini-3.1-flash-lite")
                    time.sleep(STAGE_SECONDS * 5)
                time.sleep(STAGE_SECONDS)
        (out_dir / "tailored.json").write_text(json.dumps({"basics": {"name": "UI Test"}}), encoding="utf-8")
        if not no_pdf:
            (out_dir / "resume.pdf").write_bytes(SAMPLE_PDF or b"%PDF-1.4 fake")
        (out_dir / "match_report.json").write_text(json.dumps(REPORT), encoding="utf-8")
        (out_dir / ".done").write_text(json.dumps({"no_pdf": no_pdf}), encoding="utf-8")
        return 0


def _seed(root: Path) -> None:
    (root / "master.json").write_text(
        json.dumps({"basics": {"name": "UI Test", "email": "ui@example.com"}, "skills": [{"name": "Languages", "keywords": ["Python"]}]}),
        encoding="utf-8",
    )
    legacy = root / "output" / "product_swe_disney"
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / "tailored.json").write_text("{}", encoding="utf-8")


def _enqueue_seed_jobs() -> None:
    url = f"http://{HOST}:{PORT}/api/jobs"
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://{HOST}:{PORT}/", timeout=1)
            break
        except OSError:
            time.sleep(0.2)
    for company, role, jd_text in SEED_JOBS:
        body = json.dumps({"company": company, "role": role, "jd_text": jd_text, "no_pdf": SAMPLE_PDF is None}).encode()
        request = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json", "Idempotency-Key": str(uuid.uuid4())},
        )
        urllib.request.urlopen(request, timeout=5)


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="ui-smoke-"))
    root.mkdir(parents=True, exist_ok=True)
    _seed(root)
    app = webapp_factory(
        master_path=root / "master.json",
        output_dir=root / "output",
        pdf_dir=root / "pdfs",
        state_dir=root / "state",
        pipeline_factory=SmokePipe,
        static_dir=REPO / "static",
        call_interval=0,
    )
    threading.Thread(target=_enqueue_seed_jobs, daemon=True).start()
    print(f"UI smoke server on http://{HOST}:{PORT} (data in {root})")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
