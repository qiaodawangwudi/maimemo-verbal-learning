"""Apply only a complete, guarded action plan in dependency-safe order."""

from __future__ import annotations

import re
import time
from typing import Callable

from .api import MaimemoClient
from .guard import GuardResult
from .planning import content_hash


ROOT_PLACEHOLDER = re.compile(r"\{\{root:([^}]+)\}\}")


def _chapter_cards(data: dict, chapter_id: str) -> list[dict]:
    chapter = next(
        (chapter for chapter in data.get("chapters", []) if chapter.get("id") == chapter_id),
        None,
    )
    if chapter is None:
        raise RuntimeError(f"chapter missing during readback: {chapter_id}")
    ids = set(chapter.get("card_ids", []))
    return [card for card in data.get("cards", []) if card.get("id") in ids]


def _apply_action(
    client: MaimemoClient,
    guard: GuardResult,
    action: dict,
    content: str,
    chapter_id: str,
) -> None:
    value = action["action"]
    if value == "update" or value == "repurpose":
        client.update_card(action["card_id"], content, guard)
    elif value == "create":
        client.create_card(chapter_id, content, guard)
    elif value != "unchanged":
        raise RuntimeError(f"unsafe action during sync: {value}")


def apply_plan(
    client: MaimemoClient,
    guard: GuardResult,
    plan: dict,
    final_cards: list[dict],
    chapter_id: str,
    *,
    pause: Callable[[], None] | None = None,
) -> dict:
    if not guard.ok:
        raise RuntimeError("sync requires approved guard")
    if chapter_id != plan.get("chapter_id"):
        raise RuntimeError("sync target chapter differs from approved plan")
    wait = pause or (lambda: time.sleep(1.6))
    actions = {action["title"]: action for action in plan.get("actions", [])}
    cards = {card["title"]: card for card in final_cards}
    for title in cards:
        if title not in actions:
            raise RuntimeError(f"card missing from approved plan: {title}")
        action = actions[title]
        raw_content = str(cards[title].get("content") or "")
        if action.get("content_hash") and action["content_hash"] != content_hash(raw_content):
            raise RuntimeError(f"content hash changed before write: {title}")
    comparison_titles = [
        title for title, card in cards.items() if card.get("card_type") == "comparison"
    ]
    base_titles = [title for title, card in cards.items() if card.get("card_type") == "base"]
    application_titles = [
        title for title, card in cards.items() if card.get("card_type") == "application"
    ]
    counts = {"create": 0, "update": 0, "repurpose": 0, "unchanged": 0}
    for index, title in enumerate(comparison_titles):
        action = actions[title]
        _apply_action(client, guard, action, cards[title]["content"], chapter_id)
        counts[action["action"]] += 1
        if action["action"] != "unchanged" and index < len(comparison_titles) - 1:
            wait()

    live_after_groups = _chapter_cards(client.read_deck(), chapter_id)
    roots: dict[str, str] = {}
    for card in live_after_groups:
        content = str(card.get("content") or "")
        if content.startswith("[P#H1#近义辨析｜"):
            title = content.split("]", 1)[0].removeprefix("[P#H1#")
            root_id = str(card.get("root_id") or "")
            if not root_id.startswith("mkjr_"):
                raise RuntimeError(f"invalid comparison root_id after write: {title}")
            roots[title] = root_id

    for index, title in enumerate(base_titles):
        action = actions[title]
        content = ROOT_PLACEHOLDER.sub(
            lambda match: roots.get(match.group(1))
            or (_ for _ in ()).throw(RuntimeError(f"missing comparison root: {match.group(1)}")),
            cards[title]["content"],
        )
        _apply_action(client, guard, action, content, chapter_id)
        counts[action["action"]] += 1
        if action["action"] != "unchanged" and index < len(base_titles) - 1:
            wait()
    for index, title in enumerate(application_titles):
        action = actions[title]
        _apply_action(client, guard, action, cards[title]["content"], chapter_id)
        counts[action["action"]] += 1
        if action["action"] != "unchanged" and index < len(application_titles) - 1:
            wait()
    return counts
