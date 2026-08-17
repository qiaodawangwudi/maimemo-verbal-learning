"""Verify a complete live readback against the approved final library."""

from __future__ import annotations

from collections import Counter
import os
import re

from .application_blind_review import strict_json_error
from .markji import parse_card
from .release_manifest import release_hash


ROOT_PLACEHOLDER = re.compile(r"\{\{root:([^}]+)\}\}")
ROUTE_KEYS = ("comparison", "base", "application")
ROUTE_COUNT_KEYS = {"before", "create", "update", "unchanged", "after"}
MANIFEST_FIELDS = {
    "schema_version",
    "release_id",
    "state",
    "state_evidence",
    "deck",
    "chapter_routes",
    "card_counts",
    "action_counts",
    "artifact_hashes",
    "release_hash",
}
TITLE_TYPES = {
    "近义辨析｜": "comparison",
    "基础词义｜": "base",
    "语境应用｜": "application",
}


def _add_error(errors: list[str], error: str) -> None:
    if error not in errors:
        errors.append(error)


def _title_type(title: str) -> str:
    for prefix, card_type in TITLE_TYPES.items():
        if title.startswith(prefix):
            return card_type
    return "other"


def _valid_route_title(title: str) -> bool:
    card_type = _title_type(title)
    prefix = next(
        (candidate for candidate, value in TITLE_TYPES.items() if value == card_type),
        "",
    )
    if not prefix:
        return False
    suffix = title.removeprefix(prefix).strip()
    if not suffix:
        return False
    if card_type != "comparison":
        return True
    members = [member.strip() for member in suffix.split("、")]
    return len(members) >= 2 and all(members) and len(members) == len(set(members))


def _valid_card_payload(title: str, content: str) -> bool:
    heading = f"[P#H1#{title}]"
    if not content.startswith(heading):
        return False
    separator = "\n---\n"
    separator_at = content.find(separator, len(heading))
    return separator_at >= 0 and bool(content[separator_at + len(separator) :].strip())


def _valid_root_id(root_id: str) -> bool:
    return bool(re.fullmatch(r"mkjr_\S+", root_id))


