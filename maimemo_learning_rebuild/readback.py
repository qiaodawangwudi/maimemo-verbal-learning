"""Verify a complete live readback against the approved final library."""

from __future__ import annotations

from collections import Counter

from .markji import parse_card


def verify_readback(live_cards: list[dict], expected_cards: list[dict], plan: dict) -> dict:
    errors: list[str] = []
    parsed = [parse_card(card) for card in live_cards]
    if len(live_cards) != plan.get("expected_after"):
        errors.append(
            f"live count mismatch: expected {plan.get('expected_after')} got {len(live_cards)}"
        )
    title_counts = Counter(card.title for card in parsed)
    for title, count in title_counts.items():
        if count > 1:
            errors.append(f"duplicate live title: {title}")
    live_by_title = {card.title: card for card in parsed}
    expected_by_title = {card["title"]: card for card in expected_cards}
    planned_titles = {action["title"] for action in plan.get("actions", [])}
    for title, expected in expected_by_title.items():
        live = live_by_title.get(title)
        if live is None:
            errors.append(f"missing live title: {title}")
        elif live.content != expected["content"]:
            errors.append(f"content mismatch: {title}")
        elif live.grammar_version != 3:
            errors.append(f"grammar version mismatch: {title}")
    for title in sorted(set(live_by_title) - planned_titles):
        errors.append(f"unplanned live title: {title}")
    root_ids = {card.root_id for card in parsed if card.root_id}
    for card in parsed:
        for reference in card.references:
            if reference not in root_ids:
                errors.append(f"missing root reference target: {card.title} {reference}")
    return {
        "ok": not errors,
        "errors": errors,
        "live_total": len(live_cards),
        "expected_total": plan.get("expected_after"),
        "verified_content": len(expected_by_title) - sum(
            error.startswith(("missing live title:", "content mismatch:", "grammar version mismatch:"))
            for error in errors
        ),
    }
