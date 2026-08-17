"""Coverage and privacy gates for release source inventories."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath


SOURCE_PRIVACY = {"public_ok", "local_only"}
FINAL_SEGMENT_STATUSES = {
    "reviewed",
    "no_vocabulary",
    "excluded_with_reason",
}
CANDIDATE_DECISIONS = {"include", "exclude", "asr_corrected"}
COVERAGE_FIELDS = ("sources", "segments", "candidates", "reviewed_segments")
MAX_IDENTIFIER_CHARS = 256
MAX_EXCERPT_CHARS = 240
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


def _segment_location(segment: dict) -> str:
    segment_id = segment.get("segment_id")
    if _public_identifier(segment_id):
        return segment_id.strip()
    source_id = segment.get("source_id")
    location = segment.get("location")
    source_text = source_id.strip() if _public_identifier(source_id) else ""
    location_text = location.strip() if _public_identifier(location) else ""
    return f"{source_text}:{location_text}"


def _has_stable_segment_location(segment: dict) -> bool:
    return _public_identifier(segment.get("segment_id")) or (
        _public_identifier(segment.get("source_id"))
        and _public_identifier(segment.get("location"))
    )


def _candidate_term(candidate: dict) -> str:
    value = candidate.get("term") or candidate.get("word")
    if _bounded_string(value):
        return value.strip()
    return _stable_display(value) if value is not None else "<unknown>"


def _stable_display(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _bounded_string(value: object, limit: int = MAX_IDENTIFIER_CHARS) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= limit
    )


def _normalized_repository_path(value: object) -> str | None:
    if not _bounded_string(value, 512):
        return None
    assert isinstance(value, str)
    if (
        "\\" in value
        or value.startswith("/")
        or re.match(r"^[A-Za-z]:", value)
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        return None
    normalized = PurePosixPath(value).as_posix()
    return normalized if normalized == value else None


def _public_identifier(value: object) -> bool:
    return _bounded_string(value) and not (
        value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", value)
    )


def _sha256(value: object) -> bool:
    return isinstance(value, str) and SHA256_PATTERN.fullmatch(value) is not None


def validate_source_inventory(inventory: dict) -> list[str]:
    """Return release-blocking source coverage and privacy errors."""
    if not isinstance(inventory, dict):
        return ["inventory must be an object"]

    errors: list[str] = []
    sections: dict[str, list] = {}
    for field in ("sources", "segments", "candidates"):
        if field not in inventory:
            errors.append(f"missing inventory section: {field}")
        elif not isinstance(inventory[field], list):
            errors.append(f"inventory section must be a list: {field}")
        else:
            sections[field] = inventory[field]
    frozen_fields = (
        "frozen_cards",
        "frozen_derived_cards",
        "derived_cards",
    )
    present_frozen_fields = [field for field in frozen_fields if field in inventory]
    if not present_frozen_fields:
        errors.append("missing inventory section: frozen_cards")
    frozen_sections: dict[str, list] = {}
    for field in present_frozen_fields:
        if not isinstance(inventory[field], list):
            errors.append(f"inventory section must be a list: {field}")
        else:
            frozen_sections[field] = inventory[field]
    if "coverage" not in inventory:
        errors.append("missing inventory section: coverage")

    coverage = inventory.get("coverage")
    if isinstance(coverage, dict):
        expected_counts: dict[str, int] = {}
        for field in ("sources", "segments", "candidates"):
            if field in sections:
                expected_counts[field] = len(sections[field])
        if "segments" in sections:
            expected_counts["reviewed_segments"] = sum(
                isinstance(segment, dict)
                and isinstance(segment.get("status"), str)
                and segment.get("status") in FINAL_SEGMENT_STATUSES
                for segment in sections["segments"]
            )
        for field in COVERAGE_FIELDS:
            if field not in coverage:
                errors.append(f"missing coverage counter: {field}")
                continue
            value = coverage[field]
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                errors.append(
                    "coverage counter must be a nonnegative integer: "
                    f"{field}"
                )
                continue
            expected = expected_counts.get(field)
            if expected is not None and value != expected:
                errors.append(
                    f"coverage count mismatch: {field}: "
                    f"expected {expected}, got {value}"
                )
    elif "coverage" in inventory:
        errors.append("inventory section must be an object: coverage")

    for source in sections.get("sources", []):
        if not isinstance(source, dict):
            errors.append("source entry must be an object")
            continue
        source_id_value = source.get("source_id")
        source_id = (
            source_id_value.strip()
            if _public_identifier(source_id_value)
            else "<unknown>"
        )
        if "source_id" in source and not _bounded_string(source_id_value):
            errors.append(f"source field must be a string: {source_id}: source_id")
        elif "source_id" in source and not _public_identifier(source_id_value):
            errors.append(
                f"source field is not a public identifier: {source_id}: source_id"
            )
        privacy = source.get("privacy")
        if not isinstance(privacy, str) or privacy not in SOURCE_PRIVACY:
            errors.append(
                f"invalid source privacy: {source_id}: {_stable_display(privacy)}"
            )
        if privacy == "local_only" and source.get("repository_path"):
            errors.append("local-only source exposes repository path")
        if privacy == "public_ok" and source.get("repository_path") is not None:
            if _normalized_repository_path(source.get("repository_path")) is None:
                errors.append(
                    "public source repository path is not normalized relative: "
                    f"{source_id}"
                )
        for field in ("sha256", "content_hash"):
            if field in source and not _bounded_string(source[field], 128):
                errors.append(f"source field must be a string: {source_id}: {field}")
            elif field in source and not _sha256(source[field]):
                errors.append(f"source hash is not sha256: {source_id}: {field}")

    for segment in sections.get("segments", []):
        if not isinstance(segment, dict):
            errors.append("segment entry must be an object")
            continue
        location = _segment_location(segment)
        for field in ("segment_id", "source_id", "location"):
            if field in segment and not _bounded_string(segment[field]):
                errors.append(
                    "segment field must be a bounded string: "
                    f"{location}: {field}"
                )
            elif field in segment and not _public_identifier(segment[field]):
                errors.append(
                    "segment field is not a public identifier: "
                    f"{location}: {field}"
                )
        status = segment.get("status")
        if not isinstance(status, str) or status not in FINAL_SEGMENT_STATUSES:
            errors.append(f"unclassified source segment: {location}")
        elif status == "excluded_with_reason":
            if not _bounded_string(segment.get("reason")):
                errors.append(f"excluded segment lacks reason: {location}")
            if not _has_stable_segment_location(segment):
                errors.append("excluded segment lacks source location")
        if "approved_excerpt" in segment and not _bounded_string(
            segment["approved_excerpt"], MAX_EXCERPT_CHARS
        ):
            errors.append(
                "segment field must be a bounded string: "
                f"{location}: approved_excerpt"
            )

    for candidate in sections.get("candidates", []):
        if not isinstance(candidate, dict):
            errors.append("candidate entry must be an object")
            continue
        term = _candidate_term(candidate)
        for field in ("term", "word", "source_location"):
            if field in candidate and not _bounded_string(candidate[field]):
                errors.append(
                    "candidate field must be a bounded string: "
                    f"{term}: {field}"
                )
            elif (
                field == "source_location"
                and field in candidate
                and not _public_identifier(candidate[field])
            ):
                errors.append(
                    "candidate field is not a public identifier: "
                    f"{term}: {field}"
                )
        decision = candidate.get("decision")
        if decision is None or decision == "":
            errors.append(f"candidate lacks decision: {term}")
            continue
        if not isinstance(decision, str) or decision not in CANDIDATE_DECISIONS:
            errors.append(
                f"invalid candidate decision: {term}: {_stable_display(decision)}"
            )
            continue
        if decision in {"exclude", "asr_corrected"}:
            if not _bounded_string(candidate.get("reason")):
                errors.append(f"candidate {decision} lacks reason: {term}")
            if not _bounded_string(candidate.get("source_location")):
                errors.append(
                    f"candidate {decision} lacks source location: {term}"
                )

    for cards in frozen_sections.values():
        for card in cards:
            if not isinstance(card, dict):
                errors.append("frozen card entry must be an object")
                continue
            card_id_value = card.get("card_id") or card.get("id")
            card_id = (
                card_id_value.strip()
                if _public_identifier(card_id_value)
                else "<unknown>"
            )
            for field in ("card_id", "id"):
                if field in card and not _bounded_string(card[field]):
                    errors.append(
                        f"frozen card field must be a string: {card_id}: {field}"
                    )
                elif field in card and not _public_identifier(card[field]):
                    errors.append(
                        "frozen card field is not a public identifier: "
                        f"{card_id}: {field}"
                    )
            if card.get("privacy") != "public_ok":
                errors.append(f"frozen derived card is not public_ok: {card_id}")

    return sorted(errors)


def _public_string_fields(
    item: object, fields: dict[str, int]
) -> dict[str, str]:
    if not isinstance(item, dict):
        return {}
    return {
        field: item[field]
        for field, limit in fields.items()
        if field in item and _bounded_string(item[field], limit)
    }


def public_inventory_view(inventory: dict) -> dict:
    """Build a repository-safe view without machine paths or raw source text."""
    if not isinstance(inventory, dict):
        inventory = {}
    public_view: dict = {}
    if isinstance(inventory.get("schema_version"), (str, int)):
        public_view["schema_version"] = inventory["schema_version"]
    public_view.update(
        _public_string_fields(
            inventory, {"inventory_id": 256, "generated_at": 64}
        )
    )
    if not _public_identifier(public_view.get("inventory_id")):
        public_view.pop("inventory_id", None)
    coverage = inventory.get("coverage")
    public_view["coverage"] = {
        field: coverage[field]
        for field in COVERAGE_FIELDS
        if isinstance(coverage, dict)
        and isinstance(coverage.get(field), int)
        and not isinstance(coverage.get(field), bool)
        and coverage[field] >= 0
    }

    public_sources: list[dict] = []
    sources = inventory.get("sources", [])
    for source in sources if isinstance(sources, list) else []:
        public_source = _public_string_fields(
            source,
            {
                "source_id": 256,
                "privacy": 32,
                "sha256": 128,
                "content_hash": 128,
            },
        )
        if not _public_identifier(public_source.get("source_id")):
            public_source.pop("source_id", None)
        if public_source.get("privacy") not in SOURCE_PRIVACY:
            public_source.pop("privacy", None)
        for field in ("sha256", "content_hash"):
            if not _sha256(public_source.get(field)):
                public_source.pop(field, None)
        if isinstance(source, dict) and source.get("privacy") == "public_ok":
            repository_path = _normalized_repository_path(
                source.get("repository_path")
            )
            if repository_path is not None:
                public_source["repository_path"] = repository_path
        public_sources.append(public_source)
    public_view["sources"] = public_sources

    segments = inventory.get("segments", [])
    public_view["segments"] = [
        _public_string_fields(
            segment,
            {
                "segment_id": 256,
                "source_id": 256,
                "location": 256,
                "status": 64,
                "approved_excerpt": MAX_EXCERPT_CHARS,
            },
        )
        for segment in segments if isinstance(segments, list)
    ]
    for segment in public_view["segments"]:
        for field in ("segment_id", "source_id", "location"):
            if not _public_identifier(segment.get(field)):
                segment.pop(field, None)
        if segment.get("status") not in FINAL_SEGMENT_STATUSES:
            segment.pop("status", None)
    candidates = inventory.get("candidates", [])
    public_view["candidates"] = [
        _public_string_fields(
            candidate,
            {"term": 256, "word": 256, "decision": 64, "source_location": 256},
        )
        for candidate in candidates if isinstance(candidates, list)
    ]
    for candidate in public_view["candidates"]:
        if candidate.get("decision") not in CANDIDATE_DECISIONS:
            candidate.pop("decision", None)
        if not _public_identifier(candidate.get("source_location")):
            candidate.pop("source_location", None)

    for field in ("frozen_cards", "frozen_derived_cards", "derived_cards"):
        if isinstance(inventory.get(field), list):
            public_view[field] = [
                _public_string_fields(
                    card, {"card_id": 256, "id": 256, "privacy": 32}
                )
                for card in inventory.get(field, [])
            ]
            for card in public_view[field]:
                for id_field in ("card_id", "id"):
                    if not _public_identifier(card.get(id_field)):
                        card.pop(id_field, None)
                if card.get("privacy") != "public_ok":
                    card.pop("privacy", None)

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
