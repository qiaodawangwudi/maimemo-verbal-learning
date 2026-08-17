"""Build and validate immutable, route-bound release manifests."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from pathlib import Path

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


class _StrictManifest(dict):
    """Marker for manifests built here or parsed by the strict byte loader."""


PROTECTED_FIELDS = (
    "schema_version",
    "release_id",
    "deck",
    "chapter_routes",
    "card_counts",
    "action_counts",
    "artifact_hashes",
)
RECEIPT_FIELDS = {
    "receipt_type",
    "verified",
    "release_id",
    "protected_payload_hash",
    "subject_state",
    "subject_release_hash",
}
STATE_RECEIPTS = {
    "ci_verified": ("ci_receipt", "ci_verified", "ci"),
    "awaiting_user_authorization": (
        "awaiting_user_authorization_receipt",
        "awaiting_user_authorization",
        "awaiting-user-authorization",
    ),
    "authorized": ("authorization_receipt", "authorization", "authorization"),
    "applied": ("applied_receipt", "applied", "applied"),
    "verified": ("verification_receipt", "verification", "verification"),
}


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


def load_release_manifest_bytes(raw: bytes) -> dict:
    """Parse release JSON without losing duplicate keys or non-finite numbers."""

    if not isinstance(raw, bytes):
        raise TypeError("release manifest bytes are required")
    try:
        value = json.loads(
            raw.decode("utf-8-sig"),
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("strict release manifest JSON is required") from exc
    if not isinstance(value, dict) or strict_json_error(value):
        raise ValueError("strict release manifest JSON is required")
    return _StrictManifest(value)


def load_release_manifest_file(path: Path | str) -> dict:
    """Read a release manifest through the strict raw-byte boundary."""

    return load_release_manifest_bytes(Path(path).read_bytes())


def _coerce_strict_manifest(value: object) -> _StrictManifest:
    if isinstance(value, bytes):
        return _StrictManifest(load_release_manifest_bytes(value))
    if isinstance(value, Path):
        return _StrictManifest(load_release_manifest_file(value))
    if isinstance(value, _StrictManifest):
        return value
    if isinstance(value, dict):
        raise ValueError("release manifest must be built or loaded with the strict loader")
    raise TypeError("release manifest must be an object or raw bytes")


def _prohibited_git_fields(value: object) -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = key.lower().replace("-", "_") if isinstance(key, str) else ""
            if "commit" in normalized or normalized.endswith("_sha"):
                errors.append(f"prohibited Git receipt field: {key}")
            errors.extend(_prohibited_git_fields(item))
    elif isinstance(value, list):
        for item in value:
            errors.extend(_prohibited_git_fields(item))
    return errors


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


ROUTE_COUNT_KEYS = ("before", "create", "update", "unchanged", "after")
ACTION_FIELDS = {
    "stable_card_key",
    "title",
    "card_type",
    "route_id",
    "route_name",
    "action",
    "card_id",
}
ACTION_PLAN_FIELDS = {
    "schema_version",
    "deck",
    "chapter_routes",
    "before_counts",
    "route_counts",
    "action_counts",
    "actions",
}
DECK_FIELDS = {"id", "name"}
PLANNED_ROUTE_FIELDS = {"id", "name"}


def _empty_route_counts() -> dict[str, dict[str, int]]:
    return {
        route: {key: 0 for key in ROUTE_COUNT_KEYS}
        for route in ROUTE_KEYS
    }


def _final_card_bindings(
    final_cards: object,
) -> tuple[dict[str, dict[str, int]], dict[str, dict], list[str]]:
    counts = _empty_route_counts()
    bindings: dict[str, dict] = {}
    errors: list[str] = []
    if not isinstance(final_cards, dict):
        return counts, bindings, ["final cards must be an object"]
    cards = final_cards.get("cards")
    if not isinstance(cards, list):
        return counts, bindings, ["final cards cards must be a list"]
    card_ids: list[str] = []
    titles: list[str] = []
    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            errors.append(f"frozen card must be an object: {index}")
            continue
        stable_key = card.get("stable_card_key")
        if not isinstance(stable_key, str) or not stable_key:
            errors.append(f"frozen card stable_card_key is missing: {index}")
            continue
        if stable_key in bindings:
            errors.append(f"duplicate frozen card stable_card_key: {stable_key}")
            continue
        bindings[stable_key] = card
        title = card.get("title")
        if not isinstance(title, str) or not title:
            errors.append(f"frozen card title is invalid: {stable_key}")
        else:
            titles.append(title)
        route = card.get("card_type")
        action = card.get("action")
        if route not in ROUTE_KEYS:
            errors.append(f"unknown frozen card type: {stable_key}")
            continue
        if action not in ACTION_KEYS:
            errors.append(f"unknown frozen card action: {stable_key}")
            continue
        card_id = card.get("card_id")
        if action in {"update", "unchanged"}:
            if not isinstance(card_id, str) or not card_id:
                errors.append(f"frozen card id is missing: {stable_key}")
            else:
                card_ids.append(card_id)
        counts[route][action] += 1
        counts[route]["after"] += 1
    for route in ROUTE_KEYS:
        counts[route]["before"] = counts[route]["after"] - counts[route]["create"]
    for duplicate in sorted(key for key, count in Counter(card_ids).items() if count > 1):
        errors.append(f"duplicate frozen card id: {duplicate}")
    for duplicate in sorted(key for key, count in Counter(titles).items() if count > 1):
        errors.append(f"duplicate frozen card title: {duplicate}")
    return counts, bindings, errors


def _expected_plan_metadata(
    action_plan: object,
) -> tuple[dict, dict, dict, dict, dict, list[str]]:
    errors: list[str] = []
    if not isinstance(action_plan, dict):
        return {}, {}, {}, {}, {}, ["action plan must be an object"]
    if set(action_plan) != ACTION_PLAN_FIELDS:
        errors.append("action plan fields mismatch")
    if action_plan.get("schema_version") != 2:
        errors.append("action plan schema version mismatch")
    deck = action_plan.get("deck")
    routes = action_plan.get("chapter_routes")
    before_counts = action_plan.get("before_counts")
    action_counts = action_plan.get("action_counts")
    route_counts = action_plan.get("route_counts")
    if not isinstance(deck, dict):
        errors.append("action plan deck must be an object")
        deck = {}
    elif set(deck) != DECK_FIELDS:
        errors.append("action plan deck fields mismatch")
    if not isinstance(routes, dict) or set(routes) != set(ROUTE_KEYS):
        errors.append("action plan chapter route keys mismatch")
        routes = routes if isinstance(routes, dict) else {}
    if not isinstance(before_counts, dict) or set(before_counts) != set(ROUTE_KEYS):
        errors.append("action plan before count keys mismatch")
        before_counts = before_counts if isinstance(before_counts, dict) else {}
    if not isinstance(action_counts, dict) or set(action_counts) != set(ACTION_KEYS):
        errors.append("action plan action count keys mismatch")
        action_counts = action_counts if isinstance(action_counts, dict) else {}
    if not isinstance(route_counts, dict) or set(route_counts) != set(ROUTE_KEYS):
        errors.append("action plan route count keys mismatch")
        route_counts = route_counts if isinstance(route_counts, dict) else {}
    for route in ROUTE_KEYS:
        planned_route = routes.get(route)
        if not isinstance(planned_route, dict):
            errors.append(f"action plan chapter route must be an object: {route}")
        elif set(planned_route) != PLANNED_ROUTE_FIELDS:
            errors.append(f"action plan chapter route fields mismatch: {route}")
        counts = route_counts.get(route)
        if not isinstance(counts, dict) or set(counts) != set(ROUTE_COUNT_KEYS):
            errors.append(f"action plan route count fields mismatch: {route}")
            continue
        for key in ROUTE_COUNT_KEYS:
            if type(counts.get(key)) is not int or counts[key] < 0:
                errors.append(f"invalid action plan route count: {route}.{key}")
    return deck, routes, before_counts, action_counts, route_counts, errors


def _plan_action_bindings(
    action_plan: object,
    planned_routes: dict,
) -> tuple[dict[str, dict[str, int]], dict[str, dict], dict[str, int], list[str]]:
    counts = _empty_route_counts()
    action_counts = {action: 0 for action in ACTION_KEYS}
    bindings: dict[str, dict] = {}
    errors: list[str] = []
    titles: list[str] = []
    actions = action_plan.get("actions") if isinstance(action_plan, dict) else None
    if not isinstance(actions, list):
        return counts, bindings, action_counts, ["action plan actions must be a list"]
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            errors.append(f"action plan action must be an object: {index}")
            continue
        if set(action) != ACTION_FIELDS:
            errors.append(f"action plan action fields mismatch: {index}")
        stable_key = action.get("stable_card_key")
        if not isinstance(stable_key, str) or not stable_key:
            errors.append(f"action stable_card_key is missing: {index}")
            continue
        if stable_key in bindings:
            errors.append(f"duplicate action plan stable_card_key: {stable_key}")
            continue
        bindings[stable_key] = action
        title = action.get("title")
        if not isinstance(title, str) or not title:
            errors.append(f"action title is invalid: {stable_key}")
        else:
            titles.append(title)
        route = action.get("card_type")
        value = action.get("action")
        if route not in ROUTE_KEYS:
            errors.append(f"unknown action card_type: {stable_key}")
            continue
        if value not in ACTION_KEYS:
            errors.append(f"unknown release action: {value}")
            continue
        expected_route = planned_routes.get(route)
        if not isinstance(expected_route, dict) or (
            action.get("route_id") != expected_route.get("id")
            or action.get("route_name") != expected_route.get("name")
        ):
            errors.append(f"action route binding mismatch: {stable_key}")
        card_id = action.get("card_id")
        if value in {"update", "unchanged"} and (
            not isinstance(card_id, str) or not card_id
        ):
            errors.append(f"action card_id is required: {stable_key}")
        if value == "create" and card_id != "":
            errors.append(f"create action card_id must be empty: {stable_key}")
        counts[route][value] += 1
        counts[route]["after"] += 1
        action_counts[value] += 1
    for route in ROUTE_KEYS:
        counts[route]["before"] = counts[route]["after"] - counts[route]["create"]
    for duplicate in sorted(key for key, count in Counter(titles).items() if count > 1):
        errors.append(f"duplicate action plan title: {duplicate}")
    return counts, bindings, action_counts, errors


def _release_plan_errors(
    action_plan: object,
    final_cards: object,
    planned_routes: dict,
    before_counts: dict,
    declared_action_counts: dict,
    declared_route_counts: dict,
) -> tuple[dict[str, dict[str, int]], dict[str, int], list[str]]:
    plan_counts, plan_bindings, actual_action_counts, errors = _plan_action_bindings(
        action_plan, planned_routes
    )
    card_counts, card_bindings, card_errors = _final_card_bindings(final_cards)
    errors.extend(card_errors)
    for action in ACTION_KEYS:
        if declared_action_counts.get(action) != actual_action_counts[action]:
            errors.append(f"action plan declared count mismatch: {action}")
        frozen_total = sum(card_counts[route][action] for route in ROUTE_KEYS)
        if frozen_total != actual_action_counts[action]:
            errors.append(f"action count mismatch: {action}")
    for route in ROUTE_KEYS:
        if before_counts.get(route) != plan_counts[route]["before"]:
            errors.append(f"action plan before count mismatch: {route}")
        declared = declared_route_counts.get(route)
        for key in ROUTE_COUNT_KEYS:
            if not isinstance(declared, dict) or declared.get(key) != plan_counts[route][key]:
                errors.append(f"action plan route count mismatch: {route}.{key}")
            if card_counts[route][key] != plan_counts[route][key]:
                errors.append(f"chapter route count mismatch: {route}.{key}")
    for stable_key in sorted(set(plan_bindings) - set(card_bindings)):
        errors.append(f"orphan action plan card: {stable_key}")
    for stable_key in sorted(set(card_bindings) - set(plan_bindings)):
        errors.append(f"frozen card missing action plan binding: {stable_key}")
    for stable_key in sorted(set(plan_bindings) & set(card_bindings)):
        action = plan_bindings[stable_key]
        card = card_bindings[stable_key]
        if action.get("card_type") != card.get("card_type"):
            errors.append(f"frozen card route binding mismatch: {stable_key}")
        if action.get("action") != card.get("action"):
            errors.append(f"action plan does not match frozen card: {card.get('title')}")
        for field in ("title", "card_id"):
            if action.get(field) != card.get(field):
                errors.append(f"frozen card binding mismatch: {stable_key}.{field}")
    return plan_counts, actual_action_counts, errors


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


def _protected_payload_hash(manifest: dict) -> str:
    try:
        payload = {key: manifest[key] for key in PROTECTED_FIELDS}
    except KeyError as exc:
        raise ValueError("release protected payload is incomplete") from exc
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _receipt_matches(
    receipt: object,
    *,
    receipt_type: str,
    release_id: object,
    payload_hash: str,
    subject_state: str,
    subject_release_hash: str,
) -> bool:
    return (
        isinstance(receipt, dict)
        and set(receipt) == RECEIPT_FIELDS
        and receipt.get("receipt_type") == receipt_type
        and receipt.get("verified") is True
        and receipt.get("release_id") == release_id
        and receipt.get("protected_payload_hash") == payload_hash
        and receipt.get("subject_state") == subject_state
        and receipt.get("subject_release_hash") == subject_release_hash
        and _digest(receipt.get("protected_payload_hash"))
        and _digest(receipt.get("subject_release_hash"))
    )


def _state_evidence_keys(state: str) -> set[str]:
    if state == "draft":
        return set()
    keys = {"frozen_baseline"}
    for candidate in STATE_ORDER[2 : STATE_ORDER.index(state) + 1]:
        keys.add(STATE_RECEIPTS[candidate][0])
    return keys


def _state_lineage_errors(manifest: dict) -> list[str]:
    state = manifest.get("state")
    evidence = manifest.get("state_evidence")
    if state not in STATE_ORDER or not isinstance(evidence, dict):
        return [f"release state evidence lineage incomplete: {state}"]
    if set(evidence) != _state_evidence_keys(state):
        return [f"release state evidence lineage incomplete: {state}"]
    if state == "draft":
        return []

    payload_hash = _protected_payload_hash(manifest)
    draft_view = copy.deepcopy(manifest)
    draft_view["state"] = "draft"
    draft_view["state_evidence"] = {}
    draft_hash = release_hash(draft_view)
    baseline = evidence.get("frozen_baseline")
    if not _receipt_matches(
        baseline,
        receipt_type="verified_frozen_baseline",
        release_id=manifest.get("release_id"),
        payload_hash=payload_hash,
        subject_state="draft",
        subject_release_hash=draft_hash,
    ):
        return ["invalid verified frozen baseline"]

    reconstructed_evidence = {"frozen_baseline": copy.deepcopy(baseline)}
    for target_state in STATE_ORDER[2 : STATE_ORDER.index(state) + 1]:
        previous_state = STATE_ORDER[STATE_ORDER.index(target_state) - 1]
        previous_view = copy.deepcopy(manifest)
        previous_view["state"] = previous_state
        previous_view["state_evidence"] = copy.deepcopy(reconstructed_evidence)
        previous_view["release_hash"] = release_hash(previous_view)
        key, receipt_type, label = STATE_RECEIPTS[target_state]
        receipt = evidence.get(key)
        if not _receipt_matches(
            receipt,
            receipt_type=receipt_type,
            release_id=manifest.get("release_id"),
            payload_hash=payload_hash,
            subject_state=previous_state,
            subject_release_hash=previous_view["release_hash"],
        ):
            return [f"invalid {label} receipt"]
        reconstructed_evidence[key] = copy.deepcopy(receipt)
    return []


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
    prohibited_input_fields = _prohibited_git_fields(action_plan)
    (
        deck,
        planned_routes,
        before_counts,
        declared_action_counts,
        declared_route_counts,
        metadata_errors,
    ) = (
        _expected_plan_metadata(action_plan)
    )
    route_counts, actual_action_counts, plan_errors = _release_plan_errors(
        action_plan,
        final_cards,
        planned_routes,
        before_counts,
        declared_action_counts,
        declared_route_counts,
    )
    errors = prohibited_input_fields + metadata_errors + plan_errors
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

    manifest = _StrictManifest({
        "schema_version": 2,
        "release_id": release_id,
        "state": state,
        "state_evidence": {},
        "deck": copy.deepcopy(deck),
        "chapter_routes": chapter_routes,
        "card_counts": {
            "before": sum(route_counts[route]["before"] for route in ROUTE_KEYS),
            "after": sum(route_counts[route]["after"] for route in ROUTE_KEYS),
        },
        "action_counts": actual_action_counts,
        "artifact_hashes": {
            key: hashlib.sha256(artifacts[key]).hexdigest() for key in ARTIFACT_KEYS
        },
    })
    manifest["release_hash"] = release_hash(manifest)
    post_build_errors = validate_release_manifest(manifest, artifacts)
    if post_build_errors:
        raise ValueError(
            "built release manifest is invalid: " + "; ".join(post_build_errors)
        )
    return manifest


def validate_release_manifest(manifest: dict | bytes | Path, artifacts: dict) -> list[str]:
    """Return all release-blocking route, count, byte, and self-hash errors."""

    try:
        manifest = _coerce_strict_manifest(manifest)
    except TypeError:
        return ["release manifest must be an object or raw bytes"]
    except ValueError:
        if isinstance(manifest, bytes):
            return ["release manifest is not strict JSON"]
        return ["release manifest must be built or loaded with the strict loader"]
    try:
        manifest_is_strict = strict_json_error(manifest) is None
    except (RecursionError, OverflowError, TypeError, ValueError):
        manifest_is_strict = False
    if not manifest_is_strict:
        return ["release manifest is not strict JSON"]

    errors: list[str] = []
    errors.extend(_prohibited_git_fields(manifest))
    if set(manifest) != MANIFEST_FIELDS:
        errors.append("release manifest fields mismatch")
    if manifest.get("schema_version") != 2:
        errors.append("release manifest schema version mismatch")
    if not isinstance(manifest.get("release_id"), str) or not manifest.get("release_id"):
        errors.append("release id is missing")
    if manifest.get("state") not in STATE_ORDER:
        errors.append("release state is invalid")
    if not isinstance(manifest.get("state_evidence"), dict):
        errors.append("release state evidence must be an object")
    else:
        try:
            errors.extend(_state_lineage_errors(manifest))
        except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
            errors.append(
                f"release state evidence lineage incomplete: {manifest.get('state')}"
            )

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
        if set(current) != {"id", "name", "type", "counts"}:
            errors.append(f"chapter route fields mismatch: {route}")
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
        counts = current.get("counts")
        if not isinstance(counts, dict) or set(counts) != set(ROUTE_COUNT_KEYS):
            errors.append(f"chapter route count fields mismatch: {route}")
    for duplicate in sorted(key for key, count in Counter(ids).items() if count > 1):
        errors.append(f"duplicate chapter route id: {duplicate}")
    for duplicate in sorted(key for key, count in Counter(names).items() if count > 1):
        errors.append(f"duplicate chapter route name: {duplicate}")

    action_plan = payloads.get("action_plan")
    (
        deck,
        expected_routes,
        before_counts,
        declared_action_counts,
        declared_route_counts,
        metadata_errors,
    ) = (
        _expected_plan_metadata(action_plan)
    )
    errors.extend(metadata_errors)
    manifest_deck = manifest.get("deck")
    if not isinstance(manifest_deck, dict) or set(manifest_deck) != {"id", "name"}:
        errors.append("deck fields mismatch")
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

    route_counts, actual_actions, plan_errors = _release_plan_errors(
        action_plan,
        payloads.get("final_cards"),
        expected_routes,
        before_counts,
        declared_action_counts,
        declared_route_counts,
    )
    errors.extend(plan_errors)
    for route in ROUTE_KEYS:
        current = routes.get(route)
        if not isinstance(current, dict):
            continue
        counts = current.get("counts")
        expected_counts = declared_route_counts.get(route)
        for count_key in ROUTE_COUNT_KEYS:
            if (
                not isinstance(counts, dict)
                or not isinstance(expected_counts, dict)
                or counts.get(count_key) != expected_counts.get(count_key)
            ):
                errors.append(f"chapter route count mismatch: {route}.{count_key}")

    manifest_actions = manifest.get("action_counts")
    if not isinstance(manifest_actions, dict) or set(manifest_actions) != set(ACTION_KEYS):
        errors.append("action count fields mismatch")
    for action in ACTION_KEYS:
        if not isinstance(manifest_actions, dict) or manifest_actions.get(action) != actual_actions[action]:
            errors.append(f"action count mismatch: {action}")
    expected_before = sum(route_counts[route]["before"] for route in ROUTE_KEYS)
    expected_after = sum(route_counts[route]["after"] for route in ROUTE_KEYS)
    card_counts = manifest.get("card_counts")
    if not isinstance(card_counts, dict) or set(card_counts) != {"before", "after"}:
        errors.append("card count fields mismatch")
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


def validate_release_manifest_envelope(manifest: dict) -> list[str]:
    """Validate the complete authorized v2 envelope without artifact contents."""

    if not isinstance(manifest, _StrictManifest):
        return ["release manifest must be built or loaded with the strict loader"]
    try:
        manifest_is_strict = strict_json_error(manifest) is None
    except (RecursionError, OverflowError, TypeError, ValueError):
        manifest_is_strict = False
    if not manifest_is_strict:
        return ["release manifest is not strict JSON"]

    errors: list[str] = []
    errors.extend(_prohibited_git_fields(manifest))
    if set(manifest) != MANIFEST_FIELDS:
        errors.append("release manifest fields mismatch")
    if manifest.get("schema_version") != 2 or type(manifest.get("schema_version")) is not int:
        errors.append("release manifest schema version mismatch")
    if not isinstance(manifest.get("release_id"), str) or not manifest.get("release_id"):
        errors.append("release id is missing")
    if manifest.get("state") != "authorized":
        errors.append("release state is not authorized")
    if not isinstance(manifest.get("state_evidence"), dict):
        errors.append("release state evidence must be an object")
    else:
        try:
            errors.extend(_state_lineage_errors(manifest))
        except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
            errors.append("release state evidence lineage incomplete: authorized")

    deck = manifest.get("deck")
    if not isinstance(deck, dict) or set(deck) != DECK_FIELDS:
        errors.append("deck fields mismatch")
    elif any(not isinstance(deck.get(key), str) or not deck[key] for key in DECK_FIELDS):
        errors.append("deck identity is missing")

    routes = manifest.get("chapter_routes")
    if not isinstance(routes, dict) or set(routes) != set(ROUTE_KEYS):
        errors.append("chapter route keys mismatch")
        routes = routes if isinstance(routes, dict) else {}
    route_ids: list[str] = []
    route_names: list[str] = []
    totals = {key: 0 for key in ROUTE_COUNT_KEYS}
    action_totals = {key: 0 for key in ACTION_KEYS}
    for route in ROUTE_KEYS:
        current = routes.get(route)
        if not isinstance(current, dict):
            errors.append(f"chapter route must be an object: {route}")
            continue
        if set(current) != {"id", "name", "type", "counts"}:
            errors.append(f"chapter route fields mismatch: {route}")
        if current.get("type") != route:
            errors.append(f"chapter route type mismatch: {route}")
        for field, identities in (("id", route_ids), ("name", route_names)):
            value = current.get(field)
            if not isinstance(value, str) or not value:
                errors.append(f"chapter route {field} is missing: {route}")
            else:
                identities.append(value)
        counts = current.get("counts")
        if not isinstance(counts, dict) or set(counts) != set(ROUTE_COUNT_KEYS):
            errors.append(f"chapter route count fields mismatch: {route}")
            continue
        valid_counts = True
        for key in ROUTE_COUNT_KEYS:
            if type(counts.get(key)) is not int or counts[key] < 0:
                errors.append(f"invalid chapter route count: {route}.{key}")
                valid_counts = False
            else:
                totals[key] += counts[key]
                if key in ACTION_KEYS:
                    action_totals[key] += counts[key]
        if valid_counts and (
            counts["after"] != sum(counts[key] for key in ACTION_KEYS)
            or counts["before"] != counts["update"] + counts["unchanged"]
        ):
            errors.append(f"chapter route count equation mismatch: {route}")
    if len(route_ids) != len(set(route_ids)):
        errors.append("duplicate chapter route id")
    if len(route_names) != len(set(route_names)):
        errors.append("duplicate chapter route name")

    card_counts = manifest.get("card_counts")
    if not isinstance(card_counts, dict) or set(card_counts) != {"before", "after"}:
        errors.append("card count fields mismatch")
    else:
        for key in ("before", "after"):
            if type(card_counts.get(key)) is not int or card_counts[key] < 0:
                errors.append(f"invalid card count: {key}")
            elif card_counts[key] != totals[key]:
                errors.append(f"card {key} count mismatch")

    action_counts = manifest.get("action_counts")
    if not isinstance(action_counts, dict) or set(action_counts) != set(ACTION_KEYS):
        errors.append("action count fields mismatch")
    else:
        for action in ACTION_KEYS:
            if type(action_counts.get(action)) is not int or action_counts[action] < 0:
                errors.append(f"invalid action count: {action}")
            elif action_counts[action] != action_totals[action]:
                errors.append(f"action count mismatch: {action}")

    artifact_hashes = manifest.get("artifact_hashes")
    if not isinstance(artifact_hashes, dict) or set(artifact_hashes) != set(ARTIFACT_KEYS):
        errors.append("artifact hash keys mismatch")
    else:
        for key in ARTIFACT_KEYS:
            if not _digest(artifact_hashes.get(key)):
                errors.append(f"artifact hash is invalid: {key}")
    try:
        if manifest.get("release_hash") != release_hash(manifest):
            errors.append("release self-hash mismatch")
    except (TypeError, ValueError, OverflowError, RecursionError):
        errors.append("release self-hash mismatch")
    return list(dict.fromkeys(errors))


def _fork_draft(
    manifest: dict,
    frozen_release_id: str,
    changed_payload_hash: str,
) -> dict:
    """Fork by frozen identity plus the pre-fork protected-payload digest."""

    new_release_id = f"{frozen_release_id}-draft-{changed_payload_hash[:12]}"
    fork = copy.deepcopy(manifest)
    fork["release_id"] = new_release_id
    fork["state"] = "draft"
    fork["state_evidence"] = {}
    fork["release_hash"] = release_hash(fork)
    return fork


def _external_baseline_is_structurally_verified(
    receipt: object,
    release_id: object,
) -> bool:
    return (
        isinstance(receipt, dict)
        and set(receipt) == RECEIPT_FIELDS
        and receipt.get("receipt_type") == "verified_frozen_baseline"
        and receipt.get("verified") is True
        and receipt.get("release_id") == release_id
        and receipt.get("subject_state") == "draft"
        and _digest(receipt.get("protected_payload_hash"))
        and _digest(receipt.get("subject_release_hash"))
    )


def transition_release_state(
    manifest: dict | bytes | Path,
    target_state: str,
    evidence: dict,
) -> dict:
    """Advance using caller-verified external receipts; no receipt is authenticated here."""

    manifest = _coerce_strict_manifest(manifest)
    if not isinstance(evidence, dict):
        raise TypeError("release state evidence must be an object")
    _strict_json_payload(evidence, "release state evidence")
    current_state = manifest.get("state")
    if current_state not in STATE_ORDER or target_state not in STATE_ORDER:
        raise ValueError(f"invalid release state transition: {current_state} -> {target_state}")
    current_index = STATE_ORDER.index(current_state)
    target_index = STATE_ORDER.index(target_state)
    if target_index != current_index + 1:
        raise ValueError(f"invalid release state transition: {current_state} -> {target_state}")

    baseline = evidence.get("frozen_baseline")
    if current_state in PROTECTED_STATES and baseline is None:
        raise ValueError("missing verified frozen baseline")
    target_receipt_key = None if target_state == "plan_frozen" else STATE_RECEIPTS[target_state][0]
    required_keys = {"frozen_baseline"}
    if target_receipt_key:
        required_keys.add(target_receipt_key)
    allowed_keys = required_keys
    if not required_keys.issubset(evidence) or not set(evidence).issubset(allowed_keys):
        raise ValueError("missing required transition evidence")

    if current_state == "draft":
        lineage_errors = _state_lineage_errors(manifest)
        if lineage_errors or manifest.get("release_hash") != release_hash(manifest):
            raise ValueError("current release state lineage is invalid")
        if not _receipt_matches(
            baseline,
            receipt_type="verified_frozen_baseline",
            release_id=manifest.get("release_id"),
            payload_hash=_protected_payload_hash(manifest),
            subject_state="draft",
            subject_release_hash=manifest["release_hash"],
        ):
            raise ValueError("invalid verified frozen baseline")
    else:
        stored_evidence = manifest.get("state_evidence")
        stored_baseline = (
            stored_evidence.get("frozen_baseline")
            if isinstance(stored_evidence, dict)
            else None
        )
        frozen_release_id = (
            stored_baseline.get("release_id")
            if isinstance(stored_baseline, dict)
            else None
        )
        if (
            not _external_baseline_is_structurally_verified(
                baseline, frozen_release_id
            )
            or baseline != stored_baseline
        ):
            if stored_baseline is None:
                raise ValueError("current release state lineage is invalid")
            raise ValueError("invalid verified frozen baseline")
        current_payload_hash = _protected_payload_hash(manifest)
        if current_payload_hash != baseline["protected_payload_hash"]:
            return _fork_draft(
                manifest,
                frozen_release_id,
                current_payload_hash,
            )
        if (
            _state_lineage_errors(manifest)
            or manifest.get("release_hash") != release_hash(manifest)
        ):
            raise ValueError("current release state lineage is invalid")

    transitioned = copy.deepcopy(manifest)
    transitioned["state"] = target_state
    state_evidence = transitioned.get("state_evidence")
    if not isinstance(state_evidence, dict):
        raise ValueError("current release state lineage is invalid")
    if target_state == "plan_frozen":
        state_evidence["frozen_baseline"] = copy.deepcopy(baseline)
    else:
        key, receipt_type, label = STATE_RECEIPTS[target_state]
        receipt = evidence.get(key)
        if not _receipt_matches(
            receipt,
            receipt_type=receipt_type,
            release_id=manifest.get("release_id"),
            payload_hash=_protected_payload_hash(manifest),
            subject_state=current_state,
            subject_release_hash=manifest["release_hash"],
        ):
            raise ValueError(f"invalid {label} receipt")
        state_evidence[key] = copy.deepcopy(receipt)
    transitioned["release_hash"] = release_hash(transitioned)
    if _state_lineage_errors(transitioned):
        raise ValueError("resulting release state lineage is invalid")
    return transitioned
