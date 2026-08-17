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
_CONTRAST_CONNECTORS = (
    "而",
    "但",
    "区别",
    "不同",
    "相比",
    "前者",
    "后者",
    "分别",
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


def _normalized_statement(value: object) -> str:
    return re.sub(
        r"[^0-9a-z\u4e00-\u9fff]", "", _strict_text(value).lower()
    )


def _observation_is_specific(value: object) -> bool:
    normalized = _normalized_statement(value)
    return (
        len(normalized) >= 6
        and len(set(normalized)) >= 4
        and normalized not in _PLACEHOLDER_REASONS
        and not _is_repeated_text(normalized)
    )


def _reason_links_observations(
    reason: object,
    meaning_observation: object,
    feature_observation: object,
) -> bool:
    normalized_reason = _normalized_statement(reason)
    normalized_meaning = _normalized_statement(meaning_observation)
    normalized_feature = _normalized_statement(feature_observation)
    if not normalized_meaning or not normalized_feature:
        return False
    if (
        normalized_meaning not in normalized_reason
        or normalized_feature not in normalized_reason
    ):
        return False
    remainder = normalized_reason.replace(normalized_meaning, "", 1).replace(
        normalized_feature, "", 1
    )
    return len(remainder) >= 6 and any(
        connector in remainder for connector in _CONTRAST_CONNECTORS
    )


def _observation_is_grounded(observation: object, source_text: object) -> bool:
    normalized_observation = _normalized_statement(observation)
    normalized_source = _normalized_statement(source_text)
    if not normalized_observation or not normalized_source:
        return False
    matcher = SequenceMatcher(None, normalized_observation, normalized_source)
    longest_match = max(block.size for block in matcher.get_matching_blocks())
    return matcher.ratio() >= 0.45 and longest_match >= 4


def _resolution_schema_is_valid(resolution: dict) -> bool:
    decision = _strict_text(resolution.get("decision"))
    base_valid = (
        bool(_strict_text(resolution.get("subject_id")))
        and bool(_strict_text(resolution.get("issue")))
        and decision in RESOLUTION_DECISIONS
        and _reason_is_specific(resolution.get("reason"))
        and resolution.get("reviewer_context_isolated") is True
    )
    if not base_valid or decision == "rewrite_required":
        return base_valid

    meaning_observation = resolution.get("meaning_observation")
    feature_observation = resolution.get("feature_observation")
    normalized_meaning = _normalized_statement(meaning_observation)
    normalized_feature = _normalized_statement(feature_observation)
    return (
        _observation_is_specific(meaning_observation)
        and _observation_is_specific(feature_observation)
        and normalized_meaning != normalized_feature
        and SequenceMatcher(None, normalized_meaning, normalized_feature).ratio() < 0.9
        and _reason_links_observations(
            resolution.get("reason"),
            meaning_observation,
            feature_observation,
        )
    )


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


def _resolution_is_valid(
    resolution: dict,
    *,
    subject_id: str,
    issue: str,
    meaning: object,
    feature: object,
) -> bool:
    return (
        _resolution_schema_is_valid(resolution)
        and _strict_text(resolution.get("subject_id")) == subject_id
        and _strict_text(resolution.get("issue")) == issue
        and _strict_text(resolution.get("decision")) == "rewrite_not_required"
        and _observation_is_grounded(
            resolution.get("meaning_observation"), meaning
        )
        and _observation_is_grounded(
            resolution.get("feature_observation"), feature
        )
    )


def evaluate_learning_quality(
    records: list[dict],
    groups: list[dict],
    independent_review: dict,
) -> list[str]:
    """Return unresolved learning-quality flags; never infer semantic approval."""

    errors: list[str] = []
    raw_resolutions = (
        independent_review.get("resolutions")
        if isinstance(independent_review, dict)
        else None
    )
    resolutions = raw_resolutions if isinstance(raw_resolutions, list) else []
    for record in records:
        if record.get("status") != "ready":
            continue
        if not _near_duplicate(
            record.get("meaning"), record.get("distinctive_feature")
        ):
            continue
        subject_id = _text(record.get("sense_id")) or _text(record.get("term"))
        resolved = any(
            isinstance(resolution, dict)
            and _resolution_is_valid(
                resolution,
                subject_id=subject_id,
                issue=NEAR_DUPLICATE_ISSUE,
                meaning=record.get("meaning"),
                feature=record.get("distinctive_feature"),
            )
            for resolution in resolutions
        )
        if not resolved:
            errors.append(
                f"{NEAR_DUPLICATE_ISSUE}: {_text(record.get('term'))}"
            )

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
