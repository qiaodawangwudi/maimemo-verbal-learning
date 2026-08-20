"""Validate evidence-bound group dimension reviews before card rendering."""

from __future__ import annotations

import hashlib
import json
import re
import argparse
from pathlib import Path
from collections import Counter


_BANNED_AXES = {
    "选择落点",
    "落点",
    "核心辨析",
    "词义",
    "题干关键词",
    "一眼辨析",
    "怎么选",
}
_EVIDENCE_FIELDS = {
    "meaning",
    "recognition_cues",
    "misuse_boundary",
    "typical_contexts",
}


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _value_hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def dimension_review_hash(review: dict) -> str:
    payload = dict(review)
    payload.pop("review_hash", None)
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _normalized(text: object) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", str(text)).lower()


def _canonical_axis(axis: str) -> str:
    value = _normalized(axis)
    for noise in ("补充", "角度", "维度", "方面", "比较"):
        value = value.replace(noise, "")
    return value


def _judgment_skeleton(entry: dict) -> str:
    text = "".join(
        str(judgment)
        for dimension in entry.get("dimensions", [])
        for judgment in (dimension.get("judgments") or {}).values()
    )
    for member in entry.get("members", []):
        text = text.replace(str(member), "")
    text = text.replace(str(entry.get("group_id", "")), "")
    return re.sub(r"[0-9]+", "", _normalized(text))


