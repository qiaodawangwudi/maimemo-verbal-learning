"""Independent learning-value checks for semantic records and comparisons."""

from __future__ import annotations

import hashlib
import json
import re
from difflib import SequenceMatcher

from .groups import comparison_edge_subject_id, has_reviewed_contrast_contract


NEAR_DUPLICATE_ISSUE = "meaning and feature are near-duplicates"
RESOLUTION_DECISIONS = frozenset({"rewrite_required", "rewrite_not_required"})
_PLACEHOLDER_REASONS = frozenset(
    {
        "不同",
        "已经审查",
        "人工确认",
        "人工确认没有问题",
        "已经人工审查确认没有问题",
        "理由充分",
        "无需修改",
        "通过",
    }
)
_EQUIVALENT_PHRASES = (
    ("根基", "基础"),
    ("牢固", "基础"),
    ("巩固", "基础"),
)
_DISCOURSE_FILLERS = (
    "进一步",
    "已经",
    "得到",
    "原有",
    "既有",
    "同时",
    "并且",
    "并",
)


def _text(value: object) -> str:
    return str(value or "").strip()


def _strict_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def learning_review_hash(review: dict) -> str:
    """Hash review content while excluding its stored self-hash."""

    payload = {key: value for key, value in review.items() if key != "review_hash"}
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalize_for_flagging(value: object) -> str:
    normalized = _text(value).lower()
    for source, target in _EQUIVALENT_PHRASES:
        normalized = normalized.replace(source, target)
    for filler in _DISCOURSE_FILLERS:
        normalized = normalized.replace(filler, "")
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", normalized)


def _near_duplicate(left: object, right: object) -> bool:
    normalized_left = _normalize_for_flagging(left)
    normalized_right = _normalize_for_flagging(right)
    if min(len(normalized_left), len(normalized_right)) < 4:
        return False
    return SequenceMatcher(None, normalized_left, normalized_right).ratio() >= 0.8


def _is_repeated_text(value: str) -> bool:
    for width in range(1, len(value) // 2 + 1):
        if len(value) % width == 0 and value == value[:width] * (len(value) // width):
            return True
    return False


def _reason_is_specific(value: object) -> bool:
    reason = _strict_text(value)
    normalized = re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", reason.lower())
    return (
        len(normalized) >= 12
        and normalized not in _PLACEHOLDER_REASONS
        and not _is_repeated_text(normalized)
    )


def _resolution_schema_is_valid(resolution: dict) -> bool:
    decision = _strict_text(resolution.get("decision"))
    issue = _strict_text(resolution.get("issue"))
    base_valid = (
        bool(_strict_text(resolution.get("subject_id")))
        and bool(issue)
        and decision in RESOLUTION_DECISIONS
        and _reason_is_specific(resolution.get("reason"))
        and resolution.get("reviewer_context_isolated") is True
    )
    if issue == NEAR_DUPLICATE_ISSUE:
        return base_valid and decision == "rewrite_required"
    return base_valid


def validate_independent_review(independent_review: object) -> list[str]:
    """Validate the independent-review artifact itself, fail-closed."""

    if independent_review is None:
        return ["missing independent learning review"]
    if not isinstance(independent_review, dict):
        return ["independent learning review is incomplete"]

    errors: list[str] = []
    if independent_review.get("complete") is not True:
        errors.append("independent learning review is incomplete")
    resolutions = independent_review.get("resolutions")
    if not isinstance(resolutions, list) or any(
        not isinstance(resolution, dict) for resolution in resolutions or []
    ):
        errors.append("independent learning review is incomplete")
        resolutions = []
    if independent_review.get("reviewer_context_isolated") is not True or any(
        resolution.get("reviewer_context_isolated") is not True
        for resolution in resolutions
    ):
        errors.append("independent learning review is not context-isolated")
    if any(not _resolution_schema_is_valid(resolution) for resolution in resolutions):
        errors.append("independent learning review is incomplete")
    return list(dict.fromkeys(errors))


def evaluate_learning_quality(
    records: list[dict],
    groups: list[dict],
    independent_review: dict,
) -> list[str]:
    """Return content-level quality flags that human resolutions cannot waive."""

    errors: list[str] = []
    for record in records:
        if record.get("status") != "ready":
            continue
        if not _near_duplicate(
            record.get("meaning"), record.get("distinctive_feature")
        ):
            continue
        errors.append(f"{NEAR_DUPLICATE_ISSUE}: {_text(record.get('term'))}")

    for group in groups:
        if group.get("status") != "ready":
            continue
        for edge in group.get("minimum_differences", []) or []:
            if not has_reviewed_contrast_contract(edge):
                errors.append("comparison edge lacks reviewed contrast contract")
                continue
            if not comparison_edge_subject_id(group, edge):
                errors.append("comparison edge lacks reviewed contrast contract")

    return list(dict.fromkeys(errors))
