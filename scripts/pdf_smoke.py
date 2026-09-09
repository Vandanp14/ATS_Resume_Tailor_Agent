"""Compile the real template during image construction, warming its TeX cache."""

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import JSONResume
from render import render

with TemporaryDirectory(prefix="resume-pdf-smoke-") as directory:
    master = JSONResume.model_validate_json(
        Path("examples/master.example.json").read_text()
    )
    render(master, Path(directory), compile_pdf=True)
    if not (Path(directory) / "resume.pdf").is_file():
        raise SystemExit("PDF smoke check did not produce a resume.")
