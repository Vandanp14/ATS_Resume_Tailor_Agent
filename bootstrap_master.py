#!/usr/bin/env python
"""One-time bootstrap: extract a master resume (JSON Resume) from a PDF.

This script is a thin bridge to the sibling *hiring-agent* project. It does
NOT copy any extraction code — it inserts the hiring-agent checkout onto
``sys.path`` and calls its ``PDFHandler.extract_json_from_pdf``, which runs
one LLM extraction call per resume section (~6 calls total).

Usage:
    python bootstrap_master.py resume.pdf [-o master.json] \
        [--hiring-agent-path ~/Desktop/hackerank_ats/hiring-agent]

IMPORTANT — which Python to run this with:
    The hiring-agent's own dependencies (pymupdf, pymupdf4llm,
    google-genai, ...) must be importable by the interpreter running
    this script. The simplest reliable path is to run it with the
    hiring-agent's venv python:

        ~/Desktop/hackerank_ats/hiring-agent/.venv/bin/python \
            bootstrap_master.py resume.pdf -o master.json

    This repo's own .venv also works if `pip install -r requirements.txt`
    has been run here (the requirements overlap), but the hiring-agent venv
    is the documented, always-correct choice.

The hiring-agent reads its model + API key from its own ``.env`` (its
``prompt.py`` calls ``load_dotenv()`` relative to itself), so no extra
configuration is needed here. Note: if that ``.env`` has no
``GEMINI_API_KEY``, the hiring-agent silently falls back to Ollama, which
must then be installed and running locally.

Exit codes: 0 success, 1 extraction failed, 2 bad paths/arguments,
3 hiring-agent import failed (wrong path or missing dependencies).
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

DEFAULT_HIRING_AGENT_PATH = "~/Desktop/hackerank_ats/hiring-agent"


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract a master resume (JSON Resume format) from a PDF using "
            "the sibling hiring-agent project's LLM extraction pipeline."
        ),
        epilog=(
            "Tip: run this with the hiring-agent's venv python so its "
            "dependencies are importable, e.g. "
            f"{DEFAULT_HIRING_AGENT_PATH}/.venv/bin/python "
            "bootstrap_master.py resume.pdf"
        ),
    )
    parser.add_argument("pdf", help="Path to the resume PDF to extract")
    parser.add_argument(
        "-o",
        "--output",
        default="master.json",
        help="Where to write the extracted master resume (default: master.json)",
    )
    parser.add_argument(
        "--hiring-agent-path",
        default=DEFAULT_HIRING_AGENT_PATH,
        help=(
            "Path to the hiring-agent checkout whose PDFHandler does the "
            f"extraction (default: {DEFAULT_HIRING_AGENT_PATH})"
        ),
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    # Resolve to absolute paths up front: we chdir into the hiring-agent
    # checkout below (its TemplateManager loads prompts/templates/ relative
    # to the CURRENT WORKING DIRECTORY, verified against its source), so any
    # relative paths given on our command line must be pinned first.
    pdf_path = Path(args.pdf).expanduser().resolve()
    if not pdf_path.is_file():
        print(
            f"error: PDF not found: {pdf_path}\n"
            "Pass the path to an existing resume PDF, e.g. "
            "`python bootstrap_master.py ~/Documents/resume.pdf`.",
            file=sys.stderr,
        )
        return 2

    out_path = Path(args.output).expanduser().resolve()

    hiring_agent_dir = Path(args.hiring_agent_path).expanduser().resolve()
    if not (hiring_agent_dir / "pdf.py").is_file():
        print(
            f"error: hiring-agent checkout not found at: {hiring_agent_dir}\n"
            "Expected a directory containing pdf.py (the hiring-agent repo). "
            "Point --hiring-agent-path at your checkout, e.g.\n"
            "  python bootstrap_master.py resume.pdf "
            "--hiring-agent-path ~/src/hiring-agent",
            file=sys.stderr,
        )
        return 2

    # Insert the hiring-agent FIRST on sys.path. Both repos define modules
    # named models/llm_utils/prompt/prompts — position 0 guarantees pdf.py's
    # imports resolve to the hiring-agent's versions, not this repo's.
    sys.path.insert(0, str(hiring_agent_dir))

    # Also run FROM the hiring-agent directory: its TemplateManager opens
    # "prompts/templates/*.jinja" relative to the cwd, and running from this
    # repo would make it pick up OUR (different) templates and fail at LLM
    # call time. All user-supplied paths were resolved to absolute above.
    os.chdir(hiring_agent_dir)

    try:
        from pdf import PDFHandler  # noqa: E402 — path set up above
    except ImportError as exc:
        print(
            f"error: could not import the hiring-agent's PDF pipeline: {exc}\n\n"
            "This almost always means the current Python interpreter does not "
            "have the hiring-agent's dependencies installed (pymupdf, "
            "pymupdf4llm, google-genai, ...). Two fixes:\n"
            "  1. (simplest) Run this script with the hiring-agent's own venv:\n"
            f"       {hiring_agent_dir}/.venv/bin/python "
            "bootstrap_master.py " + str(pdf_path) + "\n"
            "  2. Install this repo's requirements into the venv you are "
            "using:\n"
            "       .venv/bin/pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 3

    # Surface the hiring-agent's own progress/error logging (it logs, and
    # returns None on failure rather than raising).
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    print(
        f"Extracting {pdf_path} via hiring-agent at {hiring_agent_dir} ...",
        flush=True,
    )
    print(
        "(one LLM call per resume section — this takes a minute or two)",
        flush=True,
    )

    handler = PDFHandler()
    resume = handler.extract_json_from_pdf(str(pdf_path))

    if resume is None:
        print(
            "error: extraction failed — the hiring-agent could not produce a "
            "valid resume from this PDF.\n"
            "Check the log output above for the failing section. Common "
            "causes: an image-only/scanned PDF (no extractable text), or the "
            "hiring-agent's .env missing a GEMINI_API_KEY (it then falls "
            "back to a local Ollama server). Re-run after fixing; the "
            "extraction is stateless.",
            file=sys.stderr,
        )
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(resume.model_dump(exclude_none=True), indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {out_path}")
    print(
        "Next: review it by hand — fix anything the extraction got wrong, "
        "then keep maintaining this file directly (see README, "
        "'Maintaining master.json')."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
