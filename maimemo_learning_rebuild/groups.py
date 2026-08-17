"""Validate comparison-group structure and semantic connectivity."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .models import validate_group_record


DECISIONS = {"keep", "split", "merge", "retire_content", "repurpose"}


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

    for member in known_members:
        record = records[member]
        if not str(record.get("meaning") or "").strip():
            errors.append(f"group member missing meaning: {member}")
        if not str(record.get("distinctive_feature") or "").strip():
            errors.append(f"group member missing distinctive feature: {member}")

    member_set = set(known_members)
    reciprocal_neighbors: dict[str, set[str]] = {member: set() for member in known_members}
    for member in known_members:
        targets = _edge_targets(records[member]) & member_set
        for target in targets:
            if member not in _edge_targets(records[target]):
                errors.append(f"missing reciprocal edge: {member} -> {target}")
            else:
                reciprocal_neighbors[member].add(target)
                reciprocal_neighbors[target].add(member)

    if len(members) > 6:
        for member in known_members:
            if not reciprocal_neighbors[member]:
                errors.append(f"mega group has unconnected member: {member}")
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