def validate_dimension_review(
    groups: list[dict],
    records: dict[str, dict] | list[dict],
    review: dict,
) -> list[str]:
    """Return stable errors; never infer or repair a missing dimension."""

    errors: list[str] = []
    if not isinstance(review, dict):
        return ["dimension review must be an object"]
    if review.get("schema_version") != 1:
        errors.append("dimension review schema_version must be 1")
    if review.get("status") != "passed":
        errors.append("dimension review status must be passed")
    if review.get("review_mode") != "evidence_bound_group_review":
        errors.append("dimension review mode must be evidence_bound_group_review")
    if review.get("review_hash") != dimension_review_hash(review):
        errors.append("dimension review hash mismatch")

    if isinstance(records, list):
        by_term = {
            str(record.get("term")): record
            for record in records
            if isinstance(record, dict) and isinstance(record.get("term"), str)
        }
    elif isinstance(records, dict):
        by_term = records
    else:
        return errors + ["dimension review records must be a list or object"]

    expected = {
        str(group.get("group_id")): [str(term) for term in group.get("members", [])]
        for group in groups
        if isinstance(group, dict)
    }
    raw_entries = review.get("groups")
    if not isinstance(raw_entries, list):
        return errors + ["dimension review groups must be a list"]
    entries: dict[str, dict] = {}
    for raw in raw_entries:
        if not isinstance(raw, dict):
            errors.append("dimension review group entry must be an object")
            continue
        group_id = raw.get("group_id")
        if not isinstance(group_id, str) or not group_id:
            errors.append("dimension review group_id must be a nonempty string")
            continue
        if group_id in entries:
            errors.append(f"duplicate group disposition: {group_id}")
            continue
        entries[group_id] = raw
    for group_id in expected:
        if group_id not in entries:
            errors.append(f"missing group disposition: {group_id}")
    for group_id in entries:
        if group_id not in expected:
            errors.append(f"orphan group disposition: {group_id}")

    approved_entries: list[dict] = []
    for group_id, members in expected.items():
        entry = entries.get(group_id)
        if entry is None:
            continue
        if entry.get("members") != members:
            errors.append(f"dimension review members mismatch: {group_id}")
        disposition = entry.get("disposition")
        dimensions = entry.get("dimensions")
        checked_axes = entry.get("checked_candidate_axes")
        reason = entry.get("insufficiency_reason")
        if not isinstance(dimensions, list):
            errors.append(f"dimensions must be a list: {group_id}")
            continue
        if not isinstance(checked_axes, list) or len(checked_axes) < 2:
            errors.append(f"at least two candidate axes must be checked: {group_id}")
        if disposition == "insufficient_dimensions":
            if dimensions:
                errors.append(f"insufficient disposition cannot contain dimensions: {group_id}")
            if not isinstance(reason, str) or len(_normalized(reason)) < 12:
                errors.append(f"insufficiency reason is not reviewable: {group_id}")
            continue
        if disposition != "approved_dimensions":
            errors.append(f"unknown dimension disposition: {group_id}")
            continue
        approved_entries.append(entry)
        if reason not in ("", None):
            errors.append(f"approved dimensions cannot claim insufficiency: {group_id}")
        if not 2 <= len(dimensions) <= 5:
            errors.append(f"approved group requires two to five dimensions: {group_id}")
        semantic_axes: set[str] = set()
        for dimension in dimensions:
            if not isinstance(dimension, dict):
                errors.append(f"dimension must be an object: {group_id}")
                continue
            axis = dimension.get("axis")
            question = dimension.get("question")
            judgments = dimension.get("judgments")
            evidence = dimension.get("evidence")
            change = dimension.get("selection_change_test")
            independence = dimension.get("independence_reason")
            if not isinstance(axis, str) or not _canonical_axis(axis):
                errors.append(f"dimension axis must be nonempty: {group_id}")
                continue
            canonical_axis = _canonical_axis(axis)
            if canonical_axis in {_canonical_axis(value) for value in _BANNED_AXES}:
                errors.append(f"non-dimension axis: {group_id}:{axis}")
            if canonical_axis in semantic_axes:
                errors.append(f"duplicate semantic axis: {group_id}:{axis}")
            semantic_axes.add(canonical_axis)
            if not isinstance(question, str) or len(_normalized(question)) < 8:
                errors.append(f"dimension question is not concrete: {group_id}:{axis}")
            if not isinstance(independence, str) or len(_normalized(independence)) < 10:
                errors.append(f"dimension independence is not explained: {group_id}:{axis}")
            if not isinstance(judgments, dict) or set(judgments) != set(members):
                errors.append(f"dimension judgments must cover exact members: {group_id}:{axis}")
                judgments = {}
            if not isinstance(evidence, dict) or set(evidence) != set(members):
                errors.append(f"dimension evidence must cover exact members: {group_id}:{axis}")
                evidence = {}
            for term in members:
                judgment = judgments.get(term)
                if not isinstance(judgment, str) or term not in judgment:
                    errors.append(f"dimension judgment must name member: {group_id}:{axis}:{term}")
                    continue
                core = str(by_term.get(term, {}).get("core_discrimination", ""))
                normalized_judgment = _normalized(judgment)
                normalized_core = _normalized(core)
                if normalized_core and (
                    normalized_judgment == normalized_core
                    or normalized_judgment in normalized_core
                    or normalized_core in normalized_judgment
                ):
                    errors.append(f"dimension judgment copies core: {group_id}:{axis}:{term}")
                anchors = evidence.get(term)
                if not isinstance(anchors, list) or not anchors:
                    errors.append(f"dimension evidence is empty: {group_id}:{axis}:{term}")
                    continue
                for anchor in anchors:
                    if not isinstance(anchor, dict):
                        errors.append(f"dimension evidence anchor must be object: {group_id}:{axis}:{term}")
                        continue
                    field = anchor.get("field")
                    digest = anchor.get("value_hash")
                    excerpt = anchor.get("excerpt")
                    if field not in _EVIDENCE_FIELDS:
                        errors.append(f"unsupported dimension evidence field: {group_id}:{axis}:{term}")
                    elif digest != _value_hash(by_term.get(term, {}).get(field)):
                        errors.append(f"evidence hash mismatch: {group_id}:{axis}:{term}:{field}")
                    if not isinstance(excerpt, str) or len(_normalized(excerpt)) < 2:
                        errors.append(f"dimension evidence excerpt is empty: {group_id}:{axis}:{term}")
                    elif field in _EVIDENCE_FIELDS:
                        source_text = _normalized(
                            json.dumps(by_term.get(term, {}).get(field), ensure_ascii=False)
                        )
                        if _normalized(excerpt) not in source_text:
                            errors.append(
                                f"dimension evidence excerpt mismatch: {group_id}:{axis}:{term}:{field}"
                            )
            if not isinstance(change, dict) or set(change) != {
                "condition", "when_true", "when_false"
            }:
                errors.append(f"selection change test has wrong shape: {group_id}:{axis}")
            elif (
                not isinstance(change["condition"], str)
                or len(_normalized(change["condition"])) < 6
                or change["when_true"] not in members
                or change["when_false"] not in members
                or change["when_true"] == change["when_false"]
            ):
                errors.append(f"selection change test is not decisive: {group_id}:{axis}")

    if expected and not approved_entries:
        errors.append("blanket dimension deletion is forbidden")
    if len(approved_entries) >= 3:
        fingerprints = Counter()
        for entry in approved_entries:
            axes = tuple(sorted(_canonical_axis(item.get("axis", "")) for item in entry["dimensions"]))
            fingerprints[(axes, _judgment_skeleton(entry))] += 1
        count = max(fingerprints.values(), default=0)
        if count >= 3 and count / len(approved_entries) >= 0.5:
            errors.append("homogeneous dimension template dominates approved groups")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate an evidence-bound dimension review.")
    parser.add_argument("--groups", type=Path, required=True)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        groups = json.loads(args.groups.read_text(encoding="utf-8"))
        records = json.loads(args.records.read_text(encoding="utf-8"))
        review = json.loads(args.review.read_text(encoding="utf-8"))
        errors = validate_dimension_review(groups, records, review)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        errors = [f"dimension review input is invalid: {type(exc).__name__}"]
    print(json.dumps({"status": "passed" if not errors else "blocked", "errors": errors}, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
