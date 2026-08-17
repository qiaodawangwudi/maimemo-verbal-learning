"""Execute an approved release without ever blindly retrying a mutation."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from datetime import datetime, timezone

from .api import (
    AmbiguousMutationError,
    RateLimitError,
)
from .application_blind_review import strict_json_error
from .guard import GuardResult
from .release_journal import ReleaseJournal
from .release_manifest import (
    ARTIFACT_KEYS,
    _parse_json_artifact,
    load_release_manifest_file,
    validate_release_manifest,
)


PHASES = (
    "precheck",
    "comparisons",
    "root_readback",
    "bases",
    "applications",
    "final_readback",
)
ROUTES = ("comparison", "base", "application")
TYPE_PREFIXES = {
    "comparison": "近义辨析｜",
    "base": "基础词义｜",
    "application": "语境应用｜",
}
TITLE = re.compile(r"^\[P#H1#([^\]]+)\]")
ROOT_PLACEHOLDER = re.compile(r"\{\{root:([^}]+)\}\}")
ROOT_TOKEN = r"mkjr_[A-Za-z0-9_.-]+"
ROOT_ID = re.compile(ROOT_TOKEN)
RELEASE_HASH = re.compile(r"[0-9a-fA-F]{64}")
PLACEHOLDER_REFERENCE = re.compile(
    r"\[Card#ID/\{\{root:([^{}]+)\}\}#([^\]]+)\]"
)
RESOLVED_REFERENCE = re.compile(rf"\[Card#ID/({ROOT_TOKEN})#([^\]]+)\]")
MAX_RATE_LIMIT_RETRIES = 8
VALIDATION_FIELDS = {
    "ok",
    "receipt",
    "release_id",
    "release_hash",
    "github_run_id",
}
ARTIFACT_FILENAMES = {
    "source_inventory": ("source_inventory.json",),
    "semantic_registry": ("semantic_registry.json", "master_semantic_registry.json"),
    "group_registry": ("group_registry.json",),
    "application_review": ("application_review.json",),
    "blind_review": ("blind_review.json", "application_blind_review.json"),
    "final_cards": ("final_cards.json",),
    "snapshot": ("snapshot.json",),
    "action_plan": ("action_plan.json",),
    "quality_reports": ("quality_reports.json",),
    "engine_tree": ("engine_tree", "engine_tree.txt", "engine_tree.bin"),
    "skill_tree": ("skill_tree", "skill_tree.txt", "skill_tree.bin"),
}


class FrozenCards(list):
    """List payload carrying the separately hash-bound baseline snapshot."""

    def __init__(self, cards, snapshot):
        super().__init__(cards)
        self.snapshot = snapshot


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_strict_json(value, label):
    try:
        error = strict_json_error(value)
    except RecursionError:
        error = "nesting exceeds validation limit"
    if error:
        verb = "are" if label == "cards" else "is"
        raise RuntimeError(f"{label} {verb} not strict JSON")


def _expected_stable_key(title, card_type):
    prefix = TYPE_PREFIXES[card_type]
    return f"{card_type}:{title.removeprefix(prefix).replace('｜', ':')}"


def _title(content):
    match = TITLE.match(content if isinstance(content, str) else "")
    return match.group(1) if match else ""


def _card_type(title):
    return next(
        (card_type for card_type, prefix in TYPE_PREFIXES.items() if title.startswith(prefix)),
        "",
    )


def _route_ids(manifest):
    routes = manifest.get("chapter_routes")
    if not isinstance(routes, dict) or set(routes) != set(ROUTES):
        raise RuntimeError("release manifest requires three exact chapter routes")
    values = {}
    for route in ROUTES:
        item = routes.get(route)
        if not isinstance(item, dict) or item.get("type") != route:
            raise RuntimeError(f"invalid release route: {route}")
        route_id = item.get("id")
        if not isinstance(route_id, str) or not route_id:
            raise RuntimeError(f"invalid release route id: {route}")
        values[route] = route_id
    if len(set(values.values())) != len(ROUTES):
        raise RuntimeError("release route ids must be unique")
    return values


def _validate_manifest_shape(manifest, cards):
    release_id = manifest.get("release_id")
    release_hash = manifest.get("release_hash")
    if not isinstance(release_id, str) or not release_id:
        raise RuntimeError("release id is required")
    if not isinstance(release_hash, str) or not RELEASE_HASH.fullmatch(release_hash):
        raise RuntimeError("release manifest hash is invalid")
    deck = manifest.get("deck")
    if (
        not isinstance(deck, dict)
        or set(deck) != {"id", "name"}
        or any(not isinstance(deck.get(field), str) or not deck[field] for field in deck)
    ):
        raise RuntimeError("manifest deck identity is invalid")
    _route_ids(manifest)
    route_names = set()
    for route in ROUTES:
        item = manifest["chapter_routes"][route]
        if set(item) != {"id", "name", "type", "counts"}:
            raise RuntimeError(f"invalid release route fields: {route}")
        name = item.get("name")
        if not isinstance(name, str) or not name or name in route_names:
            raise RuntimeError(f"invalid or duplicate release route name: {route}")
        route_names.add(name)
        counts = item.get("counts")
        expected_counts = {
            "before": sum(
                card["card_type"] == route and card["action"] != "create"
                for card in cards
            ),
            "create": sum(
                card["card_type"] == route and card["action"] == "create"
                for card in cards
            ),
            "update": sum(
                card["card_type"] == route and card["action"] == "update"
                for card in cards
            ),
            "unchanged": sum(
                card["card_type"] == route and card["action"] == "unchanged"
                for card in cards
            ),
            "after": sum(card["card_type"] == route for card in cards),
        }
        if (
            not isinstance(counts, dict)
            or set(counts) != set(expected_counts)
            or counts != expected_counts
            or any(type(value) is not int or value < 0 for value in counts.values())
        ):
            raise RuntimeError(f"manifest route counts differ from cards: {route}")


def _normalize_cards(cards):
    if isinstance(cards, dict):
        cards = cards.get("cards")
    if not isinstance(cards, list):
        raise RuntimeError("frozen final cards must be a list")
    _require_strict_json(cards, "cards")
    normalized = []
    stable_keys = set()
    titles = set()
    frozen_card_ids = set()
    for index, value in enumerate(cards):
        if not isinstance(value, dict):
            raise RuntimeError(f"frozen card must be an object: {index}")
        required = ("stable_card_key", "title", "card_type", "action", "content")
        if any(not isinstance(value.get(field), str) for field in required):
            raise RuntimeError(f"frozen card fields are invalid: {index}")
        if value["card_type"] not in ROUTES or value["action"] not in {
            "create",
            "update",
            "unchanged",
        }:
            raise RuntimeError(f"frozen card route or action is invalid: {value['title']}")
        if _card_type(value["title"]) != value["card_type"]:
            raise RuntimeError(f"frozen card title route mismatch: {value['title']}")
        if value["stable_card_key"] != _expected_stable_key(
            value["title"], value["card_type"]
        ):
            raise RuntimeError(f"stable card key does not match title: {value['title']}")
        content_title = _title(value["content"])
        if content_title != value["title"]:
            raise RuntimeError(f"content title differs from declared title: {value['title']}")
        if value["stable_card_key"] in stable_keys or value["title"] in titles:
            raise RuntimeError(f"duplicate frozen stable key or title: {value['title']}")
        card_id = value.get("card_id", "")
        if not isinstance(card_id, str):
            raise RuntimeError(f"frozen card id is invalid: {value['title']}")
        if value["action"] in {"update", "unchanged"}:
            if not card_id:
                raise RuntimeError(f"frozen card id is required: {value['title']}")
            if card_id in frozen_card_ids:
                raise RuntimeError(f"duplicate frozen card id: {card_id}")
            frozen_card_ids.add(card_id)
        elif card_id:
            raise RuntimeError(f"create card id must be empty: {value['title']}")
        stable_keys.add(value["stable_card_key"])
        titles.add(value["title"])
        normalized.append(dict(value))
    comparison_titles = {
        value["title"] for value in normalized if value["card_type"] == "comparison"
    }
    for value in normalized:
        content = value["content"]
        placeholder_matches = list(PLACEHOLDER_REFERENCE.finditer(content))
        placeholder_remainder = PLACEHOLDER_REFERENCE.sub("", content)
        if "{{" in placeholder_remainder or "}}" in placeholder_remainder:
            raise RuntimeError(f"malformed root placeholder: {value['title']}")
        if placeholder_matches and value["card_type"] != "base":
            raise RuntimeError(f"root placeholder is not permitted: {value['title']}")
        for match in placeholder_matches:
            target, label = match.groups()
            if target != label or target not in comparison_titles:
                raise RuntimeError(f"invalid root placeholder target: {value['title']}")
        reference_matches = _parse_resolved_references(
            placeholder_remainder, value["title"]
        )
        if reference_matches and value["card_type"] != "base":
            raise RuntimeError(f"root reference is not permitted: {value['title']}")
        for match in reference_matches:
            root_id, label = match.groups()
            if not _valid_root(root_id) or label not in comparison_titles:
                raise RuntimeError(f"invalid root reference: {value['title']}")
    return normalized


def _index_live(deck, manifest, *, require_routes, snapshot=False):
    _require_strict_json(deck, "snapshot" if snapshot else "live deck")
    if not isinstance(deck, dict) or not isinstance(deck.get("cards"), list):
        raise RuntimeError("live deck readback is malformed")
    if require_routes:
        if not isinstance(deck.get("id"), str) or not deck.get("id"):
            raise RuntimeError("live deck id is required")
        if not isinstance(deck.get("name"), str) or not deck.get("name"):
            raise RuntimeError("live deck name is required")
    route_ids = _route_ids(manifest)
    cards_by_id = {}
    root_ids = set()
    for index, value in enumerate(deck["cards"]):
        if not isinstance(value, dict):
            raise RuntimeError(f"malformed live card at index {index}")
        card_id = value.get("id")
        if not isinstance(card_id, str) or not card_id:
            raise RuntimeError(f"malformed live card id at index {index}")
        if card_id in cards_by_id:
            raise RuntimeError(f"duplicate live card id: {card_id}")
        root_id = value.get("root_id")
        if not _valid_root(root_id):
            parsed_title = _title(value.get("content"))
            if _card_type(parsed_title) == "comparison":
                raise RuntimeError(f"invalid comparison root_id: {parsed_title}")
            raise RuntimeError(f"malformed live root id: {card_id}")
        if root_id in root_ids:
            raise RuntimeError(f"duplicate live root id: {root_id}")
        if type(value.get("grammar_version")) is not int or value.get("grammar_version") != 3:
            raise RuntimeError(f"malformed live grammar version: {card_id}")
        if not isinstance(value.get("content"), str):
            raise RuntimeError(f"malformed live card content: {card_id}")
        cards_by_id[card_id] = value
        root_ids.add(root_id)
    indexed = {route: {} for route in ROUTES}
    chapters = deck.get("chapters")
    if chapters is not None and not isinstance(chapters, list):
        label = "live deck" if require_routes else "snapshot"
        raise RuntimeError(f"{label} chapters must be a list")
    if isinstance(chapters, list):
        chapters_by_id = {}
        for index, value in enumerate(chapters):
            if not isinstance(value, dict):
                raise RuntimeError(f"malformed live chapter at index {index}")
            chapter_id = value.get("id")
            if not isinstance(chapter_id, str) or not chapter_id:
                raise RuntimeError(f"malformed live chapter id at index {index}")
            if chapter_id in chapters_by_id:
                raise RuntimeError(f"duplicate live chapter id: {chapter_id}")
            if not isinstance(value.get("name"), str) or not value.get("name"):
                raise RuntimeError(f"malformed live chapter name: {chapter_id}")
            card_ids = value.get("card_ids")
            if not isinstance(card_ids, list) or any(
                not isinstance(card_id, str) or not card_id for card_id in card_ids
            ):
                raise RuntimeError(f"live route card ids are malformed: {chapter_id}")
            if len(card_ids) != len(set(card_ids)):
                raise RuntimeError(f"duplicate card id in live chapter: {chapter_id}")
            chapters_by_id[chapter_id] = value
        if require_routes:
            for route, route_id in route_ids.items():
                if route_id not in chapters_by_id:
                    label = "snapshot" if snapshot else "release target"
                    raise RuntimeError(f"{label} route is missing: {route}")
        if snapshot and set(chapters_by_id) != set(route_ids.values()):
            raise RuntimeError("snapshot must contain exactly the three release routes")
        routed_card_ids = set()
        for route, route_id in route_ids.items():
            chapter = chapters_by_id.get(route_id)
            if not isinstance(chapter, dict):
                continue
            expected_name = manifest["chapter_routes"][route].get("name")
            if chapter.get("name") != expected_name:
                raise RuntimeError(f"chapter name mismatch: {route}")
            for card_id in chapter["card_ids"]:
                routed_card_ids.add(card_id)
                value = cards_by_id.get(card_id)
                if value is None:
                    raise RuntimeError(f"live route references missing card: {route}")
                title = _title(value.get("content"))
                if not title:
                    raise RuntimeError(f"unparseable live card: {card_id}")
                if title in indexed[route]:
                    raise RuntimeError(f"duplicate live card title blocks safe resume: {title}")
                if _card_type(title) != route:
                    raise RuntimeError(f"live card is in wrong route: {title}")
                indexed[route][title] = value
        if snapshot and routed_card_ids != set(cards_by_id):
            raise RuntimeError("snapshot card is not in an exact release route")
        return indexed
    if require_routes:
        raise RuntimeError("live deck has no chapter routes")
    for value in cards_by_id.values():
        title = _title(value.get("content"))
        route = _card_type(title)
        if route:
            if title in indexed[route]:
                raise RuntimeError(f"duplicate snapshot card title: {title}")
            indexed[route][title] = value
    return indexed


def _valid_root(value):
    return isinstance(value, str) and bool(ROOT_ID.fullmatch(value))


def _parse_resolved_references(content, title):
    if "{{" in content or "}}" in content:
        raise RuntimeError(f"unresolved root placeholder: {title}")
    matches = list(RESOLVED_REFERENCE.finditer(content))
    if "[Card#ID/" in RESOLVED_REFERENCE.sub("", content):
        raise RuntimeError(f"malformed root reference: {title}")
    return matches


def _root_map(indexed, cards):
    roots = {}
    seen_root_ids = set()
    for card in cards:
        if card["card_type"] != "comparison":
            continue
        live = indexed["comparison"].get(card["title"])
        if live is None:
            raise RuntimeError(f"comparison missing during root readback: {card['title']}")
        if not _valid_root(live.get("root_id")):
            raise RuntimeError(f"invalid comparison root_id after write: {card['title']}")
        if live["root_id"] in seen_root_ids:
            raise RuntimeError(f"duplicate live root id: {live['root_id']}")
        roots[card["title"]] = live["root_id"]
        seen_root_ids.add(live["root_id"])
    return roots


def _resolve_content(content, roots):
    def replace(match):
        root = roots.get(match.group(1))
        if not root:
            raise RuntimeError(f"missing comparison root: {match.group(1)}")
        return root

    return ROOT_PLACEHOLDER.sub(replace, content)


def _resolved_if_possible(cards, indexed):
    roots = {}
    for card in cards:
        if card["card_type"] == "comparison":
            live = indexed["comparison"].get(card["title"])
            if live is not None and _valid_root(live.get("root_id")):
                roots[card["title"]] = live["root_id"]
    resolved = {}
    for card in cards:
        content = card["content"]
        try:
            content = _resolve_content(content, roots)
        except RuntimeError:
            pass
        resolved[card["title"]] = content
    return resolved


def _live_state(route, card):
    if card is None:
        return None
    return {
        "route": route,
        "id": card.get("id"),
        "root_id": card.get("root_id"),
        "grammar_version": card.get("grammar_version"),
        "content": card.get("content"),
    }


def _matches_frozen_immutable(route, frozen, live):
    if frozen is None or live is None:
        return False
    frozen_state = _live_state(route, frozen)
    live_state = _live_state(route, live)
    return all(
        frozen_state[field] == live_state[field]
        for field in ("route", "id", "root_id", "grammar_version")
    )


def _matches_final(card, frozen, live, resolved, route):
    if live is None or live.get("content") != resolved[card["title"]]:
        return False
    if card["action"] in {"update", "unchanged"}:
        return _matches_frozen_immutable(route, frozen, live)
    return frozen is None


def _precheck(client, manifest, cards, snapshot):
    live_deck = client.read_deck()
    live = _index_live(live_deck, manifest, require_routes=True)
    expected_deck = manifest.get("deck")
    if not isinstance(expected_deck, dict) or live_deck.get("id") != expected_deck.get("id"):
        raise RuntimeError("release target deck differs from frozen manifest")
    if live_deck.get("name") != expected_deck.get("name"):
        raise RuntimeError("release target deck name differs from frozen manifest")
    if (
        snapshot.get("id") != expected_deck.get("id")
        or snapshot.get("name") != expected_deck.get("name")
    ):
        raise RuntimeError("frozen snapshot deck identity differs from manifest")
    if not isinstance(snapshot.get("chapters"), list):
        raise RuntimeError("snapshot chapters must be a list")
    frozen = _index_live(
        snapshot, manifest, require_routes=True, snapshot=True
    )
    expected = {card["title"]: card for card in cards}
    resolved = _resolved_if_possible(cards, live)
    for route in ROUTES:
        expected_titles = {
            card["title"] for card in cards if card["card_type"] == route
        }
        if (set(frozen[route]) | set(live[route])) - expected_titles:
            raise RuntimeError(f"release target snapshot is stale: {route}")
        for title in sorted(expected):
            if expected[title]["card_type"] != route:
                continue
            before = frozen[route].get(title)
            current = live[route].get(title)
            final = expected.get(title)
            if final["action"] == "create" and before is not None:
                raise RuntimeError(f"create card exists in frozen snapshot: {title}")
            if final["action"] in {"update", "unchanged"}:
                if before is None or before.get("id") != final.get("card_id"):
                    raise RuntimeError(f"frozen card id drift: {title}")
                if current is not None and current.get("id") != final.get("card_id"):
                    raise RuntimeError(f"card id drift: {title}")
                if current is not None and not _matches_frozen_immutable(
                    route, before, current
                ):
                    raise RuntimeError(f"immutable frozen card drift: {title}")
            if _live_state(route, before) == _live_state(route, current):
                continue
            if _matches_final(final, before, current, resolved, route):
                continue
            if (
                current is not None
                and final["action"] in {"update", "unchanged"}
                and current.get("id") != final.get("card_id")
            ):
                raise RuntimeError(f"card id drift: {title}")
            if before is None and current is not None and final is not None and final["action"] == "create":
                raise RuntimeError(f"same title has different content: {title}")
            raise RuntimeError(f"release target snapshot is stale: {title}")
    return {
        card["title"]: _live_state(
            card["card_type"], live[card["card_type"]].get(card["title"])
        )
        for card in cards
    }


def _cancelled(wait_policy):
    callback = getattr(wait_policy, "cancelled", None)
    return bool(callback()) if callable(callback) else False


def _wait(wait_policy, seconds):
    if _cancelled(wait_policy):
        raise RuntimeError("release cancelled")
    callback = getattr(wait_policy, "wait", None)
    if callable(callback):
        callback(seconds)
    elif callable(wait_policy):
        try:
            wait_policy(seconds)
        except TypeError:
            wait_policy()
    else:
        raise RuntimeError("release wait policy is invalid")
    if _cancelled(wait_policy):
        raise RuntimeError("release cancelled")


def _record(journal, manifest, **fields):
    entry = {
        "release_hash": str(manifest.get("release_hash") or ""),
        "timestamp": _now(),
        "github_run_id": os.environ.get("GITHUB_RUN_ID", ""),
    }
    entry.update({key: value for key, value in fields.items() if value not in (None, "")})
    journal.record(entry)


def _phase(journal, manifest, phase):
    _record(journal, manifest, title=phase, action="phase", outcome="started")


def _read_live_release(client, manifest):
    deck = client.read_deck()
    expected_deck = manifest["deck"]
    if deck.get("id") != expected_deck.get("id") or deck.get("name") != expected_deck.get("name"):
        raise RuntimeError("release-wide live drift: deck identity")
    return _index_live(deck, manifest, require_routes=True)


def _assert_exact_root_map(indexed, cards, required_roots):
    if required_roots is None:
        return
    current = _root_map(indexed, cards)
    if current != required_roots:
        raise RuntimeError("release-wide live drift: comparison root mapping")


def _gate_release(client, manifest, cards, baseline, completed, required_roots):
    indexed = _read_live_release(client, manifest)
    expected_by_route = {route: set() for route in ROUTES}
    for card in cards:
        state = completed.get(card["title"], baseline[card["title"]])
        if state is not None:
            expected_by_route[card["card_type"]].add(card["title"])
        current = _live_state(
            card["card_type"], indexed[card["card_type"]].get(card["title"])
        )
        if current != state:
            if state is None and current is not None:
                raise RuntimeError(
                    f"release-wide live drift: live content drift before mutation: {card['title']}"
                )
            raise RuntimeError(f"release-wide live drift: {card['title']}")
    for route in ROUTES:
        if set(indexed[route]) != expected_by_route[route]:
            raise RuntimeError(f"release-wide live drift: {route} route membership")
    _assert_exact_root_map(indexed, cards, required_roots)
    return indexed


def _exact_written(card, live, content, frozen_state):
    if live is None or live.get("content") != content:
        return False
    if card["action"] in {"update", "unchanged"}:
        live_state = _live_state(card["card_type"], live)
        return frozen_state is not None and all(
            live_state[field] == frozen_state[field]
            for field in ("route", "id", "root_id", "grammar_version")
        )
    return True


def _assert_content_root_mapping(card, content, roots):
    matches = _parse_resolved_references(content, card["title"])
    if not matches:
        return
    if card["card_type"] != "base" or roots is None:
        raise RuntimeError(f"root reference mapping is unavailable: {card['title']}")
    for match in matches:
        root_id, label = match.groups()
        if roots.get(label) != root_id:
            raise RuntimeError(f"root reference mapping mismatch: {card['title']} {label}")


def _write_action(
    client,
    manifest,
    cards,
    card,
    content,
    guard,
    baseline,
    completed,
    required_roots,
    wait_policy,
):
    rate_limits = 0
    while True:
        if _cancelled(wait_policy):
            raise RuntimeError("release cancelled")
        indexed = _gate_release(
            client, manifest, cards, baseline, completed, required_roots
        )
        _assert_content_root_mapping(card, content, required_roots)
        live = indexed[card["card_type"]].get(card["title"])
        if card["action"] in {"update", "unchanged"} and (
            live is None or live.get("id") != card.get("card_id")
        ):
            raise RuntimeError(f"card id drift: {card['title']}")
        if _exact_written(card, live, content, baseline[card["title"]]):
            return ("unchanged" if card["action"] == "unchanged" else "already_present"), live
        if card["action"] == "unchanged":
            raise RuntimeError(f"unchanged frozen content differs live: {card['title']}")
        if card["action"] == "create" and live is not None:
            raise RuntimeError(f"same title has different content: {card['title']}")
        try:
            if card["action"] == "create":
                client.create_card(_route_ids(manifest)[card["card_type"]], content, guard)
            else:
                client.update_card(card["card_id"], content, guard)
            readback = _read_live_release(client, manifest)
            written = readback[card["card_type"]].get(card["title"])
            if not _exact_written(
                card, written, content, baseline[card["title"]]
            ):
                raise AmbiguousMutationError(
                    f"mutation result did not read back exactly: {card['title']}"
                )
            return card["action"], written
        except RateLimitError as error:
            readback_index = _read_live_release(client, manifest)
            readback = readback_index[card["card_type"]].get(card["title"])
            if _exact_written(
                card, readback, content, baseline[card["title"]]
            ):
                return "recovered_after_ambiguous_response", readback
            rate_limits += 1
            if rate_limits > MAX_RATE_LIMIT_RETRIES:
                raise RuntimeError(f"rate limit retry budget exhausted: {card['title']}") from error
            _wait(wait_policy, error.retry_after_seconds)
        except AmbiguousMutationError:
            readback_index = _read_live_release(client, manifest)
            readback = readback_index[card["card_type"]].get(card["title"])
            if _exact_written(
                card, readback, content, baseline[card["title"]]
            ):
                return "recovered_after_ambiguous_response", readback
            raise


def _record_card(journal, manifest, card, content, outcome, live):
    card_type = card["card_type"]
    chapter = manifest["chapter_routes"][card_type]
    _record(
        journal,
        manifest,
        title=card["title"],
        action=card["action"],
        stable_card_key=card["stable_card_key"],
        card_type=card_type,
        chapter_id=chapter["id"],
        chapter_name=chapter["name"],
        card_id=live.get("id") if live else card.get("card_id"),
        root_id=live.get("root_id") if live else None,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        outcome=outcome,
    )


def _verify_final(live_deck, manifest, cards, resolved, completed):
    errors = []
    try:
        _require_strict_json(live_deck, "live deck")
    except RuntimeError as error:
        return {
            "ok": False,
            "errors": [str(error)],
            "release_hash": str(manifest.get("release_hash") or ""),
            "github_run_id": os.environ.get("GITHUB_RUN_ID", ""),
            "live_total": 0,
            "expected_total": len(cards),
            "verified_content": 0,
            "route_totals": {route: 0 for route in ROUTES},
        }
    expected_deck = manifest.get("deck")
    if isinstance(expected_deck, dict):
        if live_deck.get("id") != expected_deck.get("id"):
            errors.append("deck id mismatch")
        if live_deck.get("name") != expected_deck.get("name"):
            errors.append("deck name mismatch")
    try:
        indexed = _index_live(live_deck, manifest, require_routes=True)
    except RuntimeError as error:
        indexed = {route: {} for route in ROUTES}
        errors.append(str(error))
    expected = {
        route: {card["title"]: card for card in cards if card["card_type"] == route}
        for route in ROUTES
    }
    verified = 0
    route_totals = {route: len(indexed[route]) for route in ROUTES}
    try:
        live_roots = _root_map(indexed, cards)
    except RuntimeError as error:
        live_roots = {}
        errors.append(str(error))
    comparison_titles = {
        card["title"] for card in cards if card["card_type"] == "comparison"
    }
    for route in ROUTES:
        live_titles = set(indexed[route])
        expected_titles = set(expected[route])
        errors.extend(f"missing live title: {title}" for title in sorted(expected_titles - live_titles))
        errors.extend(f"unplanned live title: {title}" for title in sorted(live_titles - expected_titles))
        for title in sorted(live_titles & expected_titles):
            live = indexed[route][title]
            card = expected[route][title]
            if live.get("content") != resolved[title]:
                errors.append(f"content mismatch: {title}")
            elif type(live.get("grammar_version")) is not int or live.get("grammar_version") != 3:
                errors.append(f"grammar version mismatch: {title}")
            elif not _valid_root(live.get("root_id")):
                errors.append(f"malformed root_id: {title}")
            else:
                verified += 1
            if card["action"] in {"update", "unchanged"} and live.get("id") != card.get("card_id"):
                errors.append(f"card id mismatch: {title}")
            if title in completed and _live_state(route, live) != completed[title]:
                errors.append(f"completed outcome drift: {title}")
            live_content = str(live.get("content") or "")
            try:
                reference_matches = _parse_resolved_references(
                    live_content, title
                )
            except RuntimeError as error:
                reference_matches = []
                errors.append(str(error))
            for match in reference_matches:
                root_id, label = match.groups()
                if root_id not in set(live_roots.values()):
                    errors.append(f"missing root reference target: {title} {root_id}")
                if label not in comparison_titles or live_roots.get(label) != root_id:
                    errors.append(f"root reference mapping mismatch: {title} {label}")
            for match in PLACEHOLDER_REFERENCE.finditer(card["content"]):
                target, label = match.groups()
                expected_root = live_roots.get(target)
                expected_reference = f"[Card#ID/{expected_root}#{label}]"
                if not expected_root or expected_reference not in live_content:
                    errors.append(f"placeholder root mapping mismatch: {title} {target}")
        counts = manifest["chapter_routes"][route].get("counts")
        if isinstance(counts, dict) and counts.get("after") != len(indexed[route]):
            errors.append(f"route count mismatch: {route}")
    return {
        "ok": not errors,
        "errors": errors,
        "release_hash": str(manifest.get("release_hash") or ""),
        "github_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "live_total": sum(route_totals.values()),
        "expected_total": len(cards),
        "verified_content": verified,
        "route_totals": route_totals,
    }


def execute_release(client, manifest, cards, journal, wait_policy):
    """Execute exact phases with live reads as the source of truth for resume."""
    if not isinstance(manifest, dict) or not isinstance(manifest.get("release_hash"), str):
        raise RuntimeError("release manifest hash is required")
    snapshot = getattr(cards, "snapshot", manifest.get("snapshot"))
    if snapshot is None:
        raise RuntimeError("snapshot is required")
    _require_strict_json(snapshot, "snapshot")
    _require_strict_json(manifest, "manifest")
    normalized = _normalize_cards(cards)
    _validate_manifest_shape(manifest, normalized)
    if not journal.acquire():
        raise RuntimeError("release writer is already running")
    try:
        if _cancelled(wait_policy):
            raise RuntimeError("release cancelled")
        _phase(journal, manifest, "precheck")
        baseline = _precheck(client, manifest, normalized, snapshot)
        guard = GuardResult(
            True,
            (),
            manifest["release_hash"],
            str(
                manifest.get("artifact_hashes", {}).get("quality_reports")
                or manifest["release_hash"]
            ),
        )
        counts = {
            "create": 0,
            "update": 0,
            "unchanged": 0,
            "already_present": 0,
            "recovered_after_ambiguous_response": 0,
        }
        resolved = {card["title"]: card["content"] for card in normalized}
        completed = {}
        _phase(journal, manifest, "comparisons")
        for card in (value for value in normalized if value["card_type"] == "comparison"):
            outcome, live = _write_action(
                client,
                manifest,
                normalized,
                card,
                card["content"],
                guard,
                baseline,
                completed,
                None,
                wait_policy,
            )
            counts[outcome] += 1
            completed[card["title"]] = _live_state(card["card_type"], live)
            _record_card(journal, manifest, card, card["content"], outcome, live)
        _phase(journal, manifest, "root_readback")
        root_index = _gate_release(
            client, manifest, normalized, baseline, completed, None
        )
        roots = _root_map(root_index, normalized)
        for card in normalized:
            if card["card_type"] == "base":
                resolved[card["title"]] = _resolve_content(card["content"], roots)
        for phase, route in (("bases", "base"), ("applications", "application")):
            _phase(journal, manifest, phase)
            for card in (value for value in normalized if value["card_type"] == route):
                content = resolved[card["title"]]
                outcome, live = _write_action(
                    client,
                    manifest,
                    normalized,
                    card,
                    content,
                    guard,
                    baseline,
                    completed,
                    roots,
                    wait_policy,
                )
                counts[outcome] += 1
                completed[card["title"]] = _live_state(card["card_type"], live)
                _record_card(journal, manifest, card, content, outcome, live)
        _phase(journal, manifest, "final_readback")
        final = _verify_final(
            client.read_deck(), manifest, normalized, resolved, completed
        )
        return {**counts, "phases": list(PHASES), "final_readback": final}
    finally:
        journal.release()


def _is_link_or_reparse(path):
    path = Path(path)
    try:
        metadata = os.lstat(path)
    except OSError:
        return path.is_symlink()
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & reparse_flag)


def _reject_link_components(path):
    absolute = Path(os.path.abspath(os.fspath(path)))
    for component in reversed((absolute, *absolute.parents)):
        if component == Path(component.anchor):
            continue
        if _is_link_or_reparse(component):
            raise RuntimeError(f"frozen release path contains a symbolic link or reparse point")
    return absolute


def _canonical_release_dir(release_dir):
    lexical = _reject_link_components(release_dir)
    try:
        canonical = lexical.resolve(strict=True)
    except OSError as error:
        raise RuntimeError("frozen release directory is missing") from error
    if canonical != lexical or not canonical.is_dir():
        raise RuntimeError("frozen release directory is not a canonical directory")
    return canonical


def validate_release_directory(repository, release_path):
    """Return one non-linked release directory strictly below checkout/releases."""

    checkout = _reject_link_components(repository)
    try:
        checkout = checkout.resolve(strict=True)
    except OSError as error:
        raise RuntimeError("canonical checkout is missing") from error
    releases_root = _reject_link_components(checkout / "releases")
    candidate = _reject_link_components(checkout / Path(release_path))
    try:
        relative = candidate.relative_to(releases_root)
    except ValueError as error:
        raise RuntimeError("release_path must resolve under releases/") from error
    if not relative.parts:
        raise RuntimeError("release_path must name one release directory under releases/")
    canonical = _canonical_release_dir(candidate)
    try:
        canonical.relative_to(checkout)
        canonical.relative_to(releases_root)
    except ValueError as error:
        raise RuntimeError("frozen release escaped the canonical checkout") from error
    return canonical


def _safe_release_file(release_dir, path, label):
    release_dir = _canonical_release_dir(release_dir)
    lexical = _reject_link_components(path)
    try:
        canonical = lexical.resolve(strict=True)
        canonical.relative_to(release_dir)
    except (OSError, ValueError) as error:
        raise RuntimeError(f"frozen release file escaped its directory: {label}") from error
    if canonical != lexical or not canonical.is_file():
        raise RuntimeError(f"frozen release file is not canonical: {label}")
    return canonical


def _artifact_path(release_dir, key):
    release_dir = _canonical_release_dir(release_dir)
    matches = []
    for name in ARTIFACT_FILENAMES[key]:
        candidate = release_dir / name
        if candidate.exists() or _is_link_or_reparse(candidate):
            matches.append(_safe_release_file(release_dir, candidate, key))
    if len(matches) != 1:
        raise RuntimeError(f"frozen release artifact must exist exactly once: {key}")
    return matches[0]


def _load_frozen_release(release_dir):
    """Load exact bytes, validate every bound hash, then expose execution inputs."""
    release_dir = _canonical_release_dir(release_dir)
    manifest_path = _safe_release_file(
        release_dir,
        release_dir / "release_manifest.json",
        "release_manifest",
    )
    manifest = load_release_manifest_file(manifest_path)
    artifacts = {
        key: _artifact_path(release_dir, key).read_bytes() for key in ARTIFACT_KEYS
    }
    errors = validate_release_manifest(manifest, artifacts)
    if errors:
        raise RuntimeError("frozen release validation failed: " + "; ".join(errors))
    final_payload = _parse_json_artifact(artifacts["final_cards"], "final_cards")
    action_plan = _parse_json_artifact(artifacts["action_plan"], "action_plan")
    snapshot = _parse_json_artifact(artifacts["snapshot"], "snapshot")
    if not isinstance(final_payload, dict) or not isinstance(
        final_payload.get("cards"), list
    ):
        raise RuntimeError("frozen final cards artifact is malformed")
    if not isinstance(action_plan, dict) or not isinstance(
        action_plan.get("actions"), list
    ):
        raise RuntimeError("frozen action plan artifact is malformed")
    actions = {
        value.get("stable_card_key"): value
        for value in action_plan["actions"]
        if isinstance(value, dict)
        and isinstance(value.get("stable_card_key"), str)
    }
    cards = []
    for frozen in final_payload["cards"]:
        if not isinstance(frozen, dict) or frozen.get("stable_card_key") not in actions:
            raise RuntimeError("frozen card has no exact action plan binding")
        action = actions[frozen["stable_card_key"]]
        for field in ("title", "card_type", "action", "card_id"):
            if frozen.get(field, "") != action.get(field, ""):
                raise RuntimeError(
                    f"frozen action binding drift: {frozen.get('stable_card_key', '')}"
                )
        content = frozen.get("content")
        expected_content_hash = (
            hashlib.sha256(content.encode("utf-8")).hexdigest()
            if isinstance(content, str)
            else ""
        )
        if action.get("content_hash") != expected_content_hash:
            raise RuntimeError(
                f"frozen action content drift: {frozen.get('stable_card_key', '')}"
            )
        cards.append(dict(frozen))
    return manifest, FrozenCards(cards, snapshot)


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate receipt key: {key}")
        value[key] = item
    return value


def _strict_receipt(path):
    try:
        value = json.loads(
            Path(path).read_bytes().decode("utf-8-sig"),
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
            object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise RuntimeError("approval receipt must be strict JSON") from error
    if not isinstance(value, dict):
        raise RuntimeError("approval receipt must be an object")
    _require_strict_json(value, "approval receipt")
    return value


def _release_environment_module():
    return importlib.import_module(".release_environment", __package__)


def _validate_release_environment(manifest, receipt_path):
    module = _release_environment_module()
    validator = getattr(module, "validate_release_environment", None)
    if not callable(validator):
        raise RuntimeError("release_environment validator is unavailable")
    receipt = _strict_receipt(receipt_path)
    result = validator(manifest, receipt)
    try:
        _require_strict_json(result, "release environment validation")
    except RuntimeError as error:
        raise RuntimeError("GitHub release environment receipt is not approved") from error
    if not isinstance(result, dict) or set(result) != VALIDATION_FIELDS:
        raise RuntimeError("GitHub release environment receipt is not approved")
    run_id = result.get("github_run_id")
    if (
        result.get("ok") is not True
        or result.get("receipt") != receipt
        or result.get("release_id") != manifest.get("release_id")
        or result.get("release_hash") != manifest.get("release_hash")
        or not isinstance(run_id, str)
        or not run_id.isascii()
        or not run_id.isdigit()
        or not run_id.strip("0")
        or receipt.get("release_id") != manifest.get("release_id")
        or receipt.get("release_hash") != manifest.get("release_hash")
        or receipt.get("github_run_id") != run_id
        or os.environ.get("GITHUB_RUN_ID") != run_id
    ):
        raise RuntimeError("GitHub release environment receipt is not approved")
    return result


def _create_protected_client(manifest, validation):
    module = _release_environment_module()
    factory = getattr(module, "open_protected_client", None)
    capability_reader = getattr(module, "_capability_for_validation", None)
    if not callable(factory) or not callable(capability_reader):
        raise RuntimeError("GitHub release environment receipt is not approved")
    capability = capability_reader(validation)
    return factory(capability)


def _safe_error(error):
    return "protected release failed [REDACTED]"


def _parser():
    parser = argparse.ArgumentParser(
        description="Execute one protected Maimemo release"
    )
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--approval-receipt", type=Path, required=True)
    parser.add_argument("--journal", type=Path, required=True)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        manifest, cards = _load_frozen_release(args.release_dir)
        validation = _validate_release_environment(manifest, args.approval_receipt)
        client = _create_protected_client(manifest, validation)
        result = execute_release(
            client,
            manifest,
            cards,
            ReleaseJournal(args.journal),
            lambda seconds: __import__("time").sleep(seconds),
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
        return 0 if result.get("final_readback", {}).get("ok") is True else 1
    except Exception as error:
        print(f"release failed: {_safe_error(error)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
