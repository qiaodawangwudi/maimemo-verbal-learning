"""Hard quality gate for application-scenario review and cards."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


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
    payload = {key: value for key, value in review.items() if key != "review_hash"}
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _subject_key(decision: dict) -> tuple[str, str]:
    return (_text(decision.get("subject_type")), _text(decision.get("subject_id")))


def _expected_subjects(registry: dict, groups: dict) -> dict[str, set[str]]:
    return {
        "semantic": {
            _text(record.get("sense_id"))
            for record in registry.get("records", [])
            if record.get("status") == "ready" and _text(record.get("sense_id"))
        },
        "comparison_group": {
            _text(group.get("group_id"))
            for group in groups.get("groups", [])
            if group.get("status") == "ready" and _text(group.get("group_id"))
        },
    }


def _validate_application_card(card: dict, source_quotes: set[str]) -> list[str]:
    errors: list[str] = []
    title = _text(card.get("title"))
    payload = card.get("application") or {}
    prompt = _text(payload.get("prompt"))
    options = [_text(option) for option in payload.get("options", []) if _text(option)]
    answer = _text(payload.get("answer"))
    clues = [_text(clue) for clue in payload.get("clue_extraction", []) if _text(clue)]
    rejections = payload.get("distractor_rejections") or {}
    construction = payload.get("construction") or {}

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
    semantic_basis = [
        _text(item) for item in construction.get("semantic_basis", []) if _text(item)
    ]
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
) -> list[str]:
    """Require complete review coverage and useful cards for every create decision."""

    errors: list[str] = []
    expected = _expected_subjects(registry, groups)
    source_quotes = {
        "".join(_text(evidence.get("quote")).split())
        for record in registry.get("records", [])
        for evidence in record.get("evidence", [])
        if _text(evidence.get("quote"))
    }
    decisions = review.get("decisions", []) if isinstance(review, dict) else []

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

    application_cards = [
        card for card in final_cards.get("cards", []) if card.get("card_type") == "application"
    ]
    title_counts = Counter(_text(card.get("title")) for card in application_cards)
    for title, count in title_counts.items():
        if count > 1:
            errors.append(f"duplicate application card title: {title}")
    actual_titles = set(title_counts)
    if plan.get("application_review_hash") != application_review_hash(review):
        errors.append("action plan is not bound to current application review")
    planned_titles = {
        _text(action.get("title")) for action in plan.get("actions", [])
    }
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

    def load(name: str) -> dict:
        path = args.artifact_dir / name
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8-sig"))

    errors = evaluate_application_gate(
        load("master_semantic_registry.json"),
        load("group_registry.json"),
        load("application_review.json"),
        load("final_cards.json"),
        load("action_plan.json"),
    )
    print(json.dumps({"ok": not errors, "errors": errors}, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
