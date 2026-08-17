"""Independent learning-value checks for semantic records and comparisons."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
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
_COPY_NGRAM_COVERAGE = ((1, 0.85), (2, 0.75), (3, 0.65))
EDGE_REVIEW_FIELDS = frozenset(
    {
        "subject_id",
        "contrast_axis",
        "left_focus",
        "right_focus",
        "question_selection_condition",
        "reviewer_context_isolated",
    }
)
EDGE_REVIEW_OBSERVATIONS = (
    ("contrast_axis", "axis"),
    ("left_focus", "left_landing"),
    ("right_focus", "right_landing"),
    ("question_selection_condition", "question_selection_condition"),
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


def _normalize_copy_text(value: object) -> str:
    """Normalize characters for the supplementary copy heuristic only."""

    return _normalize_for_flagging(value)


def _ngram_multiset_coverage(required: str, observed: str, width: int) -> float:
    """Return order-insensitive coverage of required n-grams in observed text."""

    if len(required) < width or len(observed) < width:
        return 0.0
    required_counts = Counter(
        required[index : index + width]
        for index in range(len(required) - width + 1)
    )
    observed_counts = Counter(
        observed[index : index + width]
        for index in range(len(observed) - width + 1)
    )
    matched = sum((required_counts & observed_counts).values())
    return matched / sum(required_counts.values())


def _copies_definition(edge_text: object, definition: object) -> bool:
    """Detect a definition copied whole or with only a small local rewrite."""

    normalized_edge = _normalize_copy_text(edge_text)
    normalized_definition = _normalize_copy_text(definition)
    if len(normalized_definition) < 6 or not normalized_edge:
        return False
    if normalized_definition in normalized_edge:
        return True
    if all(
        _ngram_multiset_coverage(
            normalized_definition, normalized_edge, width
        )
        >= threshold
        for width, threshold in _COPY_NGRAM_COVERAGE
    ):
        return True

    matcher = SequenceMatcher(None, normalized_definition, normalized_edge)
    longest = max((block.size for block in matcher.get_matching_blocks()), default=0)
    if longest >= max(8, (len(normalized_definition) * 2 + 2) // 3):
        return True

    minimum_window = max(6, len(normalized_definition) - 4)
    maximum_window = min(len(normalized_edge), len(normalized_definition) + 6)
    for width in range(minimum_window, maximum_window + 1):
        for start in range(0, len(normalized_edge) - width + 1):
            candidate = normalized_edge[start : start + width]
            candidate_matcher = SequenceMatcher(
                None, normalized_definition, candidate
            )
            matched = sum(
                block.size for block in candidate_matcher.get_matching_blocks()
            )
            definition_coverage = matched / len(normalized_definition)
            candidate_coverage = matched / len(candidate)
            if (
                candidate_matcher.ratio() >= 0.88
                and definition_coverage >= 0.8
                and candidate_coverage >= 0.8
            ):
                return True
    return False


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
    edge_reviews = independent_review.get("edge_reviews")
    if not isinstance(edge_reviews, list) or any(
        not isinstance(edge_review, dict) for edge_review in edge_reviews or []
    ):
        errors.append("independent learning review is incomplete")
        edge_reviews = []
    subject_ids: list[str] = []
    for edge_review in edge_reviews:
        if set(edge_review) != EDGE_REVIEW_FIELDS:
            errors.append("independent learning review is incomplete")
            continue
        subject_id = _strict_text(edge_review.get("subject_id"))
        observations = [
            _strict_text(edge_review.get(review_field))
            for review_field, _ in EDGE_REVIEW_OBSERVATIONS
        ]
        if (
            not subject_id
            or any(not observation for observation in observations)
            or len({_normalize_for_flagging(value) for value in observations})
            != len(observations)
        ):
            errors.append("independent learning review is incomplete")
        subject_ids.append(subject_id)
        if edge_review.get("reviewer_context_isolated") is not True:
            errors.append("independent learning review is not context-isolated")
    if len(subject_ids) != len(set(subject_ids)):
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

    records_by_term = {
        _text(record.get("term")): record
        for record in records
        if _text(record.get("term"))
    }
    edge_reviews = independent_review.get("edge_reviews", [])
    if not isinstance(edge_reviews, list):
        edge_reviews = []
    reviews_by_subject: dict[str, list[dict]] = {}
    for review in edge_reviews:
        if not isinstance(review, dict):
            continue
        subject_id = _strict_text(review.get("subject_id"))
        if subject_id:
            reviews_by_subject.setdefault(subject_id, []).append(review)
    ready_subjects: set[str] = set()
    for group in groups:
        if group.get("status") != "ready":
            continue
        for edge in group.get("minimum_differences", []) or []:
            if not has_reviewed_contrast_contract(edge):
                errors.append("comparison edge lacks reviewed contrast contract")
                continue
            subject_id = comparison_edge_subject_id(group, edge)
            if not subject_id:
                errors.append("comparison edge lacks reviewed contrast contract")
                continue
            ready_subjects.add(subject_id)
            matching_reviews = reviews_by_subject.get(subject_id, [])
            if len(matching_reviews) != 1:
                errors.append(
                    f"comparison edge lacks independent contrast review: {subject_id}"
                )
                continue
            edge_review = matching_reviews[0]
            observations_match = True
            for review_field, edge_field in EDGE_REVIEW_OBSERVATIONS:
                reviewed_value = _strict_text(edge_review.get(review_field))
                edge_value = _strict_text(edge.get(edge_field))
                if reviewed_value != edge_value:
                    errors.append(
                        "comparison edge independent review mismatch: "
                        f"{subject_id}.{review_field}"
                    )
                    observations_match = False
                    continue
                if reviewed_value not in _strict_text(edge.get("text")):
                    errors.append(
                        "minimum difference omits reviewed observation: "
                        f"{subject_id}.{review_field}"
                    )
                    observations_match = False
            definitions = tuple(
                record.get(field)
                for term in (edge.get("left"), edge.get("right"))
                for record in (records_by_term.get(_text(term)),)
                if record is not None
                for field in ("meaning", "distinctive_feature")
            )
            for review_field, edge_field in EDGE_REVIEW_OBSERVATIONS:
                observation = edge.get(edge_field)
                if any(
                    _copies_definition(observation, definition)
                    for definition in definitions
                ):
                    errors.append(
                        "comparison edge observation copies definition: "
                        f"{subject_id}.{review_field}"
                    )
            if not observations_match and any(
                _copies_definition(edge.get("text"), definition)
                for definition in definitions
            ):
                errors.append(
                    "minimum difference copies definition: "
                    f"{_text(group.get('group_id'))} "
                    f"{_text(edge.get('left'))} {_text(edge.get('right'))}"
                )

    for subject_id in reviews_by_subject:
        if subject_id not in ready_subjects:
            errors.append(
                f"independent contrast review has no ready edge: {subject_id}"
            )

    return list(dict.fromkeys(errors))
