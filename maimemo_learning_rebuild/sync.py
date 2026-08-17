"""Apply only a complete, guarded action plan in dependency-safe order."""

from __future__ import annotations

import re
import time
from typing import Callable

from .api import MaimemoClient
from .guard import GuardResult
from .planning import content_hash


ROOT_PLACEHOLDER = re.compile(r"\{\{root:([^}]+)\}\}")
TITLE_PREFIX = re.compile(r"^\[P#H1#([^\]]+)\]")


def _chapter_cards(data: dict, chapter_id: str) -> list[dict]:
    chapter = next(
        (chapter for chapter in data.get("chapters", []) if chapter.get("id") == chapter_id),
        None,
    )
    if chapter is None:
        raise RuntimeError(f"chapter missing during readback: {chapter_id}")
    ids = set(chapter.get("card_ids", []))
    return [card for card in data.get("cards", []) if card.get("id") in ids]


def _cards_by_title(cards: list[dict]) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    for card in cards:
        match = TITLE_PREFIX.match(str(card.get("content") or ""))
        if not match:
            continue
        title = match.group(1)
        if title in indexed:
            raise RuntimeError(f"duplicate live card title blocks safe resume: {title}")
        indexed[title] = card
    return indexed


def _apply_routed_action(
    client: MaimemoClient,
    guard: GuardResult,
    action: dict,
    title: str,
    content: str,
    chapter_id: str,
    live_cards: dict[str, dict],
) -> str:
    """Apply one action, treating an identical prior create as safely completed."""

    if action["action"] == "create" and title in live_cards:
        live_content = str(live_cards[title].get("content") or "")
        if live_content != content:
            raise RuntimeError(f"existing routed card content differs: {title}")
        return "already_present"
    _apply_action(client, guard, action, content, chapter_id)
    return action["action"]


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


def apply_plan_to_chapters(
    client: MaimemoClient,
    guard: GuardResult,
    plan: dict,
    final_cards: list[dict],
    chapter_routes: dict[str, str],
    *,
    pause: Callable[[], None] | None = None,
) -> dict:
    """Apply one approved content plan while routing each card type to its chapter."""

    if not guard.ok:
        raise RuntimeError("sync requires approved guard")
    required_routes = {"comparison", "base", "application"}
    if set(chapter_routes) != required_routes or not all(chapter_routes.values()):
        raise RuntimeError("three complete chapter routes are required")
    wait = pause or (lambda: time.sleep(1.6))
    actions = {action["title"]: action for action in plan.get("actions", [])}
    cards = {card["title"]: card for card in final_cards}
    by_type = {
        card_type: [
            title for title, card in cards.items() if card.get("card_type") == card_type
        ]
        for card_type in required_routes
    }
    unknown_types = {
        str(card.get("card_type") or "") for card in cards.values()
    } - required_routes
    if unknown_types:
        raise RuntimeError(f"unsupported routed card types: {sorted(unknown_types)}")
    for title, card in cards.items():
        if title not in actions:
            raise RuntimeError(f"card missing from approved plan: {title}")
        action = actions[title]
        raw_content = str(card.get("content") or "")
        if action.get("content_hash") and action["content_hash"] != content_hash(raw_content):
            raise RuntimeError(f"content hash changed before write: {title}")

    counts = {
        "create": 0,
        "update": 0,
        "repurpose": 0,
        "unchanged": 0,
        "already_present": 0,
    }

    live_before = client.read_deck()
    live_by_type = {
        card_type: _cards_by_title(
            _chapter_cards(live_before, chapter_routes[card_type])
        )
        for card_type in required_routes
    }

    for title in by_type["comparison"]:
        action = actions[title]
        outcome = _apply_routed_action(
            client,
            guard,
            action,
            title,
            cards[title]["content"],
            chapter_routes["comparison"],
            live_by_type["comparison"],
        )
        counts[outcome] += 1
        if outcome not in {"unchanged", "already_present"}:
            wait()

    live_after_groups = client.read_deck()
    live_groups = _chapter_cards(live_after_groups, chapter_routes["comparison"])
    live_by_type["base"] = _cards_by_title(
        _chapter_cards(live_after_groups, chapter_routes["base"])
    )
    live_by_type["application"] = _cards_by_title(
        _chapter_cards(live_after_groups, chapter_routes["application"])
    )
    roots: dict[str, str] = {}
    for card in live_groups:
        content = str(card.get("content") or "")
        if content.startswith("[P#H1#近义辨析｜"):
            title = content.split("]", 1)[0].removeprefix("[P#H1#")
            root_id = str(card.get("root_id") or "")
            if not root_id.startswith("mkjr_"):
                raise RuntimeError(f"invalid comparison root_id after write: {title}")
            roots[title] = root_id

    for title in by_type["base"]:
        action = actions[title]
        content = ROOT_PLACEHOLDER.sub(
            lambda match: roots.get(match.group(1))
            or (_ for _ in ()).throw(
                RuntimeError(f"missing comparison root: {match.group(1)}")
            ),
            cards[title]["content"],
        )
        outcome = _apply_routed_action(
            client,
            guard,
            action,
            title,
            content,
            chapter_routes["base"],
            live_by_type["base"],
        )
        counts[outcome] += 1
        if outcome not in {"unchanged", "already_present"}:
            wait()

    for title in by_type["application"]:
        action = actions[title]
        outcome = _apply_routed_action(
            client,
            guard,
            action,
            title,
            cards[title]["content"],
            chapter_routes["application"],
            live_by_type["application"],
        )
        counts[outcome] += 1
        if outcome not in {"unchanged", "already_present"}:
            wait()
    return counts
