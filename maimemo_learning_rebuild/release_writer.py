"""Execute an approved release without ever blindly retrying a mutation."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys
from datetime import datetime, timezone

from .api import (
    AmbiguousMutationError,
    MaimemoClient,
    RateLimitError,
    UrllibTransport,
)
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
ROOT_ID = re.compile(r"mkjr_\S+")
ROOT_REFERENCE = re.compile(r"\[Card#ID/(mkjr_[^#\]]+)#")
MAX_RATE_LIMIT_RETRIES = 8
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


def _normalize_cards(cards):
    if isinstance(cards, dict):
        cards = cards.get("cards")
    if not isinstance(cards, list):
        raise RuntimeError("frozen final cards must be a list")
    normalized = []
    stable_keys = set()
    titles = set()
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
        if value["stable_card_key"] in stable_keys or value["title"] in titles:
            raise RuntimeError(f"duplicate frozen stable key or title: {value['title']}")
        if value["action"] in {"update", "unchanged"} and not value.get("card_id"):
            raise RuntimeError(f"frozen card id is required: {value['title']}")
        stable_keys.add(value["stable_card_key"])
        titles.add(value["title"])
        normalized.append(dict(value))
    return normalized


def _index_live(deck, manifest, *, require_routes):
    if not isinstance(deck, dict) or not isinstance(deck.get("cards", []), list):
        raise RuntimeError("live deck readback is malformed")
    route_ids = _route_ids(manifest)
    cards_by_id = {
        value.get("id"): value
        for value in deck.get("cards", [])
        if isinstance(value, dict) and isinstance(value.get("id"), str) and value.get("id")
    }
    indexed = {route: {} for route in ROUTES}
    chapters = deck.get("chapters")
    if isinstance(chapters, list):
        chapters_by_id = {
            value.get("id"): value
            for value in chapters
            if isinstance(value, dict) and isinstance(value.get("id"), str)
        }
        if require_routes:
            for route, route_id in route_ids.items():
                if route_id not in chapters_by_id:
                    raise RuntimeError(f"release target route is missing: {route}")
        for route, route_id in route_ids.items():
            chapter = chapters_by_id.get(route_id)
            if not isinstance(chapter, dict):
                continue
            if require_routes:
                expected_name = manifest["chapter_routes"][route].get("name")
                if chapter.get("name") != expected_name:
                    raise RuntimeError(f"chapter name mismatch: {route}")
            if not isinstance(chapter.get("card_ids", []), list):
                raise RuntimeError(f"live route card ids are malformed: {route}")
            for card_id in chapter.get("card_ids", []):
                value = cards_by_id.get(card_id)
                if value is None:
                    raise RuntimeError(f"live route references missing card: {route}")
                title = _title(value.get("content"))
                if not title:
                    raise RuntimeError(f"unparseable live card: {card_id}")
                if title in indexed[route]:
                    raise RuntimeError(f"duplicate live card title blocks safe resume: {title}")
                indexed[route][title] = value
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


def _root_map(indexed, cards):
    roots = {}
    for card in cards:
        if card["card_type"] != "comparison":
            continue
        live = indexed["comparison"].get(card["title"])
        if live is None:
            raise RuntimeError(f"comparison missing during root readback: {card['title']}")
        if not _valid_root(live.get("root_id")):
            raise RuntimeError(f"invalid comparison root_id after write: {card['title']}")
        roots[card["title"]] = live["root_id"]
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


def _precheck(client, manifest, cards, snapshot):
    live_deck = client.read_deck()
    expected_deck = manifest.get("deck")
    if (
        isinstance(expected_deck, dict)
        and isinstance(live_deck.get("id"), str)
        and live_deck.get("id") != expected_deck.get("id")
    ):
        raise RuntimeError("release target deck differs from frozen manifest")
    live = _index_live(live_deck, manifest, require_routes=True)
    frozen = (
        _index_live(snapshot, manifest, require_routes=False)
        if isinstance(snapshot, dict)
        else {route: {} for route in ROUTES}
    )
    expected = {card["title"]: card for card in cards}
    resolved = _resolved_if_possible(cards, live)
    for route in ROUTES:
        for title in sorted(set(frozen[route]) | set(live[route])):
            before = frozen[route].get(title)
            current = live[route].get(title)
            final = expected.get(title)
            if (
                before is not None
                and current is not None
                and before.get("id") == current.get("id")
                and before.get("content") == current.get("content")
            ):
                continue
            if final is not None and current is not None and current.get("content") == resolved[title]:
                continue
            if before is None and current is not None and final is not None and final["action"] == "create":
                raise RuntimeError(f"same title has different content: {title}")
            raise RuntimeError(f"release target snapshot is stale: {title}")
    return {
        card["title"]: (
            live[card["card_type"]].get(card["title"], {}).get("content")
            if live[card["card_type"]].get(card["title"]) is not None
            else None
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


def _read_action(client, manifest, card):
    indexed = _index_live(client.read_deck(), manifest, require_routes=True)
    return indexed[card["card_type"]].get(card["title"])


def _write_action(client, manifest, card, content, guard, fingerprint, wait_policy):
    rate_limits = 0
    while True:
        if _cancelled(wait_policy):
            raise RuntimeError("release cancelled")
        live = _read_action(client, manifest, card)
        if live is not None and live.get("content") == content:
            return ("unchanged" if card["action"] == "unchanged" else "already_present"), live
        current_content = live.get("content") if live is not None else None
        if current_content != fingerprint:
            raise RuntimeError(f"live content drift before mutation: {card['title']}")
        if card["action"] == "unchanged":
            raise RuntimeError(f"unchanged frozen content differs live: {card['title']}")
        if card["action"] == "create" and live is not None:
            raise RuntimeError(f"same title has different content: {card['title']}")
        if card["action"] == "update" and (
            live is None or live.get("id") != card.get("card_id")
        ):
            raise RuntimeError(f"planned update card id drifted: {card['title']}")
        try:
            if card["action"] == "create":
                client.create_card(_route_ids(manifest)[card["card_type"]], content, guard)
            else:
                client.update_card(card["card_id"], content, guard)
            written = _read_action(client, manifest, card)
            if written is None or written.get("content") != content:
                raise AmbiguousMutationError(
                    f"mutation result did not read back exactly: {card['title']}"
                )
            return card["action"], written
        except RateLimitError as error:
            readback = _read_action(client, manifest, card)
            if readback is not None and readback.get("content") == content:
                return "recovered_after_ambiguous_response", readback
            rate_limits += 1
            if rate_limits > MAX_RATE_LIMIT_RETRIES:
                raise RuntimeError(f"rate limit retry budget exhausted: {card['title']}") from error
            _wait(wait_policy, error.retry_after_seconds)
        except AmbiguousMutationError:
            readback = _read_action(client, manifest, card)
            if readback is not None and readback.get("content") == content:
                return "recovered_after_ambiguous_response", readback
            raise


def _record_card(journal, manifest, card, content, outcome, live):
    _record(
        journal,
        manifest,
        title=card["title"],
        action=card["action"],
        stable_card_key=card["stable_card_key"],
        card_id=live.get("id") if live else card.get("card_id"),
        root_id=live.get("root_id") if live else None,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        outcome=outcome,
    )


def _verify_final(live_deck, manifest, cards, resolved):
    errors = []
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
    live_roots = {
        value.get("root_id")
        for route in ROUTES
        for value in indexed[route].values()
        if _valid_root(value.get("root_id"))
    }
    for route in ROUTES:
        live_titles = set(indexed[route])
        expected_titles = set(expected[route])
        errors.extend(f"missing live title: {title}" for title in sorted(expected_titles - live_titles))
        errors.extend(f"unplanned live title: {title}" for title in sorted(live_titles - expected_titles))
        for title in sorted(live_titles & expected_titles):
            live = indexed[route][title]
            if live.get("content") != resolved[title]:
                errors.append(f"content mismatch: {title}")
            elif type(live.get("grammar_version")) is not int or live.get("grammar_version") != 3:
                errors.append(f"grammar version mismatch: {title}")
            elif not _valid_root(live.get("root_id")):
                errors.append(f"malformed root_id: {title}")
            else:
                verified += 1
            for reference in ROOT_REFERENCE.findall(str(live.get("content") or "")):
                if reference not in live_roots:
                    errors.append(f"missing root reference target: {title} {reference}")
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
    normalized = _normalize_cards(cards)
    _route_ids(manifest)
    if not journal.acquire():
        raise RuntimeError("release writer is already running")
    try:
        if _cancelled(wait_policy):
            raise RuntimeError("release cancelled")
        _phase(journal, manifest, "precheck")
        fingerprints = _precheck(client, manifest, normalized, snapshot)
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
        _phase(journal, manifest, "comparisons")
        for card in (value for value in normalized if value["card_type"] == "comparison"):
            outcome, live = _write_action(
                client,
                manifest,
                card,
                card["content"],
                guard,
                fingerprints[card["title"]],
                wait_policy,
            )
            counts[outcome] += 1
            _record_card(journal, manifest, card, card["content"], outcome, live)
        _phase(journal, manifest, "root_readback")
        roots = _root_map(
            _index_live(client.read_deck(), manifest, require_routes=True), normalized
        )
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
                    card,
                    content,
                    guard,
                    fingerprints[card["title"]],
                    wait_policy,
                )
                counts[outcome] += 1
                _record_card(journal, manifest, card, content, outcome, live)
        _phase(journal, manifest, "final_readback")
        final = _verify_final(client.read_deck(), manifest, normalized, resolved)
        return {**counts, "phases": list(PHASES), "final_readback": final}
    finally:
        journal.release()


def _artifact_path(release_dir, key):
    matches = [
        release_dir / name
        for name in ARTIFACT_FILENAMES[key]
        if (release_dir / name).is_file()
    ]
    if len(matches) != 1:
        raise RuntimeError(f"frozen release artifact must exist exactly once: {key}")
    return matches[0]


def _load_frozen_release(release_dir):
    """Load exact bytes, validate every bound hash, then expose execution inputs."""
    release_dir = Path(release_dir)
    manifest_path = release_dir / "release_manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("frozen release manifest is missing")
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
    return value


def _release_environment_module():
    return importlib.import_module(".release_environment", __package__)


def _validate_release_environment(manifest, receipt_path):
    module = _release_environment_module()
    validator = getattr(module, "validate_release_environment", None)
    if not callable(validator):
        raise RuntimeError("release_environment validator is unavailable")
    result = validator(manifest, _strict_receipt(receipt_path))
    if result is False or (
        isinstance(result, dict) and result.get("ok") is not True
    ):
        raise RuntimeError("GitHub release environment receipt is not approved")
    return result


def _create_protected_client(manifest, validation):
    module = _release_environment_module()
    factory = getattr(module, "open_protected_client", None)
    if callable(factory):
        return factory(manifest, validation)
    return MaimemoClient(
        UrllibTransport(),
        token=os.environ.get("MAIMEMO_TOKEN", ""),
        deck_id=manifest["deck"]["id"],
    )


def _safe_error(error):
    message = str(error)
    token = os.environ.get("MAIMEMO_TOKEN", "")
    return message.replace(token, "[REDACTED]") if token else message


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
