"""Build and validate immutable, route-bound release manifests."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter

from .application_blind_review import strict_json_error


ROUTE_KEYS = ("comparison", "base", "application")
ACTION_KEYS = ("create", "update", "unchanged")
ARTIFACT_KEYS = (
    "source_inventory",
    "semantic_registry",
    "group_registry",
    "application_review",
    "blind_review",
    "final_cards",
    "snapshot",
    "action_plan",
    "quality_reports",
    "engine_tree",
    "skill_tree",
)
JSON_ARTIFACT_KEYS = tuple(
    key for key in ARTIFACT_KEYS if key not in {"engine_tree", "skill_tree"}
)
STATE_ORDER = (
    "draft",
    "plan_frozen",
    "ci_verified",
    "awaiting_user_authorization",
    "authorized",
    "applied",
    "verified",
)
PROTECTED_STATES = frozenset(STATE_ORDER[STATE_ORDER.index("plan_frozen") :])


def _strict_json_payload(value: object, label: str) -> None:
    if strict_json_error(value):
        raise ValueError(f"{label} is not strict JSON")


def _reject_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON number: {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _parse_json_artifact(raw: bytes, key: str) -> object:
    if not isinstance(raw, bytes):
        raise TypeError(f"artifact bytes required: {key}")
    try:
        text = raw.decode("utf-8-sig")
        value = json.loads(
            text,
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"artifact is not strict JSON: {key}") from exc
    if strict_json_error(value):
        raise ValueError(f"artifact is not strict JSON: {key}")
    return value


def _artifact_payloads(artifacts: object) -> dict[str, object]:
    if not isinstance(artifacts, dict):
        raise TypeError("artifacts must be an object")
    if set(artifacts) != set(ARTIFACT_KEYS):
        raise ValueError("artifact keys mismatch")
    payloads: dict[str, object] = {}
    for key in ARTIFACT_KEYS:
        raw = artifacts[key]
        if not isinstance(raw, bytes):
            raise TypeError(f"artifact bytes required: {key}")
        if key in JSON_ARTIFACT_KEYS:
            payloads[key] = _parse_json_artifact(raw, key)
    return payloads


def _route_counts(final_cards: object) -> tuple[dict[str, dict[str, int]], list[str]]:
    errors: list[str] = []
    counts = {
        route: {"create": 0, "update": 0, "unchanged": 0, "after": 0}
        for route in ROUTE_KEYS
    }
    if not isinstance(final_cards, dict):
        return counts, ["final cards must be an object"]
    cards = final_cards.get("cards")
    if not isinstance(cards, list):
        return counts, ["final cards cards must be a list"]

    card_ids: list[str] = []
    titles: list[str] = []
    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            errors.append(f"frozen card must be an object: {index}")
            continue
        route = card.get("card_type")
        action = card.get("action")
        title = card.get("title")
        if route not in ROUTE_KEYS:
            errors.append(f"unknown frozen card type: {index}")
            continue
        if action not in ACTION_KEYS:
            errors.append(f"unknown frozen card action: {index}")
            continue
        if not isinstance(title, str) or not title:
            errors.append(f"frozen card title is missing: {index}")
        else:
            titles.append(title)
        card_id = card.get("card_id")
        if action in {"update", "unchanged"}:
            if not isinstance(card_id, str) or not card_id:
                errors.append(f"frozen card id is missing: {index}")
            else:
                card_ids.append(card_id)
        counts[route][action] += 1
        counts[route]["after"] += 1

    for duplicate in sorted(key for key, count in Counter(card_ids).items() if count > 1):
        errors.append(f"duplicate frozen card id: {duplicate}")
    for duplicate in sorted(key for key, count in Counter(titles).items() if count > 1):
        errors.append(f"duplicate frozen card title: {duplicate}")
    return counts, errors


def _expected_plan_metadata(
    action_plan: object,
) -> tuple[dict, dict, dict, dict, list[str]]:
    errors: list[str] = []
    if not isinstance(action_plan, dict):
        return {}, {}, {}, {}, ["action plan must be an object"]
    deck = action_plan.get("deck")
    routes = action_plan.get("chapter_routes")
    before_counts = action_plan.get("before_counts")
    action_counts = action_plan.get("action_counts")
    if not isinstance(deck, dict):
        errors.append("action plan deck must be an object")
        deck = {}
    if not isinstance(routes, dict) or set(routes) != set(ROUTE_KEYS):
        errors.append("action plan chapter route keys mismatch")
        routes = routes if isinstance(routes, dict) else {}
    if not isinstance(before_counts, dict) or set(before_counts) != set(ROUTE_KEYS):
        errors.append("action plan before count keys mismatch")
        before_counts = before_counts if isinstance(before_counts, dict) else {}
    if not isinstance(action_counts, dict) or set(action_counts) != set(ACTION_KEYS):
        errors.append("action plan action count keys mismatch")
        action_counts = action_counts if isinstance(action_counts, dict) else {}
    return deck, routes, before_counts, action_counts, errors


def _count_errors(
    route_counts: dict[str, dict[str, int]],
    before_counts: dict,
    plan_action_counts: dict,
) -> list[str]:
    errors: list[str] = []
    actual_actions = {
        action: sum(route_counts[route][action] for route in ROUTE_KEYS)
        for action in ACTION_KEYS
    }
    for action in ACTION_KEYS:
        if plan_action_counts.get(action) != actual_actions[action]:
            errors.append(f"action plan count mismatch: {action}")
    for route in ROUTE_KEYS:
        before = before_counts.get(route)
        if type(before) is not int or before < 0:
            errors.append(f"invalid before count: {route}")
        elif before + route_counts[route]["create"] != route_counts[route]["after"]:
            errors.append(f"before/after count mismatch: {route}")
    return errors


def _plan_card_errors(action_plan: object, final_cards: object) -> list[str]:
    if not isinstance(action_plan, dict) or not isinstance(final_cards, dict):
        return []
    actions = action_plan.get("actions")
    cards = final_cards.get("cards")
    if not isinstance(actions, list) or not isinstance(cards, list):
        return []
    errors: list[str] = []
    planned_by_title: dict[str, object] = {}
    duplicate_titles: set[str] = set()
    for action in actions:
        if not isinstance(action, dict):
            errors.append("action plan action must be an object")
            continue
        title = action.get("title")
        if not isinstance(title, str) or not title:
            errors.append("action plan action title is missing")
            continue
        if title in planned_by_title:
            duplicate_titles.add(title)
        planned_by_title[title] = action.get("action")
    for title in sorted(duplicate_titles):
        errors.append(f"duplicate action plan title: {title}")
    for card in cards:
        if not isinstance(card, dict):
            continue
        title = card.get("title")
        if isinstance(title, str) and planned_by_title.get(title) != card.get("action"):
            errors.append(f"action plan does not match frozen card: {title}")
    return errors


def release_hash(manifest: dict) -> str:
    """Return the canonical UTF-8 JSON hash, excluding only its own field."""

    if not isinstance(manifest, dict):
        raise TypeError("release manifest must be an object")
    _strict_json_payload(manifest, "release manifest")
    payload = {key: value for key, value in manifest.items() if key != "release_hash"}
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_release_manifest(inputs: dict) -> dict:
    """Build a v2 manifest from exact artifact bytes and a frozen action plan."""

    if not isinstance(inputs, dict):
        raise TypeError("release inputs must be an object")
    release_id = inputs.get("release_id")
    state = inputs.get("state", "draft")
    if not isinstance(release_id, str) or not release_id:
        raise ValueError("release id is required")
    if state != "draft":
        raise ValueError("new release must start in draft")
    artifacts = inputs.get("artifacts")
    payloads = _artifact_payloads(artifacts)
    action_plan = payloads["action_plan"]
    final_cards = payloads["final_cards"]
    deck, planned_routes, before_counts, planned_actions, metadata_errors = (
        _expected_plan_metadata(action_plan)
    )
    route_counts, card_errors = _route_counts(final_cards)
    errors = (
        metadata_errors
        + card_errors
        + _count_errors(route_counts, before_counts, planned_actions)
        + _plan_card_errors(action_plan, final_cards)
    )
    if errors:
        raise ValueError("invalid release inputs: " + "; ".join(errors))

    if not isinstance(deck.get("id"), str) or not deck.get("id"):
        raise ValueError("action plan deck id is required")
    if not isinstance(deck.get("name"), str) or not deck.get("name"):
        raise ValueError("action plan deck name is required")
    chapter_routes = {}
    for route in ROUTE_KEYS:
        planned = planned_routes.get(route)
        if not isinstance(planned, dict):
            raise ValueError(f"action plan chapter route must be an object: {route}")
        route_id = planned.get("id")
        route_name = planned.get("name")
        if not isinstance(route_id, str) or not route_id:
            raise ValueError(f"chapter route id is required: {route}")
        if not isinstance(route_name, str) or not route_name:
            raise ValueError(f"chapter route name is required: {route}")
        chapter_routes[route] = {
            "id": route_id,
            "name": route_name,
            "type": route,
            "counts": route_counts[route],
        }
    duplicate_ids = [
        value for value, count in Counter(item["id"] for item in chapter_routes.values()).items()
        if count > 1
    ]
    duplicate_names = [
        value for value, count in Counter(item["name"] for item in chapter_routes.values()).items()
        if count > 1
    ]
    if duplicate_ids or duplicate_names:
        raise ValueError("chapter route ids and names must be unique")

    manifest = {
        "schema_version": 2,
        "release_id": release_id,
        "state": state,
        "state_evidence": {},
        "deck": copy.deepcopy(deck),
        "chapter_routes": chapter_routes,
        "card_counts": {
            "before": sum(before_counts[route] for route in ROUTE_KEYS),
            "after": sum(route_counts[route]["after"] for route in ROUTE_KEYS),
        },
        "action_counts": {
            action: sum(route_counts[route][action] for route in ROUTE_KEYS)
            for action in ACTION_KEYS
        },
        "artifact_hashes": {
            key: hashlib.sha256(artifacts[key]).hexdigest() for key in ARTIFACT_KEYS
        },
    }
    manifest["release_hash"] = release_hash(manifest)
    return manifest


def validate_release_manifest(manifest: dict, artifacts: dict) -> list[str]:
    """Return all release-blocking route, count, byte, and self-hash errors."""

    if not isinstance(manifest, dict):
        return ["release manifest must be an object"]
    if strict_json_error(manifest):
        return ["release manifest is not strict JSON"]

    errors: list[str] = []
    if manifest.get("schema_version") != 2:
        errors.append("release manifest schema version mismatch")
    if not isinstance(manifest.get("release_id"), str) or not manifest.get("release_id"):
        errors.append("release id is missing")
    if manifest.get("state") not in STATE_ORDER:
        errors.append("release state is invalid")
    if not isinstance(manifest.get("state_evidence"), dict):
        errors.append("release state evidence must be an object")
    if any("commit" in key.lower() for key in manifest):
        errors.append("git commit sha must be bound outside the manifest")

    payloads: dict[str, object] = {}
    if not isinstance(artifacts, dict) or set(artifacts) != set(ARTIFACT_KEYS):
        errors.append("artifact keys mismatch")
        artifacts = artifacts if isinstance(artifacts, dict) else {}
    for key in ARTIFACT_KEYS:
        raw = artifacts.get(key)
        if not isinstance(raw, bytes):
            errors.append(f"artifact bytes required: {key}")
            continue
        if key in JSON_ARTIFACT_KEYS:
            try:
                payloads[key] = _parse_json_artifact(raw, key)
            except (TypeError, ValueError):
                errors.append(f"artifact is not strict JSON: {key}")

    stored_hashes = manifest.get("artifact_hashes")
    if not isinstance(stored_hashes, dict) or set(stored_hashes) != set(ARTIFACT_KEYS):
        errors.append("artifact hash keys mismatch")
        stored_hashes = stored_hashes if isinstance(stored_hashes, dict) else {}
    for key in ARTIFACT_KEYS:
        raw = artifacts.get(key)
        if isinstance(raw, bytes):
            actual = hashlib.sha256(raw).hexdigest()
            if stored_hashes.get(key) != actual:
                errors.append(f"artifact byte hash mismatch: {key}")

    routes = manifest.get("chapter_routes")
    if not isinstance(routes, dict) or set(routes) != set(ROUTE_KEYS):
        errors.append("chapter route keys mismatch")
        routes = routes if isinstance(routes, dict) else {}
    ids: list[str] = []
    names: list[str] = []
    for route in ROUTE_KEYS:
        current = routes.get(route)
        if not isinstance(current, dict):
            errors.append(f"chapter route must be an object: {route}")
            continue
        route_id = current.get("id")
        route_name = current.get("name")
        if isinstance(route_id, str) and route_id:
            ids.append(route_id)
        else:
            errors.append(f"chapter route id is missing: {route}")
        if isinstance(route_name, str) and route_name:
            names.append(route_name)
        else:
            errors.append(f"chapter route name is missing: {route}")
        if current.get("type") != route:
            errors.append(f"chapter route type mismatch: {route}")
    for duplicate in sorted(key for key, count in Counter(ids).items() if count > 1):
        errors.append(f"duplicate chapter route id: {duplicate}")
    for duplicate in sorted(key for key, count in Counter(names).items() if count > 1):
        errors.append(f"duplicate chapter route name: {duplicate}")

    action_plan = payloads.get("action_plan")
    deck, expected_routes, before_counts, planned_actions, metadata_errors = (
        _expected_plan_metadata(action_plan)
    )
    errors.extend(metadata_errors)
    manifest_deck = manifest.get("deck")
    if not isinstance(manifest_deck, dict) or manifest_deck != deck:
        errors.append("deck mismatch")
    for route in ROUTE_KEYS:
        current = routes.get(route)
        expected = expected_routes.get(route)
        if not isinstance(current, dict) or not isinstance(expected, dict):
            continue
        if current.get("id") != expected.get("id"):
            errors.append(f"chapter route id mismatch: {route}")
        if current.get("name") != expected.get("name"):
            errors.append(f"chapter route name mismatch: {route}")

    route_counts, card_errors = _route_counts(payloads.get("final_cards"))
    errors.extend(card_errors)
    errors.extend(_count_errors(route_counts, before_counts, planned_actions))
    errors.extend(_plan_card_errors(action_plan, payloads.get("final_cards")))
    for route in ROUTE_KEYS:
        current = routes.get(route)
        if not isinstance(current, dict):
            continue
        counts = current.get("counts")
        for count_key in (*ACTION_KEYS, "after"):
            if not isinstance(counts, dict) or counts.get(count_key) != route_counts[route][count_key]:
                errors.append(f"chapter route count mismatch: {route}.{count_key}")

    actual_actions = {
        action: sum(route_counts[route][action] for route in ROUTE_KEYS)
        for action in ACTION_KEYS
    }
    manifest_actions = manifest.get("action_counts")
    for action in ACTION_KEYS:
        if not isinstance(manifest_actions, dict) or manifest_actions.get(action) != actual_actions[action]:
            errors.append(f"action count mismatch: {action}")
    expected_before = sum(
        value for value in before_counts.values() if type(value) is int
    ) if isinstance(before_counts, dict) else 0
    expected_after = sum(route_counts[route]["after"] for route in ROUTE_KEYS)
    card_counts = manifest.get("card_counts")
    if not isinstance(card_counts, dict) or card_counts.get("before") != expected_before:
        errors.append("card before count mismatch")
    if not isinstance(card_counts, dict) or card_counts.get("after") != expected_after:
        errors.append("card after count mismatch")

    try:
        if manifest.get("release_hash") != release_hash(manifest):
            errors.append("release self-hash mismatch")
    except (TypeError, ValueError, OverflowError, RecursionError):
        errors.append("release self-hash mismatch")
    return errors


def _fork_draft(
    manifest: dict,
    artifact_hashes: dict,
    requested_release_id: object,
) -> dict:
    if isinstance(requested_release_id, str) and requested_release_id:
        new_release_id = requested_release_id
    else:
        seed = json.dumps(
            {
                "release_id": manifest.get("release_id"),
                "artifact_hashes": artifact_hashes,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        suffix = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
        new_release_id = f"{manifest.get('release_id', 'release')}-draft-{suffix}"
    if new_release_id == manifest.get("release_id"):
        raise ValueError("changed protected release requires a new release id")
    fork = copy.deepcopy(manifest)
    fork["release_id"] = new_release_id
    fork["state"] = "draft"
    fork["state_evidence"] = {}
    fork["artifact_hashes"] = copy.deepcopy(artifact_hashes)
    fork["release_hash"] = release_hash(fork)
    return fork


def transition_release_state(manifest: dict, target_state: str, evidence: dict) -> dict:
    """Advance a release without mutating it, or fork changed protected bytes."""

    if not isinstance(manifest, dict):
        raise TypeError("release manifest must be an object")
    if not isinstance(evidence, dict):
        raise TypeError("release state evidence must be an object")
    _strict_json_payload(manifest, "release manifest")
    _strict_json_payload(evidence, "release state evidence")
    current_state = manifest.get("state")
    if current_state not in STATE_ORDER or target_state not in STATE_ORDER:
        raise ValueError(f"invalid release state transition: {current_state} -> {target_state}")

    if (
        current_state in PROTECTED_STATES
        and manifest.get("release_hash") != release_hash(manifest)
    ):
        artifact_hashes = manifest.get("artifact_hashes")
        if not isinstance(artifact_hashes, dict) or set(artifact_hashes) != set(ARTIFACT_KEYS):
            raise ValueError("protected artifact hash keys mismatch")
        return _fork_draft(manifest, artifact_hashes, evidence.get("new_release_id"))

    replacement_hashes = evidence.get("protected_artifact_hashes")
    if replacement_hashes is not None:
        if not isinstance(replacement_hashes, dict) or set(replacement_hashes) != set(ARTIFACT_KEYS):
            raise ValueError("protected artifact hash keys mismatch")
        if replacement_hashes != manifest.get("artifact_hashes"):
            if current_state in PROTECTED_STATES:
                return _fork_draft(
                    manifest,
                    replacement_hashes,
                    evidence.get("new_release_id"),
                )
            raise ValueError("protected artifact hashes can change only by rebuilding a draft")

    current_index = STATE_ORDER.index(current_state)
    target_index = STATE_ORDER.index(target_state)
    if target_index <= current_index:
        raise ValueError(f"invalid release state transition: {current_state} -> {target_state}")
    skipped_states = STATE_ORDER[current_index + 1 : target_index]
    missing = [state for state in skipped_states if not evidence.get(state)]
    if missing:
        raise ValueError("missing release state evidence: " + ", ".join(missing))

    transitioned = copy.deepcopy(manifest)
    transitioned["state"] = target_state
    state_evidence = transitioned.get("state_evidence")
    if not isinstance(state_evidence, dict):
        raise ValueError("release state evidence must be an object")
    for key, value in evidence.items():
        if key not in {"protected_artifact_hashes", "new_release_id"}:
            state_evidence[key] = copy.deepcopy(value)
    transitioned["release_hash"] = release_hash(transitioned)
    return transitioned
