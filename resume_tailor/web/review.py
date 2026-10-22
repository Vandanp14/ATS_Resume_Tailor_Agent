"""Project stored analysis into a readable, revision-bound review."""

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    reviewed_ids: list[str] = Field(max_length=200)


def read_review(directory: Path) -> dict:
    path = directory / "match_report.json"
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError("The match report is not available yet.")
    raw = path.read_bytes()
    report = json.loads(raw)
    revision = hashlib.sha256(raw).hexdigest()
    source_facts = report.get("source_facts", {})
    if isinstance(source_facts, list):
        source_facts = {
            item.get("source_id"): item
            for item in source_facts
            if isinstance(item, dict) and item.get("source_id")
        }
    if not isinstance(source_facts, dict):
        source_facts = {}
    claims = []
    for field, label in (
        ("inferred_metrics", "Estimated metric"),
        ("cross_entry_attributions", "Evidence from another entry"),
    ):
        for index, item in enumerate(report.get(field, [])):
            claims.append(
                {
                    "id": f"{field}:{index}",
                    "kind": label,
                    "claim": item.get("final_claim")
                    or item.get("intended_accomplishment", ""),
                    "basis": item.get("inference_basis", ""),
                    "baseline": item.get("baseline", ""),
                    "destination": item.get("destination_work_id", ""),
                    "sources": [
                        source_facts
                        .get(source, {})
                        .get("text", source)
                        for source in item.get("source_fact_ids", [])
                    ],
                }
            )
    saved = directory / "review_decision.json"
    reviewed = []
    if saved.is_file() and not saved.is_symlink():
        try:
            decision = ReviewDecision.model_validate_json(saved.read_text())
            if decision.revision == revision:
                reviewed = decision.reviewed_ids
        except (ValueError, OSError):
            pass
    return {
        "revision": revision,
        "coverage_pct": report.get("coverage_pct"),
        "missing_must_haves": report.get("missing_must_haves", []),
        "weak_sections": report.get("weak_sections", []),
        "recommendations": report.get("recommendations", []),
        "truth_violations": report.get("truth_violations", []),
        "rejected_section_edits": report.get("rejected_section_edits", []),
        "notes": report.get("notes"),
        "qualification_coverage": report.get("qualification_coverage", []),
        "evidence_assignments": report.get("evidence_plan", {}).get("assignments", []),
        "claims": claims,
        "reviewed_ids": reviewed,
    }
