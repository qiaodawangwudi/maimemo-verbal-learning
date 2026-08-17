"""Independent learning-value checks for semantic records and comparisons."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from difflib import SequenceMatcher

from .groups import comparison_edge_subject_id, has_reviewed_contrast_contract
from .render import render_comparison_card


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
        "comparison_subject_id",
        "group_id",
        "left",
        "right",
        "left_observation",
        "right_observation",
        "contrast_axis",
        "left_focus",
        "right_focus",
        "question_selection_condition",
    }
)
COMPARISON_REVIEW_FIELDS = frozenset(
    {
        "comparison_subject_id",
        "stable_card_key",
        "card_type",
        "route_id",
        "route_name",
        "title",
        "final_content_hash",
        "edge_subject_ids",
    }
)
INDEPENDENT_REVIEW_BASE_FIELDS = frozenset(
    {
        "complete",
        "reviewer_context_isolated",
        "resolutions",
        "edge_reviews",
        "comparison_reviews",
    }
)
INDEPENDENT_REVIEW_FIELD_SETS = frozenset(
    {
        INDEPENDENT_REVIEW_BASE_FIELDS,
        INDEPENDENT_REVIEW_BASE_FIELDS | {"review_hash"},
        INDEPENDENT_REVIEW_BASE_FIELDS
        | {"semantic_registry_hash", "group_registry_hash", "review_hash"},
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


def _canonical_hash(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def comparison_review_subject_id(binding: dict) -> str:
    """Return a collision-safe identity for one exact reviewed card output."""

    fields = (
        "stable_card_key",
        "card_type",
        "route_id",
        "route_name",
        "title",
        "final_content_hash",
    )
    values = {field: binding.get(field) for field in fields}
    if any(
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > 512
        or re.search(r"[\x00-\x1f\x7f]", value)
        for value in values.values()
    ):
        return ""
    if values["card_type"] != "comparison":
        return ""
    if not re.fullmatch(r"[0-9a-f]{64}", values["final_content_hash"]):
        return ""
    return "comparison-v1-" + _canonical_hash(
        {"kind": "comparison_card", "version": 1, **values}
    )


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
    if frozenset(independent_review) not in INDEPENDENT_REVIEW_FIELD_SETS:
        errors.append("independent learning review is incomplete")
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
    edge_comparison_ids: dict[str, list[str]] = {}
    for edge_review in edge_reviews:
        if set(edge_review) != EDGE_REVIEW_FIELDS:
            errors.append("independent learning review is incomplete")
            continue
        subject_id = _strict_text(edge_review.get("subject_id"))
        identity_group = {"group_id": edge_review.get("group_id")}
        identity_edge = {
            "left": edge_review.get("left"),
            "right": edge_review.get("right"),
        }
        expected_subject_id = comparison_edge_subject_id(
            identity_group, identity_edge
        )
        observations = [
            _strict_text(edge_review.get(review_field))
            for review_field, _ in EDGE_REVIEW_OBSERVATIONS
        ]
        if (
            not subject_id
            or subject_id != expected_subject_id
            or not _strict_text(edge_review.get("comparison_subject_id"))
            or not _strict_text(edge_review.get("left_observation"))
            or not _strict_text(edge_review.get("right_observation"))
            or any(not observation for observation in observations)
            or len({_normalize_for_flagging(value) for value in observations})
            != len(observations)
        ):
            errors.append("independent learning review is incomplete")
        subject_ids.append(subject_id)
        edge_comparison_ids.setdefault(
            _strict_text(edge_review.get("comparison_subject_id")), []
        ).append(subject_id)
    if len(subject_ids) != len(set(subject_ids)):
        errors.append("independent learning review is incomplete")

    comparison_reviews = independent_review.get("comparison_reviews")
    if not isinstance(comparison_reviews, list) or any(
        not isinstance(comparison_review, dict)
        for comparison_review in comparison_reviews or []
    ):
        errors.append("independent learning review is incomplete")
        comparison_reviews = []
    comparison_ids: list[str] = []
    for comparison_review in comparison_reviews:
        if set(comparison_review) != COMPARISON_REVIEW_FIELDS:
            errors.append("independent learning review is incomplete")
            continue
        comparison_id = _strict_text(
            comparison_review.get("comparison_subject_id")
        )
        expected_comparison_id = comparison_review_subject_id(comparison_review)
        edge_subject_ids = comparison_review.get("edge_subject_ids")
        if (
            not comparison_id
            or comparison_id != expected_comparison_id
            or not isinstance(edge_subject_ids, list)
            or not edge_subject_ids
            or any(type(value) is not str or not value for value in edge_subject_ids)
            or len(edge_subject_ids) != len(set(edge_subject_ids))
            or set(edge_subject_ids) != set(edge_comparison_ids.get(comparison_id, []))
        ):
            errors.append("independent learning review is incomplete")
        comparison_ids.append(comparison_id)
    if len(comparison_ids) != len(set(comparison_ids)):
        errors.append("independent learning review is incomplete")
    if set(edge_comparison_ids) != set(comparison_ids):
        errors.append("independent learning review is incomplete")
    return list(dict.fromkeys(errors))


def _source_anchor_valid(anchor: object, record: dict | None) -> bool:
    value = _strict_text(anchor)
    normalized = _normalize_for_flagging(value)
    generic_markers = (
        "本身",
        "词语不同",
        "含义不同",
        "判断落点",
        "变量",
        "标签",
        "模板",
        "占位",
        "待填写",
        "待补充",
    )
    if (
        record is None
        or len(normalized) < 4
        or normalized == _normalize_for_flagging(record.get("term"))
        or any(marker in value for marker in generic_markers)
    ):
        return False
    sources = (
        _strict_text(record.get("meaning")),
        _strict_text(record.get("distinctive_feature")),
    )
    return any(value in source for source in sources if source)


def _comparison_stable_key(title: str) -> str:
    prefix = "近义辨析｜"
    return "comparison:" + title.removeprefix(prefix).replace("｜", ":")


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
    comparison_reviews = independent_review.get("comparison_reviews", [])
    if not isinstance(comparison_reviews, list):
        comparison_reviews = []
    comparisons_by_subject: dict[str, list[dict]] = {}
    for comparison_review in comparison_reviews:
        if not isinstance(comparison_review, dict):
            continue
        comparison_id = _strict_text(
            comparison_review.get("comparison_subject_id")
        )
        if comparison_id:
            comparisons_by_subject.setdefault(comparison_id, []).append(
                comparison_review
            )
    ready_subjects: set[str] = set()
    ready_comparison_subjects: set[str] = set()
    for group in groups:
        if group.get("status") != "ready":
            continue
        group_edge_subjects: list[str] = []
        group_comparison_subjects: list[str] = []
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
            if (
                edge_review.get("group_id") != group.get("group_id")
                or edge_review.get("left") != edge.get("left")
                or edge_review.get("right") != edge.get("right")
            ):
                errors.append(
                    f"comparison edge independent review identity mismatch: {subject_id}"
                )
                continue
            group_edge_subjects.append(subject_id)
            comparison_subject = _strict_text(
                edge_review.get("comparison_subject_id")
            )
            if comparison_subject:
                group_comparison_subjects.append(comparison_subject)
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
            left_record = records_by_term.get(_text(edge.get("left")))
            right_record = records_by_term.get(_text(edge.get("right")))
            left_anchor = _strict_text(edge_review.get("left_observation"))
            right_anchor = _strict_text(edge_review.get("right_observation"))
            axis = _strict_text(edge_review.get("contrast_axis"))
            left_focus = _strict_text(edge_review.get("left_focus"))
            right_focus = _strict_text(edge_review.get("right_focus"))
            selection = _strict_text(
                edge_review.get("question_selection_condition")
            )
            left_term = _text(edge.get("left"))
            right_term = _text(edge.get("right"))
            anchored = (
                _source_anchor_valid(left_anchor, left_record)
                and _source_anchor_valid(right_anchor, right_record)
                and left_anchor != right_anchor
                and all(
                    value in axis
                    for value in (left_term, right_term, left_anchor, right_anchor)
                )
                and all(value in left_focus for value in (left_term, left_anchor))
                and all(value in right_focus for value in (right_term, right_anchor))
                and "选" in selection
                and all(
                    value in selection
                    for value in (left_term, right_term, left_anchor, right_anchor)
                )
            )
            if not anchored:
                errors.append(
                    f"comparison edge review lacks source anchors: {subject_id}"
                )
            definitions = tuple(
                record.get(field)
                for term in (edge.get("left"), edge.get("right"))
                for record in (records_by_term.get(_text(term)),)
                if record is not None
                for field in ("meaning", "distinctive_feature")
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

        unique_comparison_subjects = set(group_comparison_subjects)
        if group_edge_subjects and len(unique_comparison_subjects) != 1:
            errors.append(
                "ready comparison group lacks one independent card review: "
                f"{_text(group.get('group_id'))}"
            )
            continue
        if not group_edge_subjects:
            continue
        comparison_subject = next(iter(unique_comparison_subjects))
        ready_comparison_subjects.add(comparison_subject)
        matching_comparisons = comparisons_by_subject.get(comparison_subject, [])
        if len(matching_comparisons) != 1:
            errors.append(
                "ready comparison group lacks one independent card review: "
                f"{_text(group.get('group_id'))}"
            )
            continue
        comparison_review = matching_comparisons[0]
        member_records = [
            records_by_term.get(_text(term)) for term in group.get("members", [])
        ]
        if not member_records or any(record is None for record in member_records):
            errors.append(
                f"comparison review missing source records: {_text(group.get('group_id'))}"
            )
            continue
        title = _text(
            group.get("title")
            or group.get("current_title")
            or f"近义辨析｜{'、'.join(group.get('members', []))}"
        )
        rendered = render_comparison_card(group, member_records)
        expected = {
            "stable_card_key": _comparison_stable_key(title),
            "card_type": "comparison",
            "title": title,
            "final_content_hash": hashlib.sha256(
                rendered.encode("utf-8")
            ).hexdigest(),
        }
        if (
            any(comparison_review.get(field) != value for field, value in expected.items())
            or set(comparison_review.get("edge_subject_ids", []))
            != set(group_edge_subjects)
            or comparison_review_subject_id(comparison_review)
            != comparison_subject
        ):
            errors.append(
                f"reviewed comparison output mismatch: {expected['stable_card_key']}"
            )

    for subject_id in reviews_by_subject:
        if subject_id not in ready_subjects:
            errors.append(
                f"independent contrast review has no ready edge: {subject_id}"
            )
    for comparison_subject in comparisons_by_subject:
        if comparison_subject not in ready_comparison_subjects:
            errors.append(
                "independent comparison card review has no ready group: "
                f"{comparison_subject}"
            )

    return list(dict.fromkeys(errors))
