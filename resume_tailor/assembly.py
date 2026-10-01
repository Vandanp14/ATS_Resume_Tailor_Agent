"""Resume assembly, review-edit, and reporting facade."""

from pipeline_core import (
    PipelineComponents,
    apply_review_edits,
    assemble_scored,
    cross_entry_attributions,
    inferred_metrics,
    partition_review_truth_violations,
    scan_bullet_style,
    scan_metric_quality,
    scan_unsupported_technology,
    transferable_skill_injections,
    waive_cross_entry_objections,
)

__all__ = [
    "PipelineComponents",
    "apply_review_edits",
    "assemble_scored",
    "cross_entry_attributions",
    "inferred_metrics",
    "partition_review_truth_violations",
    "scan_bullet_style",
    "scan_metric_quality",
    "scan_unsupported_technology",
    "transferable_skill_injections",
    "waive_cross_entry_objections",
]