def verify_release_readback(
    live_deck: dict, expected_cards: list[dict], manifest: dict
) -> dict:
    """Verify every live card against one exact route-bound release manifest."""

    errors: list[str] = []
    github_run_id = os.environ.get("GITHUB_RUN_ID", "")
    stored_release_hash = (
        manifest.get("release_hash")
        if isinstance(manifest, dict) and isinstance(manifest.get("release_hash"), str)
        else ""
    )
    report = {
        "ok": False,
        "errors": errors,
        "release_hash": stored_release_hash,
        "github_run_id": github_run_id,
        "live_total": 0,
        "expected_total": 0,
        "verified_content": 0,
        "route_totals": {route: 0 for route in ROUTE_KEYS},
    }

    if not github_run_id:
        _add_error(errors, "GITHUB_RUN_ID is required")
    elif (
        not github_run_id.isascii()
        or not github_run_id.isdigit()
        or not github_run_id.strip("0")
    ):
        _add_error(errors, "GITHUB_RUN_ID must be a positive decimal string")

    input_errors = (
        ("live deck", live_deck),
        ("expected cards", expected_cards),
        ("release manifest", manifest),
    )
    invalid_json = set()
    for label, value in input_errors:
        try:
            json_error = strict_json_error(value)
        except RecursionError:
            json_error = "nesting exceeds validation limit"
        if json_error:
            _add_error(errors, f"{label} is not strict JSON")
            invalid_json.add(label)
    if invalid_json:
        return report

    if not isinstance(live_deck, dict):
        _add_error(errors, "live deck must be an object")
    if not isinstance(expected_cards, list):
        _add_error(errors, "expected cards must be a list")
    if not isinstance(manifest, dict):
        _add_error(errors, "release manifest must be an object")
    if errors and (
        not isinstance(live_deck, dict)
        or not isinstance(expected_cards, list)
        or not isinstance(manifest, dict)
    ):
        return report

    if set(manifest) != MANIFEST_FIELDS:
        _add_error(errors, "release manifest fields mismatch")
    if type(manifest.get("schema_version")) is not int or manifest.get("schema_version") != 2:
        _add_error(errors, "release manifest schema version mismatch")
    if not isinstance(manifest.get("release_id"), str) or not manifest["release_id"]:
        _add_error(errors, "release_id must be a nonempty string")
    if manifest.get("state") != "applied":
        _add_error(errors, "release manifest must be in applied state")
    if not isinstance(manifest.get("state_evidence"), dict):
        _add_error(errors, "state_evidence must be an object")
    action_counts = manifest.get("action_counts")
    if (
        not isinstance(action_counts, dict)
        or set(action_counts) != {"create", "update", "unchanged"}
        or any(
            type(action_counts.get(action)) is not int or action_counts[action] < 0
            for action in ("create", "update", "unchanged")
        )
    ):
        _add_error(errors, "manifest action counts are malformed")
    artifact_hashes = manifest.get("artifact_hashes")
    if not isinstance(artifact_hashes, dict):
        _add_error(errors, "artifact_hashes must be an object")
    elif any(
        not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
        for value in artifact_hashes.values()
    ):
        _add_error(errors, "artifact_hashes contains a malformed digest")
    if not isinstance(stored_release_hash, str) or not re.fullmatch(
        r"[0-9a-f]{64}", stored_release_hash
    ):
        _add_error(errors, "release_hash must be a sha256 digest")
    try:
        if stored_release_hash != release_hash(manifest):
            _add_error(errors, "release self-hash mismatch")
    except (TypeError, ValueError, OverflowError, RecursionError):
        _add_error(errors, "release self-hash mismatch")

    deck = manifest.get("deck")
    if (
        not isinstance(deck, dict)
        or set(deck) != {"id", "name"}
        or not isinstance(deck.get("id"), str)
        or not deck.get("id")
        or not isinstance(deck.get("name"), str)
        or not deck.get("name")
    ):
        _add_error(errors, "release deck binding is malformed")
        deck = {}
    elif live_deck.get("id") != deck["id"]:
        _add_error(errors, "deck id mismatch")
    elif live_deck.get("name") != deck["name"]:
        _add_error(errors, "deck name mismatch")

    routes = manifest.get("chapter_routes")
    if not isinstance(routes, dict) or set(routes) != set(ROUTE_KEYS):
        _add_error(errors, "chapter route keys mismatch")
        routes = routes if isinstance(routes, dict) else {}
    route_bindings: dict[str, dict] = {}
    route_ids: list[str] = []
    route_names: list[str] = []
    for route in ROUTE_KEYS:
        binding = routes.get(route)
        if not isinstance(binding, dict) or set(binding) != {"id", "name", "type", "counts"}:
            _add_error(errors, f"malformed chapter route: {route}")
            continue
        route_id = binding.get("id")
        route_name = binding.get("name")
        counts = binding.get("counts")
        if not isinstance(route_id, str) or not route_id:
            _add_error(errors, f"malformed chapter route: {route}")
            continue
        if not isinstance(route_name, str) or not route_name:
            _add_error(errors, f"malformed chapter route: {route}")
            continue
        if binding.get("type") != route:
            _add_error(errors, f"chapter route type mismatch: {route}")
        if not isinstance(counts, dict) or set(counts) != ROUTE_COUNT_KEYS or any(
            type(counts.get(key)) is not int or counts[key] < 0
            for key in ROUTE_COUNT_KEYS
        ):
            _add_error(errors, f"malformed chapter route counts: {route}")
        route_bindings[route] = binding
        route_ids.append(route_id)
        route_names.append(route_name)
    for route_id, count in Counter(route_ids).items():
        if count > 1:
            _add_error(errors, f"duplicate chapter route id: {route_id}")
    for route_name, count in Counter(route_names).items():
        if count > 1:
            _add_error(errors, f"duplicate chapter route name: {route_name}")

    expected_by_title: dict[str, dict] = {}
    expected_type_counts = Counter()
    for index, card in enumerate(expected_cards):
        if not isinstance(card, dict):
            _add_error(errors, f"expected card must be an object: {index}")
            continue
        title = card.get("title")
        content = card.get("content")
        card_type = card.get("card_type")
        if (
            not isinstance(title, str)
            or not title
            or not isinstance(content, str)
            or not content
            or card_type not in ROUTE_KEYS
        ):
            _add_error(errors, f"malformed expected card at index {index}")
            continue
        if title in expected_by_title:
            _add_error(errors, f"duplicate expected title: {title}")
            continue
        if _title_type(title) != card_type or not _valid_route_title(title):
            _add_error(errors, f"expected card type/title mismatch: {title}")
        if not _valid_card_payload(title, content):
            _add_error(errors, f"malformed expected card payload: {title}")
        expected_by_title[title] = card
        expected_type_counts[card_type] += 1
    report["expected_total"] = len(expected_cards)

    card_counts = manifest.get("card_counts")
    if (
        not isinstance(card_counts, dict)
        or set(card_counts) != {"before", "after"}
        or any(type(card_counts.get(key)) is not int or card_counts[key] < 0 for key in ("before", "after"))
    ):
        _add_error(errors, "manifest card counts are malformed")
        expected_total = None
    else:
        expected_total = card_counts["after"]
        if expected_total != len(expected_cards):
            _add_error(errors, "expected card total does not match manifest")
    for route in ROUTE_KEYS:
        binding = route_bindings.get(route)
        if isinstance(binding, dict) and isinstance(binding.get("counts"), dict):
            after = binding["counts"].get("after")
            if type(after) is int and after != expected_type_counts[route]:
                _add_error(errors, f"route count mismatch: {route}")

    cards = live_deck.get("cards")
    chapters = live_deck.get("chapters")
    if not isinstance(cards, list):
        _add_error(errors, "live deck cards must be a list")
        cards = []
    if not isinstance(chapters, list):
        _add_error(errors, "live deck chapters must be a list")
        chapters = []
    report["live_total"] = len(cards)
    if expected_total is not None and len(cards) != expected_total:
        _add_error(errors, f"live count mismatch: expected {expected_total} got {len(cards)}")

    raw_by_id: dict[str, dict] = {}
    parsed_by_id = {}
    parsed_cards = []
    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            _add_error(errors, f"malformed live card at index {index}")
            continue
        card_id = card.get("id")
        if not isinstance(card_id, str) or not card_id:
            _add_error(errors, f"malformed live card at index {index}")
            continue
        if card_id in raw_by_id:
            _add_error(errors, f"duplicate live card id: {card_id}")
            continue
        raw_by_id[card_id] = card
        try:
            parsed = parse_card(card)
        except (TypeError, ValueError):
            _add_error(errors, f"unparseable live card: {card_id}")
            continue
        parsed_cards.append(parsed)
        parsed_by_id[card_id] = parsed
        if not _valid_route_title(parsed.title):
            _add_error(errors, f"malformed card title: {parsed.title}")
        if not _valid_card_payload(parsed.title, parsed.content):
            _add_error(errors, f"malformed card payload: {parsed.title}")
        if not _valid_root_id(parsed.root_id):
            _add_error(errors, f"malformed root_id: {parsed.title}")
        if type(parsed.grammar_version) is not int or parsed.grammar_version != 3:
            _add_error(errors, f"grammar version mismatch: {parsed.title}")

    title_counts = Counter(card.title for card in parsed_cards)
    for title, count in title_counts.items():
        if count > 1:
            _add_error(errors, f"duplicate live title: {title}")
    root_counts = Counter(card.root_id for card in parsed_cards if card.root_id)
    for root_id, count in root_counts.items():
        if count > 1:
            _add_error(errors, f"duplicate live root_id: {root_id}")

    chapter_by_id: dict[str, dict] = {}
    chapter_names = Counter()
    for index, chapter in enumerate(chapters):
        if not isinstance(chapter, dict):
            _add_error(errors, f"malformed live chapter at index {index}")
            continue
        chapter_id = chapter.get("id")
        chapter_name = chapter.get("name")
        chapter_card_ids = chapter.get("card_ids")
        if (
            not isinstance(chapter_id, str)
            or not chapter_id
            or not isinstance(chapter_name, str)
            or not chapter_name
            or not isinstance(chapter_card_ids, list)
            or any(not isinstance(card_id, str) or not card_id for card_id in chapter_card_ids)
        ):
            _add_error(errors, f"malformed live chapter at index {index}")
            continue
        if chapter_id in chapter_by_id:
            _add_error(errors, f"duplicate live chapter id: {chapter_id}")
            continue
        chapter_by_id[chapter_id] = chapter
        chapter_names[chapter_name] += 1
    for chapter_name, count in chapter_names.items():
        if count > 1:
            _add_error(errors, f"duplicate live chapter name: {chapter_name}")

    assigned_routes: dict[str, list[str]] = {}
    for route in ROUTE_KEYS:
        binding = route_bindings.get(route)
        if not isinstance(binding, dict):
            continue
        chapter = chapter_by_id.get(binding["id"])
        if chapter is None:
            _add_error(errors, f"chapter id mismatch: {route}")
            continue
        if chapter["name"] != binding["name"]:
            _add_error(errors, f"chapter name mismatch: {route}")
            continue
        card_ids = chapter["card_ids"]
        report["route_totals"][route] = len(card_ids)
        if len(card_ids) != len(set(card_ids)):
            _add_error(errors, f"duplicate card assignment in {route} chapter")
        counts = binding.get("counts")
        if isinstance(counts, dict) and type(counts.get("after")) is int:
            if len(card_ids) != counts["after"]:
                _add_error(errors, f"route count mismatch: {route}")
        for card_id in card_ids:
            if card_id not in raw_by_id:
                _add_error(errors, f"chapter references missing live card: {card_id}")
                continue
            assigned_routes.setdefault(card_id, []).append(route)

    for card_id in raw_by_id:
        assignments = assigned_routes.get(card_id, [])
        if not assignments:
            _add_error(errors, f"unrouted live card: {card_id}")
        elif len(assignments) > 1:
            _add_error(errors, f"card assigned to multiple release chapters: {card_id}")
    for card_id, parsed in parsed_by_id.items():
        for route in assigned_routes.get(card_id, []):
            if parsed.card_type != route:
                _add_error(errors, f"wrong card type in {route} chapter")

    live_by_title = {card.title: card for card in parsed_cards}
    for title in sorted(set(live_by_title) - set(expected_by_title)):
        _add_error(errors, f"unplanned live title: {title}")
    comparison_roots = {
        parsed.title: parsed.root_id
        for card_id, parsed in parsed_by_id.items()
        if parsed.card_type == "comparison"
        and assigned_routes.get(card_id) == ["comparison"]
        and _valid_root_id(parsed.root_id)
    }
    valid_comparison_root_ids = set(comparison_roots.values())
    for title, expected in expected_by_title.items():
        live = live_by_title.get(title)
        if live is None:
            _add_error(errors, f"missing live title: {title}")
            continue
        expected_content = ROOT_PLACEHOLDER.sub(
            lambda match: comparison_roots.get(match.group(1), match.group(0)),
            expected["content"],
        )
        if ROOT_PLACEHOLDER.search(expected_content):
            _add_error(errors, f"unresolved root placeholder: {title}")
        if live.content != expected_content:
            _add_error(errors, f"content mismatch: {title}")
        for reference in live.references:
            if reference not in valid_comparison_root_ids:
                _add_error(errors, f"missing root reference target: {title} {reference}")
        if (
            live.content == expected_content
            and type(live.grammar_version) is int
            and live.grammar_version == 3
            and live.card_type == expected["card_type"]
            and assigned_routes.get(live.card_id) == [expected["card_type"]]
        ):
            report["verified_content"] += 1

    report["ok"] = not errors
    return report


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
    comparison_roots = {
        card.title: card.root_id
        for card in parsed
        if card.card_type == "comparison" and card.root_id
    }
    planned_titles = {action["title"] for action in plan.get("actions", [])}
    for title, expected in expected_by_title.items():
        live = live_by_title.get(title)
        expected_content = ROOT_PLACEHOLDER.sub(
            lambda match: comparison_roots.get(match.group(1), match.group(0)),
            str(expected["content"]),
        )
        if live is None:
            errors.append(f"missing live title: {title}")
        elif live.content != expected_content:
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
