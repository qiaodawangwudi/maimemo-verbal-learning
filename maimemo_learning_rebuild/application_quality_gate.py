"""Hard quality gate for application-scenario review and cards."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from .application_blind_review import (
    blind_review_hash,
    evaluate_blind_reviews,
    load_strict_json,
    strict_json_error,
)


SUBJECT_TYPES = {"semantic", "comparison_group"}
DECISIONS = {"create", "not_needed"}
CONSTRUCTION_MODES = {"authored", "adapted"}
CLASSROOM_SPEECH = (
    "咱们",
    "同学们",
    "对不对",
    "来看一下",
    "可以吧",
    "可以吗",
    "这个词",
    "选项的侧重点",
)


def _text(value: object) -> str:
    return str(value or "").strip()


def application_review_hash(review: dict) -> str:
    if not isinstance(review, dict):
        raise TypeError("application review must be an object")
    if strict_json_error(review):
        raise ValueError("application review is not strict JSON")
    payload = {key: value for key, value in review.items() if key != "review_hash"}
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _subject_key(decision: dict) -> tuple[str, str]:
    return (_text(decision.get("subject_type")), _text(decision.get("subject_id")))


def _expected_subjects(records: list[dict], group_records: list[dict]) -> dict[str, set[str]]:
    return {
        "semantic": {
            _text(record.get("sense_id"))
            for record in records
            if record.get("status") == "ready" and _text(record.get("sense_id"))
        },
        "comparison_group": {
            _text(group.get("group_id"))
            for group in group_records
            if group.get("status") == "ready" and _text(group.get("group_id"))
        },
    }


def _validate_application_card(card: dict, source_quotes: set[str]) -> list[str]:
    errors: list[str] = []
    title = _text(card.get("title"))
    payload = card.get("application")
    if not isinstance(payload, dict):
        return [f"application card payload must be an object: {title}"]
    prompt = _text(payload.get("prompt"))
    raw_options = payload.get("options", [])
    options = (
        [_text(option) for option in raw_options if _text(option)]
        if isinstance(raw_options, list)
        else []
    )
    answer = _text(payload.get("answer"))
    raw_clues = payload.get("clue_extraction", [])
    clues = (
        [_text(clue) for clue in raw_clues if _text(clue)]
        if isinstance(raw_clues, list)
        else []
    )
    rejections = payload.get("distractor_rejections")
    if not isinstance(rejections, dict):
        rejections = {}
    construction = payload.get("construction")
    if not isinstance(construction, dict):
        construction = {}

    if not title.startswith("语境应用｜"):
        errors.append(f"application card has invalid title: {title}")
    if len(prompt) < 18:
        errors.append(f"application card lacks usable context: {title}")
    if any(marker in prompt for marker in CLASSROOM_SPEECH):
        errors.append(f"application card contains classroom speech: {title}")
    normalized_prompt = "".join(prompt.split())
    if normalized_prompt and normalized_prompt in source_quotes:
        errors.append(f"application card copies source wording: {title}")
    if len(options) < 2 or len(set(options)) != len(options):
        errors.append(f"application card lacks valid options: {title}")
    if not answer or answer not in options:
        errors.append(f"application card answer is not an option: {title}")
    if not clues:
        errors.append(f"application card lacks clue extraction: {title}")
    if len(_text(payload.get("fit_reasoning"))) < 12:
        errors.append(f"application card lacks fit reasoning: {title}")
    distractors = [option for option in options if option != answer]
    if not distractors or any(len(_text(rejections.get(term))) < 12 for term in distractors):
        errors.append(f"application card lacks distractor rejection: {title}")
    if len(_text(payload.get("transfer_rule"))) < 12:
        errors.append(f"application card lacks transfer rule: {title}")
    if len(_text(payload.get("uniqueness_rationale"))) < 12:
        errors.append(f"application card lacks uniqueness rationale: {title}")
    mode = _text(construction.get("mode"))
    if mode not in CONSTRUCTION_MODES:
        errors.append(f"application card uses unsupported construction mode: {title}")
    raw_semantic_basis = construction.get("semantic_basis", [])
    semantic_basis = (
        [_text(item) for item in raw_semantic_basis if _text(item)]
        if isinstance(raw_semantic_basis, list)
        else []
    )
    if not semantic_basis:
        errors.append(f"application card lacks semantic construction basis: {title}")
    if len(_text(construction.get("construction_note"))) < 12:
        errors.append(f"application card lacks construction note: {title}")
    if mode == "adapted" and not construction.get("source_basis"):
        errors.append(f"adapted application card lacks source basis: {title}")
    return errors


def evaluate_application_gate(
    registry: dict,
    groups: dict,
    review: dict,
    final_cards: dict,
    plan: dict,
    blind_review: dict | None = None,
) -> list[str]:
    """Require complete review coverage and useful cards for every create decision."""

    errors: list[str] = []

    def checked_object(value: object, label: str) -> dict:
        if not isinstance(value, dict):
            errors.append(f"{label} must be an object")
            return {}
        if strict_json_error(value):
            errors.append(f"{label} is not strict JSON")
            return {}
        return value

    registry = checked_object(registry, "semantic registry")
    groups = checked_object(groups, "group registry")
    review_is_object = isinstance(review, dict) and not strict_json_error(review)
    review = checked_object(review, "application review")
    final_cards = checked_object(final_cards, "final cards")
    plan = checked_object(plan, "action plan")

    def object_list(container: dict, key: str, label: str) -> list[dict]:
        value = container.get(key, [])
        if not isinstance(value, list):
            errors.append(f"{label} must be a list")
            return []
        objects: list[dict] = []
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                errors.append(f"{label} entry must be an object: {index}")
            else:
                objects.append(item)
        return objects

    records = object_list(registry, "records", "semantic registry records")
    group_records = object_list(groups, "groups", "group registry groups")
    decisions = object_list(review, "decisions", "application review decisions")
    cards = object_list(final_cards, "cards", "final cards cards")
    plan_actions = object_list(plan, "actions", "action plan actions")
    expected = _expected_subjects(records, group_records)
    source_quotes = {
        "".join(_text(evidence.get("quote")).split())
        for record in records
        for evidence in (
            record.get("evidence", [])
            if isinstance(record.get("evidence", []), list)
            else []
        )
        if isinstance(evidence, dict)
        if _text(evidence.get("quote"))
    }

    if not review.get("complete"):
        errors.append("application review is not marked complete")

    keys = [_subject_key(decision) for decision in decisions]
    duplicate_keys = {key for key, count in Counter(keys).items() if count > 1}
    for subject_type, subject_id in sorted(duplicate_keys):
        errors.append(f"duplicate application decision: {subject_type}:{subject_id}")

    actual_by_type = {
        subject_type: {
            subject_id
            for current_type, subject_id in keys
            if current_type == subject_type
        }
        for subject_type in SUBJECT_TYPES
    }
    labels = {"semantic": "semantic", "comparison_group": "comparison-group"}
    for subject_type in ("semantic", "comparison_group"):
        missing = expected[subject_type] - actual_by_type[subject_type]
        extra = actual_by_type[subject_type] - expected[subject_type]
        if missing:
            errors.append(
                f"application review missing {labels[subject_type]} decisions: {len(missing)}"
            )
        if extra:
            errors.append(
                f"application review has unknown {labels[subject_type]} decisions: {len(extra)}"
            )

    create_titles: set[str] = set()
    for decision in decisions:
        subject_type, subject_id = _subject_key(decision)
        if subject_type not in SUBJECT_TYPES or not subject_id:
            errors.append(f"invalid application decision subject: {subject_type}:{subject_id}")
            continue
        value = _text(decision.get("decision"))
        if value not in DECISIONS:
            errors.append(f"invalid application decision: {subject_type}:{subject_id}")
            continue
        if len(_text(decision.get("reason"))) < 12:
            errors.append(f"application decision lacks specific reason: {subject_type}:{subject_id}")
        if value == "create":
            title = _text(decision.get("card_title"))
            if not title.startswith("语境应用｜"):
                errors.append(f"application create decision lacks card title: {subject_type}:{subject_id}")
            else:
                create_titles.add(title)
            if len(_text(decision.get("training_goal"))) < 8:
                errors.append(f"application create decision lacks training goal: {subject_type}:{subject_id}")

    application_cards = [card for card in cards if card.get("card_type") == "application"]
    title_counts = Counter(_text(card.get("title")) for card in application_cards)
    for title, count in title_counts.items():
        if count > 1:
            errors.append(f"duplicate application card title: {title}")
    actual_titles = set(title_counts)
    current_application_hash = None
    if review_is_object:
        try:
            current_application_hash = application_review_hash(review)
        except (TypeError, ValueError, OverflowError, RecursionError):
            errors.append("application review is not strict JSON")
    if current_application_hash is None or plan.get(
        "application_review_hash"
    ) != current_application_hash:
        errors.append("action plan is not bound to current application review")
    if blind_review is None:
        errors.append("missing blind review")
    else:
        errors.extend(evaluate_blind_reviews(final_cards, blind_review))
        current_blind_hash = None
        if isinstance(blind_review, dict) and not strict_json_error(blind_review):
            try:
                current_blind_hash = blind_review_hash(blind_review)
            except (TypeError, ValueError, OverflowError, RecursionError):
                current_blind_hash = None
        if current_blind_hash is None or plan.get(
            "blind_review_hash"
        ) != current_blind_hash:
            errors.append("action plan is not bound to current blind review")
    planned_titles = {_text(action.get("title")) for action in plan_actions}
    for title in sorted(create_titles - planned_titles):
        errors.append(f"application card is missing from action plan: {title}")
    for title in sorted(create_titles - actual_titles):
        errors.append(f"application decision has no matching card: {title}")
    for title in sorted(actual_titles - create_titles):
        errors.append(f"application card has no approved decision: {title}")
    for card in application_cards:
        errors.extend(_validate_application_card(card, source_quotes))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args()

    def load(name: str, *, missing: object = None) -> object:
        path = args.artifact_dir / name
        if not path.exists():
            return missing
        return load_strict_json(path)

    try:
        errors = evaluate_application_gate(
            load("master_semantic_registry.json", missing={}),
            load("group_registry.json", missing={}),
            load("application_review.json", missing={}),
            load("final_cards.json", missing={}),
            load("action_plan.json", missing={}),
            load("application_blind_review.json"),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        errors = [f"invalid strict JSON: {exc}"]
    print(json.dumps({"ok": not errors, "errors": errors}, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
