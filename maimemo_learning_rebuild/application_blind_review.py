"""Independent blind-solve review for frozen application cards."""

from __future__ import annotations

import hashlib
import json
from collections import Counter


GENERIC_REVIEW_PHRASES = (
    "不符合题意",
    "不符合语境",
    "不合适",
    "不是答案",
    "不能选择这个选项",
    "与题干不匹配",
)


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _normalized_reason(value: str) -> str:
    return "".join(character for character in value if character.isalnum())


def _application_cards(final_cards: dict) -> tuple[list[dict], list[str]]:
    if not isinstance(final_cards, dict):
        return [], ["final cards must be an object"]
    cards = final_cards.get("cards")
    if not isinstance(cards, list):
        return [], ["final cards cards must be a list"]
    applications: list[dict] = []
    errors: list[str] = []
    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            errors.append(f"final card must be an object: {index}")
            continue
        if card.get("card_type") == "application":
            applications.append(card)
    return applications, errors


def _review_entries(blind_review: dict) -> tuple[list[dict], list[str]]:
    if not isinstance(blind_review, dict):
        return [], ["blind review must be an object"]
    errors: list[str] = []
    if blind_review.get("complete") is not True:
        errors.append("blind review is not marked complete")
    reviews = blind_review.get("reviews")
    if not isinstance(reviews, list):
        errors.append("blind reviews must be a list")
        return [], errors
    entries: list[dict] = []
    for index, review in enumerate(reviews):
        if not isinstance(review, dict):
            errors.append(f"blind review entry must be an object: {index}")
            continue
        entries.append(review)
    stored_hash = blind_review.get("review_hash")
    if stored_hash is not None and (
        not isinstance(stored_hash, str)
        or stored_hash.strip() != blind_review_hash(blind_review)
    ):
        errors.append("blind review hash mismatch")
    return entries, errors


def _validate_entry(review: dict, card: dict) -> tuple[list[str], list[str]]:
    title = review.get("card_title")
    label = title.strip() if isinstance(title, str) else "<invalid-title>"
    errors: list[str] = []
    repeated_reason_candidates: list[str] = []

    status = review.get("status")
    if not isinstance(status, str):
        errors.append(f"blind review status must be a string: {label}")
    elif status != "pass":
        errors.append(f"blind review status is not pass: {label}")

    selected = review.get("selected_answer")
    if not _nonempty_string(selected):
        errors.append(f"blind review selected_answer must be a string: {label}")
        selected = ""
    else:
        selected = selected.strip()

    application = card.get("application")
    if not isinstance(application, dict):
        errors.append(f"frozen application payload must be an object: {label}")
        application = {}
    frozen_answer = application.get("answer")
    if not _nonempty_string(frozen_answer):
        errors.append(f"frozen application answer must be a string: {label}")
        frozen_answer = ""
    else:
        frozen_answer = frozen_answer.strip()
    if selected and frozen_answer and selected != frozen_answer:
        errors.append("blind answer disagrees with frozen answer")

    viable_options = review.get("viable_options")
    viable: list[str] = []
    if not isinstance(viable_options, list):
        errors.append(f"blind review viable_options must be a list: {label}")
    elif any(not _nonempty_string(option) for option in viable_options):
        errors.append(f"blind review viable_options must contain strings: {label}")
    else:
        viable = [option.strip() for option in viable_options]
        if len(viable) > 1:
            errors.append("blind review found multiple viable options")
        elif not viable:
            errors.append(f"blind review found no viable option: {label}")
        if len(set(viable)) != len(viable):
            errors.append(f"blind review repeats viable option: {label}")
        if len(viable) == 1 and selected and viable[0] != selected:
            errors.append(f"blind selected answer is not the viable option: {label}")

    decisive_clues = review.get("decisive_clues")
    clues: list[str] = []
    if not isinstance(decisive_clues, list):
        errors.append(f"blind review decisive_clues must be a list: {label}")
    elif any(not _nonempty_string(clue) for clue in decisive_clues):
        errors.append(f"blind review decisive_clues must contain strings: {label}")
    else:
        clues = [clue.strip() for clue in decisive_clues]
        if not clues:
            errors.append(f"blind review lacks decisive clues: {label}")

    if review.get("reviewer_context_isolated") is not True:
        errors.append(f"blind review reviewer_context_isolated must be true: {label}")
        errors.append(f"blind review is not context-isolated: {label}")
    if review.get("expected_answer_seen") is not False:
        errors.append(f"blind review expected_answer_seen must be false: {label}")
        if review.get("expected_answer_seen") is True:
            errors.append(f"blind review saw expected answer: {label}")

    options = application.get("options")
    if not isinstance(options, list) or any(not _nonempty_string(option) for option in options):
        errors.append(f"frozen application options must be a list of strings: {label}")
        options = []
    else:
        options = [option.strip() for option in options]
    distractors = [option for option in options if option != frozen_answer]
    rejections = review.get("distractor_rejections")
    if not isinstance(rejections, dict):
        errors.append(f"blind review distractor_rejections must be an object: {label}")
        rejections = {}
    elif any(
        not _nonempty_string(option) or not _nonempty_string(reason)
        for option, reason in rejections.items()
    ):
        errors.append(
            f"blind review distractor_rejections must map strings to strings: {label}"
        )
    for distractor in distractors:
        reason = rejections.get(distractor)
        if not _nonempty_string(reason) or len(reason.strip()) < 12:
            errors.append(f"blind review lacks distractor rejection: {label}:{distractor}")
            continue
        reason = reason.strip()
        normalized = _normalized_reason(reason.replace(distractor, ""))
        repeated_reason_candidates.append(normalized)
        if distractor not in reason or any(
            phrase in reason for phrase in GENERIC_REVIEW_PHRASES
        ):
            errors.append(
                f"blind review distractor rejection is not card-specific: {label}:{distractor}"
            )
    extra_rejections = set(rejections) - set(distractors)
    for distractor in sorted(str(value) for value in extra_rejections):
        errors.append(f"blind review has unknown distractor rejection: {label}:{distractor}")
    return errors, repeated_reason_candidates


