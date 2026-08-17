"""Independent learning-value checks for semantic records and comparisons."""

from __future__ import annotations

import hashlib
import json
import re
from difflib import SequenceMatcher

from .groups import comparison_edge_subject_id, has_reviewed_contrast_contract


NEAR_DUPLICATE_ISSUE = "meaning and feature are near-duplicates"
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


def _resolution_is_valid(
    resolution: dict,
    *,
    subject_id: str,
    issue: str,
) -> bool:
    return (
        _text(resolution.get("subject_id")) == subject_id
        and _text(resolution.get("issue")) == issue
        and bool(_text(resolution.get("decision")))
        and len(_text(resolution.get("reason"))) >= 12
        and resolution.get("reviewer_context_isolated") is True
    )


def evaluate_learning_quality(
    records: list[dict],
    groups: list[dict],
    independent_review: dict,
) -> list[str]:
    """Return unresolved learning-quality flags; never infer semantic approval."""

    errors: list[str] = []
    resolutions = (
        independent_review.get("resolutions", [])
        if isinstance(independent_review, dict)
        else []
    )
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
