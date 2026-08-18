"""Load and structurally audit an immutable Maimemo library snapshot."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .markji import ParsedCard, parse_card


def load_snapshot(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def audit_snapshot(snapshot: dict) -> dict:
    parsed: list[ParsedCard] = [parse_card(card) for card in snapshot.get("cards", [])]
    title_counts = Counter(card.title for card in parsed)
    duplicate_titles = sorted(
        title for title, count in title_counts.items() if count > 1
    )
    roots = {card.root_id for card in parsed if card.root_id}
    missing_targets = [
        {"title": card.title, "reference": reference}
        for card in parsed
        for reference in card.references
        if reference not in roots
    ]
    return {
        "total": len(parsed),
        "base": sum(card.card_type == "base" for card in parsed),
        "comparison": sum(card.card_type == "comparison" for card in parsed),
        "application": sum(card.card_type == "application" for card in parsed),
        "other": sum(card.card_type == "other" for card in parsed),
        "duplicate_titles": duplicate_titles,
        "missing_root_ids": [card.title for card in parsed if not card.root_id],
        "bad_grammar_versions": [
            {"title": card.title, "grammar_version": card.grammar_version}
            for card in parsed
            if card.grammar_version != 3
        ],
        "missing_reference_targets": missing_targets,
    }
