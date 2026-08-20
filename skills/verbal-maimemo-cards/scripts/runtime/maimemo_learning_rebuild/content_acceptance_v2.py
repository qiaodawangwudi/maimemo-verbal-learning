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
_GENERIC_SCENARIO_OUTCOMES = {
    "横线所在句准确成立",
    "句子准确成立",
    "表达准确",
    "选择正确答案",
}
_PLACEHOLDER_SCENARIO_MARKERS = ("所缺词语", "填入词语", "横线所在")
_LEXICAL_SUFFIX_AFTER_BLANK = re.compile(r"____[剂]")
_BOILERPLATE_BOUNDARY_MARKERS = (
    "课程证据中未出现可直接替换的近义词",
    "按本词核心语义判断",
    "不能只因大意相近互换",
)


def _norm(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", str(value)).lower()


def _review_frame(value: object, members: object = ()) -> str:
    text = str(value)
    for member in members if isinstance(members, list) else []:
        text = text.replace(str(member), "<词>")
    text = re.sub(r"“[^”]*”", "“<内容>”", text)
    text = re.sub(r"\d+", "<数字>", text)
    return _norm(text)


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
            if slot.lstrip().startswith(("/", "\\")) or "课程" in slot or slot.count("“") != slot.count("”"):
                errors.append(f"generation debris in core slot: {term}:{slot}")
        normalized_core = _norm(joined)
        normalized_meaning = _norm(meaning)
        if len(normalized_core) >= 8 and (
            normalized_core in normalized_meaning or normalized_meaning in normalized_core
        ):
            errors.append(f"core merely repeats meaning: {term}")
        boundary = record.get("misuse_boundary")
        if isinstance(boundary, str) and any(marker in boundary for marker in _BOILERPLATE_BOUNDARY_MARKERS):
            errors.append(f"boilerplate misuse boundary: {term}")
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
    adjudication_frames: Counter[str] = Counter()
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
        adjudication = group.get("closed_group_adjudication")
        if not isinstance(adjudication, dict):
            errors.append(f"closed-group adjudication missing: {group_id}")
        else:
            if adjudication.get("method") != "manual_closed_group_review":
                errors.append(f"closed-group adjudication method invalid: {group_id}")
            if adjudication.get("relation") not in {"near_synonym", "same_slot_confusable"}:
                errors.append(f"closed-group adjudication relation invalid: {group_id}")
            if adjudication.get("reviewed_members") != members:
                errors.append(f"closed-group adjudication members mismatch: {group_id}")
            for field in ("why_confusable", "why_closed"):
                if not isinstance(adjudication.get(field), str) or len(_norm(adjudication.get(field))) < 8:
                    errors.append(f"closed-group adjudication {field} incomplete: {group_id}")
                else:
                    adjudication_frames[f"{field}:{_review_frame(adjudication[field], members)}"] += 1
    if len(groups) >= 5 and adjudication_frames:
        dominant = adjudication_frames.most_common(1)[0][1]
        if dominant >= 5 and dominant / len(groups) >= 0.5:
            errors.append("generated closed-group adjudication skeleton dominates batch")
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


def validate_dimension_review_coverage(groups: object, review: object) -> list[str]:
    """Validate that every comparison group received a substantive dimension decision."""

    if not isinstance(groups, list) or not isinstance(review, list):
        return ["dimension coverage inputs must be lists"]
    errors: list[str] = []
    expected = {
        str(group.get("group_id")): [str(term) for term in group.get("members", [])]
        for group in groups
        if isinstance(group, dict) and group.get("group_id")
    }
    entries: dict[str, dict] = {}
    for index, entry in enumerate(review):
        if not isinstance(entry, dict):
            errors.append(f"dimension review entry must be object: {index}")
            continue
        group_id = str(entry.get("group_id", ""))
        if not group_id:
            errors.append(f"dimension review group id missing: {index}")
            continue
        if group_id in entries:
            errors.append(f"duplicate dimension review group: {group_id}")
        entries[group_id] = entry
    if set(entries) != set(expected):
        errors.append("dimension review must cover exact comparison groups")
    approved = 0
    insufficiency_reasons: list[str] = []
    insufficiency_frames: list[str] = []
    checked_axis_sets: list[tuple[str, ...]] = []
    for group_id, members in expected.items():
        entry = entries.get(group_id)
        if entry is None:
            continue
        if entry.get("members") != members:
            errors.append(f"dimension review members mismatch: {group_id}")
        disposition = entry.get("disposition")
        if disposition == "approved_dimensions":
            approved += 1
            dimensions = entry.get("dimensions")
            if not isinstance(dimensions, list) or len(dimensions) < 2:
                errors.append(f"approved dimensions require at least two axes: {group_id}")
        elif disposition == "insufficient_dimensions":
            axes = entry.get("checked_candidate_axes")
            reason = entry.get("insufficiency_reason")
            if not isinstance(axes, list) or not axes or any(
                not isinstance(axis, str) or len(_norm(axis)) < 2 for axis in axes
            ):
                errors.append(f"checked candidate axes missing: {group_id}")
            else:
                checked_axis_sets.append(tuple(_norm(axis) for axis in axes))
            if not isinstance(reason, str) or len(_norm(reason)) < 8:
                errors.append(f"dimension insufficiency reason incomplete: {group_id}")
            else:
                insufficiency_reasons.append(_norm(reason))
                insufficiency_frames.append(_review_frame(reason, members))
        else:
            errors.append(f"dimension disposition invalid: {group_id}")
            if not isinstance(entry.get("checked_candidate_axes"), list) or not entry.get(
                "checked_candidate_axes"
            ):
                errors.append(f"checked candidate axes missing: {group_id}")
    if expected and approved == 0:
        errors.append("blanket dimension deletion is forbidden")
    if len(insufficiency_reasons) >= 3:
        dominant = Counter(insufficiency_reasons).most_common(1)[0][1]
        if dominant >= 3 and dominant / len(insufficiency_reasons) >= 0.5:
            errors.append("homogeneous dimension insufficiency reason dominates batch")
    if len(insufficiency_frames) >= 4:
        dominant_frame = Counter(insufficiency_frames).most_common(1)[0][1]
        dominant_axes = Counter(checked_axis_sets).most_common(1)[0][1]
        if (
            dominant_frame >= 4
            and dominant_frame / len(insufficiency_frames) >= 0.5
            and dominant_axes / len(checked_axis_sets) >= 0.5
        ):
            errors.append("homogeneous dimension review frame and axis set dominate batch")
    return errors


def validate_card_learning_layers(content: object, card_type: str, identity: str) -> list[str]:
    """Validate the learning-layer order required by the card method."""

    if not isinstance(content, str):
        return [f"card content must be text: {identity}"]
    required = {
        "basic": ["核心辨析", "基本词义", "一眼辨析"],
        "comparison": ["核心辨析", "基本词义", "一眼辨析", "怎么选"],
    }.get(card_type, [])
    positions: list[tuple[str, int]] = []
    errors: list[str] = []
    for layer in required:
        position = content.find(f"【{layer}】")
        if position < 0:
            errors.append(f"missing layer: {layer}: {identity}")
        else:
            positions.append((layer, position))
    if len(positions) == len(required) and [position for _, position in positions] != sorted(
        position for _, position in positions
    ):
        errors.append(f"learning layers out of order: {identity}")
    optional_order = ["一眼辨析", "多维判断", "易错边界", "附加｜题干可圈出"]
    previous = content.find("【基本词义】")
    for layer in optional_order:
        position = content.find(f"【{layer}】")
        if position >= 0 and previous >= 0 and position < previous:
            errors.append(f"learning layers out of order: {identity}:{layer}")
        if position >= 0:
            previous = position
    if card_type == "comparison" and all(content.find(f"【{layer}】") >= 0 for layer in ("核心辨析", "基本词义", "怎么选")):
        core_body = content[
            content.find("【核心辨析】") + len("【核心辨析】") : content.find("【基本词义】")
        ]
        how_body = content[content.find("【怎么选】") + len("【怎么选】") :]
        core_slots: list[str] = []
        for line in core_body.splitlines():
            payload = re.sub(r"^\s*\[T#B#[^\]]*\]", "", line).strip()
            core_slots.extend(_norm(slot) for slot in payload.split("+") if len(_norm(slot)) >= 4)
        normalized_how = _norm(how_body)
        if len(core_slots) >= 2 and all(slot in normalized_how for slot in core_slots):
            errors.append(f"how-to-choose repeats core slots: {identity}")
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
    rejection_skeletons: Counter[str] = Counter()
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
        if _LEXICAL_SUFFIX_AFTER_BLANK.search(prompt):
            errors.append(f"application blank leaks lexical form: {term}")
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
        else:
            event = str(elements.get("event", ""))
            outcome = str(elements.get("outcome", ""))
            if any(marker in event for marker in _PLACEHOLDER_SCENARIO_MARKERS):
                errors.append(f"placeholder scenario event: {term}")
            if outcome.strip() in _GENERIC_SCENARIO_OUTCOMES or "横线" in outcome:
                errors.append(f"generic scenario outcome: {term}")
        rejections = application.get("distractor_rejections")
        expected_distractors = set(options) - {answer} if options else set()
        if not isinstance(rejections, dict) or set(rejections) != expected_distractors or any(
            not isinstance(value, str) or len(_norm(value)) < 8 for value in (rejections or {}).values()
        ):
            errors.append(f"application distractor review incomplete: {term}")
        else:
            for distractor, explanation in rejections.items():
                value = str(explanation)
                normalized = value.replace(str(distractor), "{term}")
                normalized = re.sub(r"“[^”]*”", "“{condition}”", normalized)
                rejection_skeletons[_norm(normalized)] += 1
        skeletons[_prompt_skeleton(prompt, options)] += 1
    if len(applications) >= 10:
        dominant = max(skeletons.values(), default=0)
        if dominant >= 5 and dominant / len(applications) >= 0.25:
            errors.append("application prompt skeleton dominates batch")
        rejection_dominant = max(rejection_skeletons.values(), default=0)
        if rejection_dominant >= 5 and rejection_dominant / max(1, sum(rejection_skeletons.values())) >= 0.25:
            errors.append("distractor explanation template dominates batch")
        rejection_total = sum(rejection_skeletons.values())
        minimum_frames = max(6, (rejection_total + 4) // 5)
        if rejection_total >= 20 and len(rejection_skeletons) < minimum_frames:
            errors.append("too few distractor explanation frames for batch")
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
    errors.extend(validate_dimension_review_coverage(comparison_groups, dimension_groups))
    errors.extend(validate_dimension_novelty(dimension_groups, semantics))
    errors.extend(validate_application_authoring(applications, semantics))
    grouped_terms = {
        str(term)
        for group in comparison_groups
        if isinstance(group, dict) and isinstance(group.get("members"), list)
        for term in group["members"]
    }
    application_terms = {
        str(item.get("term")) for item in applications if isinstance(item, dict) and item.get("term")
    }
    if grouped_terms != set(semantics):
        errors.append("approved terms missing comparison group and one-glance review")
    if application_terms != set(semantics):
        errors.append("approved terms missing application review")

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
    exact_identity(bundle.get("application_cards"), "term", set(semantics), "application")
    for card in bundle.get("basic_cards", []) if isinstance(bundle.get("basic_cards"), list) else []:
        if isinstance(card, dict):
            errors.extend(validate_card_learning_layers(card.get("content"), "basic", str(card.get("term"))))
    for card in bundle.get("comparison_cards", []) if isinstance(bundle.get("comparison_cards"), list) else []:
        if isinstance(card, dict):
            errors.extend(
                validate_card_learning_layers(
                    card.get("content"), "comparison", str(card.get("group_id"))
                )
            )
    return errors
