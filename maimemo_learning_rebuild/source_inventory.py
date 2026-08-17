"""Coverage and privacy gates for release source inventories."""

from __future__ import annotations

import copy
import hashlib
import json


SOURCE_PRIVACY = {"public_ok", "local_only"}
FINAL_SEGMENT_STATUSES = {
    "reviewed",
    "no_vocabulary",
    "excluded_with_reason",
}
CANDIDATE_DECISIONS = {"include", "exclude", "asr_corrected"}


def _segment_location(segment: dict) -> str:
    source_id = str(segment.get("source_id") or "").strip()
    location = str(segment.get("location") or "").strip()
    return str(segment.get("segment_id") or f"{source_id}:{location}")


def _candidate_term(candidate: dict) -> str:
    return str(candidate.get("term") or candidate.get("word") or "<unknown>")


def _frozen_cards(inventory: dict) -> list[dict]:
    cards: list[dict] = []
    for field in ("frozen_cards", "frozen_derived_cards", "derived_cards"):
        cards.extend(inventory.get(field, []))
    return cards


def validate_source_inventory(inventory: dict) -> list[str]:
    """Return release-blocking source coverage and privacy errors."""
    errors: list[str] = []

    for source in inventory.get("sources", []):
        source_id = str(source.get("source_id") or "<unknown>")
        privacy = source.get("privacy")
        if privacy not in SOURCE_PRIVACY:
            errors.append(f"invalid source privacy: {source_id}: {privacy}")
        if privacy == "local_only" and source.get("repository_path"):
            errors.append("local-only source exposes repository path")

    for segment in inventory.get("segments", []):
        location = _segment_location(segment)
        status = segment.get("status")
        if status not in FINAL_SEGMENT_STATUSES:
            errors.append(f"unclassified source segment: {location}")
        elif status == "excluded_with_reason" and not str(
            segment.get("reason") or ""
        ).strip():
            errors.append(f"excluded segment lacks reason: {location}")

    for candidate in inventory.get("candidates", []):
        term = _candidate_term(candidate)
        decision = candidate.get("decision")
        if not decision:
            errors.append(f"candidate lacks decision: {term}")
            continue
        if decision not in CANDIDATE_DECISIONS:
            errors.append(f"invalid candidate decision: {term}: {decision}")
            continue
        if decision in {"exclude", "asr_corrected"}:
            if not str(candidate.get("reason") or "").strip():
                errors.append(f"candidate {decision} lacks reason: {term}")
            if not str(candidate.get("source_location") or "").strip():
                errors.append(
                    f"candidate {decision} lacks source location: {term}"
                )

    for card in _frozen_cards(inventory):
        if card.get("privacy") != "public_ok":
            card_id = str(card.get("card_id") or card.get("id") or "<unknown>")
            errors.append(f"frozen derived card is not public_ok: {card_id}")

    return errors


def _selected_fields(item: dict, fields: tuple[str, ...]) -> dict:
    return {field: copy.deepcopy(item[field]) for field in fields if field in item}


def public_inventory_view(inventory: dict) -> dict:
    """Build a repository-safe view without machine paths or raw source text."""
    public_view = _selected_fields(
        inventory,
        ("schema_version", "inventory_id", "generated_at", "coverage"),
    )

    public_sources: list[dict] = []
    for source in inventory.get("sources", []):
        fields = (
            "source_id",
            "privacy",
            "sha256",
            "content_hash",
        )
        public_source = _selected_fields(source, fields)
        if source.get("privacy") == "public_ok" and source.get("repository_path"):
            public_source["repository_path"] = source["repository_path"]
        public_sources.append(public_source)
    public_view["sources"] = public_sources

    public_view["segments"] = [
        _selected_fields(
            segment,
            (
                "segment_id",
                "source_id",
                "location",
                "status",
                "approved_excerpt",
            ),
        )
        for segment in inventory.get("segments", [])
    ]
    public_view["candidates"] = [
        _selected_fields(
            candidate,
            ("term", "word", "decision", "source_location"),
        )
        for candidate in inventory.get("candidates", [])
    ]

    for field in ("frozen_cards", "frozen_derived_cards", "derived_cards"):
        if field in inventory:
            public_view[field] = [
                _selected_fields(card, ("card_id", "id", "privacy"))
                for card in inventory.get(field, [])
            ]

    return public_view


def source_inventory_hash(inventory: dict) -> str:
    """Hash the canonical repository-safe representation of an inventory."""
    canonical = json.dumps(
        public_inventory_view(inventory),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