def evaluate_blind_reviews(final_cards: dict, blind_review: dict) -> list[str]:
    """Return blind-solve review violations for application cards."""

    if not isinstance(blind_review, dict):
        return ["blind review must be an object"]
    application_cards, errors = _application_cards(final_cards)
    entries, review_errors = _review_entries(blind_review)
    errors.extend(review_errors)

    cards_by_title: dict[str, dict] = {}
    for card in application_cards:
        title = card.get("title")
        if not _nonempty_string(title):
            errors.append("application card title must be a string")
            continue
        cards_by_title[title.strip()] = card

    entry_titles = [
        entry.get("card_title").strip()
        for entry in entries
        if _nonempty_string(entry.get("card_title"))
    ]
    title_counts = Counter(entry_titles)
    for title, count in sorted(title_counts.items()):
        if count > 1:
            errors.append(f"duplicate blind review: {title}")
    for title in sorted(set(cards_by_title) - set(title_counts)):
        errors.append(f"missing blind review: {title}")
    for title in sorted(set(title_counts) - set(cards_by_title)):
        errors.append(f"unknown blind review: {title}")

    reason_owners: list[tuple[str, str]] = []
    for index, entry in enumerate(entries):
        title = entry.get("card_title")
        if not _nonempty_string(title):
            errors.append(f"blind review card_title must be a string: {index}")
            continue
        title = title.strip()
        card = cards_by_title.get(title)
        if card is None:
            continue
        entry_errors, reasons = _validate_entry(entry, card)
        errors.extend(entry_errors)
        reason_owners.extend((reason, title) for reason in reasons if reason)

    reason_counts = Counter(reason for reason, _ in reason_owners)
    repeated_titles = {
        title for reason, title in reason_owners if reason_counts[reason] > 1
    }
    for title in sorted(repeated_titles):
        errors.append(f"blind review repeats generic reason: {title}")
    return list(dict.fromkeys(errors))


def blind_review_hash(review: dict) -> str:
    """Return the canonical digest for a blind review artifact."""

    if not isinstance(review, dict):
        raise TypeError("blind review must be an object")
    payload = {key: value for key, value in review.items() if key != "review_hash"}
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
