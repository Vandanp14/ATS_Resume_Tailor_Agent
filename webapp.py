#!/usr/bin/env python
"""Thin Uvicorn entrypoint for the local web app.

Usage:
    .venv/bin/python webapp.py [--master master.json] [--port 8000]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import uvicorn

from resume_tailor.config import DEFAULT_MODEL
from resume_tailor.runtime import DEFAULT_CALL_INTERVAL
from resume_tailor.web.app import webapp_factory
from resume_tailor.web.models import (
    DEFAULT_MAX_CALLS_PER_MINUTE,
    DEFAULT_MAX_INPUT_TOKENS_PER_MINUTE,
    DEFAULT_MAX_REQUESTS_PER_DAY,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="webapp.py",
        description="Local queue-enabled web app for tailoring a resume against pasted JDs.",
    )
    parser.add_argument("--master", type=Path, default=Path("master.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--pdf-dir", type=Path, default=Path("resumepdfs"))
    parser.add_argument("--state-dir", type=Path, default=Path(".resume-tailor"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--call-interval", type=float, default=DEFAULT_CALL_INTERVAL)
    parser.add_argument(
        "--max-calls-per-minute",
        type=int,
        default=DEFAULT_MAX_CALLS_PER_MINUTE,
        help="Rolling 60-second web-app Gemini request cap.",
    )
    parser.add_argument(
        "--max-input-tokens-per-minute",
        type=int,
        default=DEFAULT_MAX_INPUT_TOKENS_PER_MINUTE,
        help="Rolling 60-second observed Gemini input-token cap.",
    )
    parser.add_argument(
        "--max-requests-per-day",
        type=int,
        default=DEFAULT_MAX_REQUESTS_PER_DAY,
        help="Web-app Gemini request cap per Pacific-time day.",
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--verbose", action="store_true")
    return parser


def _validate(args: argparse.Namespace) -> None:
    if args.call_interval < 0:
        raise SystemExit("--call-interval must be non-negative.")
    if args.max_calls_per_minute < 1:
        raise SystemExit("--max-calls-per-minute must be positive.")
    if args.max_input_tokens_per_minute < 1:
        raise SystemExit("--max-input-tokens-per-minute must be positive.")
    if args.max_requests_per_day < 1:
        raise SystemExit("--max-requests-per-day must be positive.")
    for name in ("output_dir", "pdf_dir", "state_dir"):
        path = Path(getattr(args, name))
        if path.exists() and not path.is_dir():
            raise SystemExit(f"--{name.replace('_', '-')} must be a directory, not a file: {path}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    _validate(args)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        app = webapp_factory(
            master_path=args.master,
            output_dir=args.output_dir,
            pdf_dir=args.pdf_dir,
            state_dir=args.state_dir,
            model=args.model,
            call_interval=args.call_interval,
            max_calls_per_minute=args.max_calls_per_minute,
            max_input_tokens_per_minute=args.max_input_tokens_per_minute,
            max_requests_per_day=args.max_requests_per_day,
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
