"""Validate comparison-group structure and semantic connectivity."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .models import validate_group_record


DECISIONS = {"keep", "split", "merge", "retire_content", "repurpose"}
REVIEWED_CONTRAST_FIELDS = (
    "shared_basis",
    "axis",
    "left_landing",
    "right_landing",
)


def comparison_edge_subject_id(group: dict, edge: dict) -> str:
    group_id = str(group.get("group_id") or "").strip()
    left = str(edge.get("left") or "").strip()
    right = str(edge.get("right") or "").strip()
    if not group_id or not left or not right:
        return ""
    return f"{group_id}:{left}:{right}"


def has_reviewed_contrast_contract(edge: dict) -> bool:
    if not isinstance(edge, dict):
        return False
    if any(
        not isinstance(edge.get(field), str) or not edge[field].strip()
        for field in REVIEWED_CONTRAST_FIELDS
    ):
        return False
    evidence_ids = edge.get("evidence_ids")
    if not isinstance(evidence_ids, list) or not evidence_ids:
        return False
    if any(
        not isinstance(evidence_id, str) or not evidence_id.strip()
        for evidence_id in evidence_ids
    ):
        return False
    return edge.get("review_status") == "pass"


def audit_group_overlaps(groups: list[dict]) -> list[dict]:
    overlaps: list[dict] = []
    for index, left in enumerate(groups):
        left_members = set(left.get("members", []))
        for right in groups[index + 1 :]:
            right_members = set(right.get("members", []))
            shared = left_members & right_members
            if not shared:
                continue
            if left_members == right_members:
                overlap_type = "exact"
            elif left_members < right_members or right_members < left_members:
                overlap_type = "subset"
            else:
                overlap_type = "partial"
            overlaps.append(
                {
                    "left_group_id": left["group_id"],
                    "right_group_id": right["group_id"],
                    "type": overlap_type,
                    "shared_members": sorted(shared),
                }
            )
    return overlaps


def _edge_targets(record: dict) -> set[str]:
    return {
        str(edge.get("other_term") or "")
        for edge in record.get("comparison_edges", [])
        if str(edge.get("other_term") or "")
    }


def validate_group_semantics(group: dict, records: dict[str, dict]) -> list[str]:
    errors = validate_group_record(group, records)
    group_id = str(group.get("group_id") or "")
    members = list(group.get("members", []))
    decision = str(group.get("decision") or "")
    if decision not in DECISIONS:
        errors.append(f"unknown group decision: {decision}")

    known_members = [member for member in members if member in records]
    expected_order = sorted(
        known_members,
        key=lambda term: (records[term].get("registry_order", 10**9), term),
    )
    if known_members != expected_order:
        errors.append(f"unstable member order: {group_id}")

    if group.get("status") != "ready":
        return errors

    if len(members) > 6:
        errors.append(f"comparison group exceeds learning limit: {group_id} {len(members)}")

    for member in known_members:
        record = records[member]
        if not str(record.get("meaning") or "").strip():
            errors.append(f"group member missing meaning: {member}")
        if not str(record.get("distinctive_feature") or "").strip():
            errors.append(f"group member missing distinctive feature: {member}")

    member_set = set(known_members)
    neighbors: dict[str, set[str]] = {member: set() for member in known_members}
    seen_pairs: set[tuple[str, str]] = set()
    for difference in group.get("minimum_differences", []):
        left = str(difference.get("left") or "")
        right = str(difference.get("right") or "")
        text = str(difference.get("text") or "").strip()
        if left not in member_set or right not in member_set:
            errors.append(f"minimum difference references nonmember: {group_id} {left} {right}")
            continue
        pair = tuple(sorted((left, right)))
        if pair in seen_pairs:
            errors.append(f"duplicate minimum difference: {group_id} {left} {right}")
        seen_pairs.add(pair)
        if not text:
            errors.append(f"empty minimum difference: {group_id} {left} {right}")
        neighbors[left].add(right)
        neighbors[right].add(left)
    if known_members:
        reached = {known_members[0]}
        pending = [known_members[0]]
        while pending:
            pending.extend(sorted(neighbors[pending.pop()] - reached))
            reached.update(pending)
        missing = [member for member in known_members if member not in reached]
        if missing:
            errors.append(
                f"disconnected minimum-difference graph: {group_id} {'、'.join(missing)}"
            )
    return errors


def validate_group_registry(groups: list[dict], records: dict[str, dict]) -> list[str]:
    errors: list[str] = []
    group_ids = [str(group.get("group_id") or "") for group in groups]
    for group_id in sorted(set(group_ids)):
        if group_id and group_ids.count(group_id) > 1:
            errors.append(f"duplicate group_id: {group_id}")
    for group in groups:
        errors.extend(validate_group_semantics(group, records))
    by_id = {group["group_id"]: group for group in groups}
    for overlap in audit_group_overlaps(groups):
        left_id = overlap["left_group_id"]
        right_id = overlap["right_group_id"]
        left_reasons = by_id[left_id].get("overlap_reasons", {})
        right_reasons = by_id[right_id].get("overlap_reasons", {})
        if not str(left_reasons.get(right_id) or right_reasons.get(left_id) or "").strip():
            errors.append(f"unexplained overlap: {left_id} {right_id}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", type=Path)
    args = parser.parse_args()
    if not args.validate:
        parser.error("--validate is required")
    payload = json.loads(args.validate.read_text(encoding="utf-8-sig"))
    records = {record["term"]: record for record in payload.get("records", [])}
    errors = validate_group_registry(payload.get("groups", []), records)
    if errors:
        for error in errors:
            print(error)
        return 1
    print(json.dumps(payload.get("totals", {}), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
