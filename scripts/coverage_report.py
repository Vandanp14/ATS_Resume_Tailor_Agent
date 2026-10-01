"""Deterministic keyword-coverage regression report over generated outputs.

Walks an output tree, re-measures every ``tailored.json`` against the
requirement map stored in its ``match_report.json``, and prints one row per
job. No LLM calls, so it is free to run after every prompt change:

    .venv/bin/python scripts/coverage_report.py [--output-dir output] \
        [--min-supported 80]

Columns: computed coverage (all JD requirements, weighted), supported coverage
(only requirements the master states — the achievable ceiling), proxies placed
on the page vs. bridged, placement findings, and unresolved truth violations.
Exit status is 1 when any job falls below ``--min-supported``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keyword_coverage import placement_findings, resume_coverage  # noqa: E402


def _row(job_dir: Path) -> dict | None:
    report_path = job_dir / "match_report.json"
    tailored_path = job_dir / "tailored.json"
    if not (report_path.is_file() and tailored_path.is_file()):
        return None
    report = json.loads(report_path.read_text(encoding="utf-8"))
    requirements = report.get("requirement_map")
    if not requirements:
        return None
    tailored = json.loads(tailored_path.read_text(encoding="utf-8"))
    coverage = resume_coverage(tailored, requirements)
    proxied = [item for item in coverage["requirements"] if item["status"] == "proxy"]
    return {
        "job": job_dir.name,
        "computed": coverage["computed_coverage_pct"],
        "supported": coverage["supported_coverage_pct"],
        "proxies": f"{sum(item['proxy_on_page'] for item in proxied)}/{len(proxied)}",
        "placement": len(placement_findings(tailored, requirements)),
        "truth": len(report.get("truth_violations", [])),
        "missing": ", ".join(coverage["missing_supported_terms"][:4]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--min-supported", type=float, default=0.0)
    args = parser.parse_args(argv)

    rows = [
        row
        for job_dir in sorted(path for path in args.output_dir.iterdir() if path.is_dir())
        if (row := _row(job_dir)) is not None
    ]
    if not rows:
        print(f"No outputs with a requirement map under {args.output_dir}")
        return 0
    header = f"{'job':<40} {'computed':>8} {'supported':>9} {'proxies':>7} {'place':>5} {'truth':>5}  missing stated terms"
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['job'][:40]:<40} {row['computed']:>7.1f}% {row['supported']:>8.1f}% "
            f"{row['proxies']:>7} {row['placement']:>5} {row['truth']:>5}  {row['missing']}"
        )
    average = sum(row["supported"] for row in rows) / len(rows)
    print(f"\n{len(rows)} job(s); mean supported coverage {average:.1f}%")
    below = [row["job"] for row in rows if row["supported"] < args.min_supported]
    if below:
        print(f"Below --min-supported {args.min_supported}: {', '.join(below)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
