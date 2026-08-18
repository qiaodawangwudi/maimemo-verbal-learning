"""Apply complete human-reviewed semantic replacements without source-specific logic."""

from __future__ import annotations


REQUIRED_LEARNING_FIELDS = {
    "meaning",
    "distinctive_feature",
    "recognition_cues",
    "dimensions",
    "comparison_edges",
    "misuse_boundary",
}


def apply_reviewed_override(
    record: dict,
    override: dict,
    review_id: str,
    *,
    provenance: dict | None = None,
) -> dict:
    """Promote only a complete replacement explicitly marked ready."""
    if override.get("status") != "ready":
        blocker = override.get("review_blocker")
        if blocker and blocker not in record.setdefault("review_blockers", []):
            record["review_blockers"].append(blocker)
        return record

    missing = sorted(
        field
        for field in REQUIRED_LEARNING_FIELDS
        if field not in override or override[field] in (None, "")
    )
    if missing:
        blocker = "人工覆盖缺少完整学习字段"
        if blocker not in record.setdefault("review_blockers", []):
            record["review_blockers"].append(blocker)
        return record

    record.update({field: override[field] for field in REQUIRED_LEARNING_FIELDS})
    for optional in ("source_kind", "evidence"):
        if optional in override:
            record[optional] = override[optional]
    record["status"] = "ready"
    record["typical_contexts"] = override.get("typical_contexts", [])
    record.pop("candidate", None)
    record.pop("review_blockers", None)
    record_provenance = record.setdefault("provenance", {})
    record_provenance.pop("derived_content_quarantined", None)
    record_provenance["manual_semantic_review"] = review_id
    if provenance:
        record_provenance.update(provenance)
    return record
