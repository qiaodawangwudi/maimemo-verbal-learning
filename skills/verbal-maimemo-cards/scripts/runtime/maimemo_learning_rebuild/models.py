"""Validation rules shared by every rebuild stage."""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable


STATUSES = {"pending", "ready", "conflict", "retired"}
ACTIONS = {"unchanged", "update", "manual-review", "create", "repurpose"}
AMBIGUOUS_REFERENCES = ("前者", "后者", "两者", "二者", "它俩", "他俩")
READY_FIELDS = (
    "term",
    "sense_id",
    "source_kind",
    "meaning",
    "distinctive_feature",
    "dimensions",
    "comparison_edges",
    "evidence",
)


def _text(value: object) -> str:
    return str(value or "").strip()


def _normalized_learning_text(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", _text(value)).lower()


def _ambiguous_errors(values: Iterable[object]) -> list[str]:
    combined = "\n".join(_text(value) for value in values)
    return [
        f"ambiguous reference: {word}"
        for word in AMBIGUOUS_REFERENCES
        if word in combined
    ]


def validate_semantic_record(record: dict) -> list[str]:
    errors: list[str] = []
    status = _text(record.get("status"))
    if status not in STATUSES:
        errors.append(f"unknown status: {status}")
        return errors

    for field in ("term", "sense_id", "source_kind"):
        if not _text(record.get(field)):
            errors.append(f"missing field: {field}")

    if status != "ready":
        return errors

    for field in READY_FIELDS:
        value = record.get(field)
        if field in {"dimensions", "comparison_edges", "evidence"}:
            if value is None:
                errors.append(f"missing field: {field}")
        elif not _text(value):
            errors.append(f"missing field: {field}")

    meaning = _text(record.get("meaning"))
    feature = _text(record.get("distinctive_feature"))
    boundary = _text(record.get("misuse_boundary"))
    core = _text(record.get("core_discrimination"))
    if core:
        slots = [slot.strip() for slot in core.split("+")]
        if len(slots) < 2 or any(not slot for slot in slots):
            errors.append("core_discrimination requires keyword slots joined by +")
        normalized_core = _normalized_learning_text(core)
        for cue in record.get("recognition_cues") or []:
            normalized_cue = _normalized_learning_text(cue)
            if normalized_cue and normalized_cue == normalized_core:
                errors.append("recognition cue repeats core_discrimination")
                break
    if meaning and meaning == feature:
        errors.append("meaning equals distinctive_feature")
    if meaning and meaning == boundary:
        errors.append("meaning equals misuse_boundary")
    if feature and feature == boundary:
        errors.append("distinctive_feature equals misuse_boundary")

    evidence = record.get("evidence") or []
    if record.get("source_kind") == "teacher_transcript" and not evidence:
        errors.append("teacher_transcript record requires evidence")

    learner_values: list[object] = [meaning, feature, boundary]
    learner_values.extend(
        dimension.get("judgment", "")
        for dimension in record.get("dimensions") or []
        if isinstance(dimension, dict)
    )
    learner_values.extend(
        edge.get("minimum_difference", "")
        for edge in record.get("comparison_edges") or []
        if isinstance(edge, dict)
    )
    errors.extend(_ambiguous_errors(learner_values))
    return errors


def validate_group_record(group: dict, terms: Iterable[str]) -> list[str]:
    errors: list[str] = []
    known = set(terms)
    members = list(group.get("members") or [])
    counts = Counter(members)
    for member, count in counts.items():
        if count > 1:
            errors.append(f"duplicate group member: {member}")
    for member in dict.fromkeys(members):
        if member not in known:
            errors.append(f"unknown group member: {member}")
    if len(members) < 2:
        errors.append("comparison group requires at least two members")
    if not _text(group.get("group_id")):
        errors.append("missing field: group_id")
    if not _text(group.get("purpose")):
        errors.append("missing field: purpose")
    status = _text(group.get("status"))
    if status not in STATUSES:
        errors.append(f"unknown status: {status}")
    return errors


def validate_action_record(action: dict) -> list[str]:
    errors: list[str] = []
    value = _text(action.get("action"))
    if value not in ACTIONS:
        errors.append(f"unknown action: {value}")
        return errors
    for field in ("title", "content_hash", "reason"):
        if not _text(action.get(field)):
            errors.append(f"missing field: {field}")
    if value in {"update", "repurpose"} and not _text(action.get("card_id")):
        errors.append(f"{value} requires card_id")
    if value == "create" and action.get("card_id"):
        errors.append("create must not contain card_id")
    return errors
