"""Fail-closed semantic acceptance for learning-focused vocabulary previews."""

from __future__ import annotations

import re
from collections import Counter


_META_PROMPT_PATTERNS = (
    "题干先写到",
    "又明确出现",
    "这一落点",
    "这些关键落点",
    "材料呈现出",
    "题干没有",
    "题干强调",
)
_BAD_SLOT_PUNCTUATION = re.compile(r"[、，,；;。.!！?？:：]")
_GENERIC_SLOTS = {"目标", "对象", "事情", "事物", "情况", "状态", "某种语义", "具体语义"}


def _norm(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", str(value)).lower()


def validate_semantic_review(records: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(records, list):
        return ["semantic review must be a list"]
    seen: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            errors.append(f"semantic record must be object: {index}")
            continue
        term = record.get("term")
        if not isinstance(term, str) or not term.strip():
            errors.append(f"semantic term must be nonempty: {index}")
            continue
        if term in seen:
            errors.append(f"duplicate semantic term: {term}")
        seen.add(term)
        status = record.get("status")
        if status not in {"approved", "pending"}:
            errors.append(f"status must be approved or pending: {term}")
            continue
        if status == "pending":
            if not isinstance(record.get("pending_reason"), str) or len(_norm(record.get("pending_reason"))) < 8:
                errors.append(f"pending reason is not reviewable: {term}")
            continue
        meaning = record.get("meaning")
        slots = record.get("core_slots")
        if not isinstance(meaning, str) or len(_norm(meaning)) < 6:
            errors.append(f"approved meaning is incomplete: {term}")
        if not isinstance(slots, list) or not 2 <= len(slots) <= 4:
            errors.append(f"approved core requires two to four slots: {term}")
            slots = []
        joined = "".join(str(slot) for slot in slots)
        if joined.count("（") != joined.count("）") or joined.count("(") != joined.count(")"):
            errors.append(f"broken bracket in core slots: {term}")
        for slot in slots:
            if not isinstance(slot, str) or len(_norm(slot)) < 2:
                errors.append(f"empty or fragmentary core slot: {term}")
                continue
            if slot.count("（") != slot.count("）") or slot.count("(") != slot.count(")"):
                errors.append(f"broken bracket in core slot: {term}:{slot}")
            if _BAD_SLOT_PUNCTUATION.search(slot):
                errors.append(f"punctuation fragment in core slot: {term}:{slot}")
            if slot.strip() in _GENERIC_SLOTS:
                errors.append(f"generic core slot: {term}:{slot}")
        evidence = record.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"approved record lacks evidence: {term}")
        else:
            for item in evidence:
                if not isinstance(item, dict) or not all(
                    isinstance(item.get(field), str) and item.get(field).strip()
                    for field in ("source_group_id", "location", "quote")
                ):
                    errors.append(f"approved evidence is not locatable: {term}")
                    break
    return errors


def validate_comparison_review(groups: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(groups, list):
        return ["comparison review must be a list"]
    seen: set[str] = set()
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            errors.append(f"comparison group must be object: {index}")
            continue
        group_id = group.get("group_id")
        if not isinstance(group_id, str) or not group_id:
            errors.append(f"comparison group id missing: {index}")
            continue
        if group_id in seen:
            errors.append(f"duplicate comparison group: {group_id}")
        seen.add(group_id)
        if group.get("status") != "approved":
            errors.append(f"comparison group is not approved: {group_id}")
        if group.get("group_basis") != "reciprocal_reviewed_boundary":
            errors.append(f"comparison group basis is not independently reviewed: {group_id}")
        members = group.get("members")
        if not isinstance(members, list) or not 2 <= len(members) <= 6 or len(members) != len(set(members)):
            errors.append(f"comparison members invalid: {group_id}")
            members = []
        profiles = group.get("member_profiles")
        if not isinstance(profiles, dict) or set(profiles) != set(members):
            errors.append(f"member profiles must cover exact members: {group_id}")
        else:
            for term, profile in profiles.items():
                if not isinstance(profile, dict) or not isinstance(profile.get("meaning"), str) or not isinstance(profile.get("core_slots"), list):
                    errors.append(f"member profiles are incomplete: {group_id}:{term}")
        edges = group.get("one_glance_edges")
        covered: set[str] = set()
        if not isinstance(edges, list) or not edges:
            errors.append(f"pairwise one-glance edges missing: {group_id}")
        else:
            edge_ids: set[tuple[str, str]] = set()
            for edge in edges:
                if not isinstance(edge, dict):
                    errors.append(f"pairwise one-glance edge invalid: {group_id}")
                    continue
                left, right, difference = edge.get("left"), edge.get("right"), edge.get("difference")
                pair = tuple(sorted((str(left), str(right))))
                if left not in members or right not in members or left == right or pair in edge_ids:
                    errors.append(f"pairwise one-glance edge identity invalid: {group_id}")
                edge_ids.add(pair)
                covered.update((str(left), str(right)))
                if not isinstance(difference, str) or " vs " not in difference or len(_norm(difference)) < 6:
                    errors.append(f"pairwise one-glance difference invalid: {group_id}:{left}:{right}")
            if members and covered != set(members):
                errors.append(f"pairwise one-glance graph does not cover members: {group_id}")
        rules = group.get("selection_rules")
        if not isinstance(rules, list) or not rules:
            errors.append(f"selection rules missing: {group_id}")
        else:
            choices = [rule.get("choose") for rule in rules if isinstance(rule, dict)]
            if set(choices) != set(members):
                errors.append(f"selection rules must cover exact members: {group_id}")
            for rule in rules:
                if not isinstance(rule, dict) or not isinstance(rule.get("condition"), str) or len(_norm(rule.get("condition"))) < 6:
                    errors.append(f"selection rule is not concrete: {group_id}")
        observations = group.get("evidence_observations")
        if not isinstance(observations, dict) or set(observations) != set(members):
            errors.append(f"comparison evidence observations must cover members: {group_id}")
        else:
            for term, observation in observations.items():
                if not isinstance(observation, dict) or not all(
                    isinstance(observation.get(field), str) and observation.get(field).strip()
                    for field in ("observation", "source_group_id", "location", "quote")
                ):
                    errors.append(f"comparison observation is not locatable: {group_id}:{term}")
    return errors


def validate_dimension_novelty(review: object, semantics: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(review, list) or not isinstance(semantics, dict):
        return ["dimension novelty inputs must be list and object"]
    for entry in review:
        if not isinstance(entry, dict) or entry.get("disposition") != "approved_dimensions":
            continue
        group_id = str(entry.get("group_id"))
        dimensions = entry.get("dimensions")
        if not isinstance(dimensions, list) or len(dimensions) < 2:
            errors.append(f"approved dimensions require at least two axes: {group_id}")
            continue
        for dimension in dimensions:
            if not isinstance(dimension, dict):
                errors.append(f"dimension must be object: {group_id}")
                continue
            axis = str(dimension.get("axis"))
            judgments = dimension.get("judgments")
            if not isinstance(judgments, dict):
                errors.append(f"dimension judgments missing: {group_id}:{axis}")
                continue
            for term, judgment in judgments.items():
                slots = semantics.get(term, {}).get("core_slots", [])
                normalized_judgment = _norm(str(judgment).replace(str(term), ""))
                for slot in slots:
                    normalized_slot = _norm(slot)
                    if len(normalized_slot) >= 4 and normalized_slot in normalized_judgment:
                        errors.append(f"dimension repeats core slot: {group_id}:{axis}:{term}:{slot}")
    return errors


def _prompt_skeleton(prompt: str, terms: list[str]) -> str:
    value = prompt
    for term in terms:
        value = value.replace(term, "词语")
    value = re.sub(r"“[^”]*”", "“内容”", value)
    value = re.sub(r"\d+", "数字", value)
    return _norm(value)


def validate_application_authoring(applications: object, semantics: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(applications, list) or not isinstance(semantics, dict):
        return ["application authoring inputs must be list and object"]
    skeletons: Counter[str] = Counter()
    for index, application in enumerate(applications):
        if not isinstance(application, dict):
            errors.append(f"application must be object: {index}")
            continue
        term = application.get("term")
        prompt = application.get("prompt")
        options = application.get("options")
        answer = application.get("answer")
        if not isinstance(term, str) or term not in semantics:
            errors.append(f"application term has no approved semantics: {index}")
            continue
        if not isinstance(prompt, str) or len(_norm(prompt)) < 18:
            errors.append(f"application prompt lacks a concrete event: {term}")
            prompt = str(prompt or "")
        if any(pattern in prompt for pattern in _META_PROMPT_PATTERNS):
            errors.append(f"meta definition prompt: {term}")
        if term in prompt:
            errors.append(f"application prompt leaks answer: {term}")
        for slot in semantics[term].get("core_slots", []):
            if len(_norm(slot)) >= 4 and _norm(slot) in _norm(prompt):
                errors.append(f"application prompt quotes core slot: {term}:{slot}")
        if not isinstance(options, list) or not 2 <= len(options) <= 4 or len(set(options)) != len(options) or options.count(answer) != 1 or answer != term:
            errors.append(f"application options or answer invalid: {term}")
            options = []
        elements = application.get("scenario_elements")
        if not isinstance(elements, dict) or set(elements) != {"subject", "event", "constraint", "outcome"} or any(
            not isinstance(value, str) or len(_norm(value)) < 2 for value in (elements or {}).values()
        ):
            errors.append(f"application scenario elements incomplete: {term}")
        rejections = application.get("distractor_rejections")
        expected_distractors = set(options) - {answer} if options else set()
        if not isinstance(rejections, dict) or set(rejections) != expected_distractors or any(
            not isinstance(value, str) or len(_norm(value)) < 8 for value in (rejections or {}).values()
        ):
            errors.append(f"application distractor review incomplete: {term}")
        skeletons[_prompt_skeleton(prompt, options)] += 1
    if len(applications) >= 10:
        dominant = max(skeletons.values(), default=0)
        if dominant >= 5 and dominant / len(applications) >= 0.25:
            errors.append("application prompt skeleton dominates batch")
    return errors


def validate_preview_bundle(
    bundle: object,
    semantic_review: object,
    comparison_review: object,
    dimension_review: object,
    application_review: object,
) -> list[str]:
    """Bind rendered cards to the exact reviewed subset; a pass label is never evidence."""
    errors: list[str] = []
    if not all(isinstance(value, dict) for value in (bundle, semantic_review, comparison_review, dimension_review, application_review)):
        return ["preview bundle inputs must be objects"]
    if bundle.get("schema_version") != 2 or bundle.get("status") != "passed_reviewed_subset":
        errors.append("preview bundle status or schema invalid")
    expected_hashes = {
        "semantic": semantic_review.get("semantic_review_hash"),
        "comparison": comparison_review.get("comparison_review_hash"),
        "dimension": dimension_review.get("dimension_review_hash"),
        "application": application_review.get("application_review_hash"),
    }
    if bundle.get("source_review_hashes") != expected_hashes or any(not isinstance(value, str) or not value for value in expected_hashes.values()):
        errors.append("source review hash mismatch")

    semantic_records = semantic_review.get("records")
    comparison_groups = comparison_review.get("groups")
    dimension_groups = dimension_review.get("groups")
    applications = application_review.get("applications")
    if not isinstance(semantic_records, list) or not isinstance(comparison_groups, list) or not isinstance(dimension_groups, list) or not isinstance(applications, list):
        errors.append("source review collections missing")
        return errors
    errors.extend(validate_semantic_review(semantic_records))
    errors.extend(validate_comparison_review(comparison_groups))
    semantics = {record.get("term"): record for record in semantic_records if isinstance(record, dict) and record.get("status") == "approved"}
    errors.extend(validate_dimension_novelty(dimension_groups, semantics))
    errors.extend(validate_application_authoring(applications, semantics))

    def exact_identity(items: object, field: str, expected: set[str], label: str) -> None:
        if not isinstance(items, list):
            errors.append(f"{label} cards must be list")
            return
        identities = [item.get(field) for item in items if isinstance(item, dict)]
        if len(identities) != len(items) or len(identities) != len(set(identities)) or set(identities) != expected:
            errors.append(f"{label} cards do not match reviewed identities")
        if any(not isinstance(item.get("content"), str) or not item.get("content").strip() for item in items if isinstance(item, dict)):
            errors.append(f"{label} card content missing")

    exact_identity(bundle.get("basic_cards"), "term", set(semantics), "basic")
    exact_identity(bundle.get("comparison_cards"), "group_id", {str(group.get("group_id")) for group in comparison_groups}, "comparison")
    exact_identity(bundle.get("application_cards"), "term", {str(item.get("term")) for item in applications}, "application")
    return errors
