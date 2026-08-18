"""Whole-registry semantic quality review."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .learning_quality import evaluate_learning_quality, validate_independent_review
from .models import validate_semantic_record
from .sources import load_source_catalog, validate_evidence


GENERIC_WARNINGS = (
    "需结合题干逻辑对应点使用",
    "不把课堂高频用法当作固定语境",
)
SUSPICIOUS_EXACT = {
    "一些军队",
    "是什么意思啊",
    "社区北站北社区",
    "这个事儿",
    "点是什么",
}


def _review_registry(
    records: list[dict],
    catalog: dict,
    groups: list[dict],
    independent_review: object,
    *,
    require_independent_review: bool,
) -> dict:
    key_counts = Counter(
        (str(record.get("term") or ""), str(record.get("sense_id") or ""))
        for record in records
    )
    duplicate_keys = sum(count - 1 for count in key_counts.values() if count > 1)
    known_terms = {str(record.get("term") or "") for record in records}
    status_counts = Counter(str(record.get("status") or "") for record in records)
    details: list[dict] = []
    repeated_fields = 0
    generic_warnings = 0
    suspicious_fragments = 0
    broken_edges = 0
    missing_evidence = 0
    effective_ready = 0
    hard_errors = duplicate_keys

    for record in records:
        term = str(record.get("term") or "")
        errors = validate_semantic_record(record)
        if (
            record.get("status") == "ready"
            and (record.get("provenance") or {}).get("derived_content_quarantined")
        ):
            errors.append("quarantined derived content declared ready")
        if any("equals" in error for error in errors):
            repeated_fields += 1
        boundary = str(record.get("misuse_boundary") or "")
        if record.get("status") == "ready" and any(
            warning in boundary for warning in GENERIC_WARNINGS
        ):
            generic_warnings += 1
            errors.append("generic misuse boundary")
        meaning = str(record.get("meaning") or "").strip()
        if record.get("status") == "ready" and meaning in SUSPICIOUS_EXACT:
            suspicious_fragments += 1
            errors.append(f"suspicious spoken fragment: {meaning}")
        for edge in record.get("comparison_edges", []) or []:
            other = str(edge.get("other_term") or "")
            if other not in known_terms:
                broken_edges += 1
                errors.append(f"unknown comparison member: {other}")
        evidence = record.get("evidence", []) or []
        if record.get("status") == "ready" and record.get("source_kind") == "teacher_transcript":
            if not evidence:
                missing_evidence += 1
            for item in evidence:
                evidence_errors = validate_evidence(catalog, item)
                if evidence_errors:
                    missing_evidence += 1
                    errors.extend(evidence_errors)
        if record.get("status") == "ready" and not errors:
            effective_ready += 1
        if errors:
            hard_errors += len(errors)
            details.append({"term": term, "errors": errors})

    learning_quality_errors: list[str] = []
    if require_independent_review:
        learning_quality_errors.extend(validate_independent_review(independent_review))
        if isinstance(independent_review, dict):
            learning_quality_errors.extend(
                evaluate_learning_quality(records, groups, independent_review)
            )
    learning_quality_errors = list(dict.fromkeys(learning_quality_errors))
    hard_errors += len(learning_quality_errors)
    return {
        "records": len(records),
        "ready": effective_ready,
        "declared_ready": status_counts.get("ready", 0),
        "pending": status_counts.get("pending", 0),
        "conflict": status_counts.get("conflict", 0),
        "retired": status_counts.get("retired", 0),
        "duplicate_keys": duplicate_keys,
        "missing_evidence": missing_evidence,
        "broken_edges": broken_edges,
        "repeated_fields": repeated_fields,
        "generic_warnings": generic_warnings,
        "suspicious_fragments": suspicious_fragments,
        "hard_errors": hard_errors,
        "details": details,
        "learning_quality_errors": learning_quality_errors,
    }


def review_registry(
    records: list[dict],
    catalog: dict,
    groups: list[dict],
    independent_review: object = None,
) -> dict:
    """Run the complete review, including mandatory independent learning review."""

    return _review_registry(
        records,
        catalog,
        groups,
        independent_review,
        require_independent_review=True,
    )


def review_registry_precheck(
    records: list[dict], catalog: dict, groups: list[dict]
) -> dict:
    """Run only build-time semantic structure checks before independent review."""

    return _review_registry(
        records,
        catalog,
        groups,
        None,
        require_independent_review=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--groups", type=Path, required=True)
    parser.add_argument("--independent-review", type=Path)
    args = parser.parse_args()
    registry = json.loads(args.registry.read_text(encoding="utf-8-sig"))
    catalog = load_source_catalog(args.sources)
    group_payload = json.loads(args.groups.read_text(encoding="utf-8-sig"))
    independent_review = (
        json.loads(args.independent_review.read_text(encoding="utf-8-sig"))
        if args.independent_review
        else None
    )
    report = review_registry(
        registry.get("records", []),
        catalog,
        group_payload.get("groups", []),
        independent_review,
    )
    print(json.dumps({key: value for key, value in report.items() if key != "details"}, ensure_ascii=False, sort_keys=True))
    if report["hard_errors"]:
        for detail in report["details"]:
            print(json.dumps(detail, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
