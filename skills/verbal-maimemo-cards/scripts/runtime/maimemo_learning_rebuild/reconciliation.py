"""Reconcile reviewed semantic identities against the complete card library."""

from __future__ import annotations

import argparse
import hashlib
import json
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from .application_blind_review import load_strict_json, strict_json_error
from .markji import parse_card


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _snapshot_hash(snapshot: dict) -> str:
    return _canonical_hash(snapshot)


def semantic_registry_hash(records: list[dict]) -> str:
    return _canonical_hash(records)


def normalize_term(term: object) -> str:
    """Return a comparison key that catches width, case and spacing variants."""

    normalized = unicodedata.normalize("NFKC", str(term or "")).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _parse_snapshot_cards(snapshot: dict) -> list:
    if not isinstance(snapshot, dict) or strict_json_error(snapshot):
        raise ValueError("snapshot must be a strict JSON object")
    raw_cards = snapshot.get("cards", [])
    if not isinstance(raw_cards, list) or any(
        not isinstance(card, dict) for card in raw_cards
    ):
        raise ValueError("snapshot cards must be a list of objects")
    parsed = [parse_card(card) for card in raw_cards]
    card_ids = [card.card_id for card in parsed]
    if any(not card_id for card_id in card_ids):
        raise ValueError("snapshot card_id is required")
    duplicate_ids = sorted(
        card_id for card_id, count in Counter(card_ids).items() if count > 1
    )
    if duplicate_ids:
        raise ValueError("duplicate snapshot card_id: " + "、".join(duplicate_ids))
    return parsed


def reconciliation_hash(report: dict) -> str:
    if not isinstance(report, dict) or strict_json_error(report):
        raise ValueError("library reconciliation is not strict JSON")
    payload = {
        key: value for key, value in report.items() if key != "reconciliation_hash"
    }
    return _canonical_hash(payload)


def _resolution_error(
    resolution: object,
    *,
    candidates: list[str],
    multiple_senses: bool,
) -> str | None:
    if not isinstance(resolution, dict):
        return "resolution must be an object"
    decision = resolution.get("decision")
    canonical = resolution.get("canonical_card_id", "")
    retire = resolution.get("retire_card_ids", [])
    reason = resolution.get("reason")
    if decision not in {
        "reuse_existing",
        "create_new",
        "merge_existing",
        "layer_senses",
    }:
        return "invalid reconciliation decision"
    if not isinstance(reason, str) or not reason.strip():
        return "explicit resolution requires reason"
    if not isinstance(canonical, str) or not isinstance(retire, list) or any(
        not isinstance(card_id, str) for card_id in retire
    ):
        return "resolution card identities are invalid"
    if len(retire) != len(set(retire)) or canonical in retire:
        return "resolution card identities are invalid"
    candidate_set = set(candidates)
    if decision == "create_new":
        if candidates or canonical or retire or multiple_senses:
            return "create requires zero reusable candidates and one sense"
    elif decision == "reuse_existing":
        if len(candidates) != 1 or canonical != candidates[0] or retire or multiple_senses:
            return "reuse must target the sole same-term candidate"
    elif decision == "merge_existing":
        if len(candidates) < 2 or canonical not in candidate_set:
            return "merge requires a canonical duplicate candidate"
        if set(retire) != candidate_set - {canonical}:
            return "merge must account for every duplicate candidate"
    elif decision == "layer_senses":
        if not multiple_senses:
            return "layer_senses requires multiple reviewed senses"
        if len(candidates) > 1:
            if canonical not in candidate_set or set(retire) != candidate_set - {canonical}:
                return "layer_senses must account for every duplicate candidate"
        elif len(candidates) == 1 and (canonical != candidates[0] or retire):
            return "layer_senses must reuse the sole candidate"
        elif not candidates and (canonical or retire):
            return "layer_senses cannot name absent cards"
    return None


def build_library_reconciliation(
    snapshot: dict,
    records: list[dict],
    *,
    resolutions: dict[str, dict] | None = None,
) -> dict:
    """Build a deterministic, snapshot-bound duplicate reconciliation artifact."""

    if not isinstance(records, list) or any(
        not isinstance(record, dict) for record in records
    ) or strict_json_error(records):
        raise ValueError("semantic records must be a strict JSON list of objects")
    if resolutions is None:
        resolutions = {}
    if not isinstance(resolutions, dict) or any(
        not isinstance(key, str) for key in resolutions
    ) or strict_json_error(resolutions):
        raise ValueError("resolutions must be a strict JSON object")

    parsed = _parse_snapshot_cards(snapshot)
    base_by_key: dict[str, list] = defaultdict(list)
    for card in parsed:
        if card.card_type == "base":
            base_by_key[normalize_term(card.term)].append(card)
    for cards in base_by_key.values():
        cards.sort(key=lambda card: (card.card_id, card.title))

    senses_by_key: Counter[str] = Counter(
        normalize_term(record.get("term")) for record in records
    )
    report_snapshot_hash = _snapshot_hash(snapshot)
    entries: list[dict] = []
    errors: list[str] = []
    used_resolution_keys: set[str] = set()
    ordered_records = sorted(
        records,
        key=lambda record: (
            normalize_term(record.get("term")),
            str(record.get("sense_id") or ""),
        ),
    )
    for record in ordered_records:
        term = str(record.get("term") or "").strip()
        sense_id = str(record.get("sense_id") or "").strip()
        normalized = normalize_term(term)
        raw_aliases = record.get("aliases", [])
        if not isinstance(raw_aliases, list) or any(
            not isinstance(alias, str) or not alias.strip() for alias in raw_aliases
        ):
            raise ValueError(f"semantic aliases must be nonempty strings: {sense_id}")
        match_terms = list(dict.fromkeys([term, *(alias.strip() for alias in raw_aliases)]))
        match_keys = list(dict.fromkeys(normalize_term(value) for value in match_terms))
        candidates_by_id = {
            card.card_id: card
            for key in match_keys
            for card in base_by_key.get(key, [])
        }
        candidates = sorted(
            candidates_by_id.values(), key=lambda card: (card.card_id, card.title)
        )
        candidate_ids = [card.card_id for card in candidates]
        candidate_titles = [card.title for card in candidates]
        multiple_senses = senses_by_key[normalized] > 1
        resolution = resolutions.get(sense_id)
        entry_errors: list[str] = []

        if not term or not sense_id or not normalized:
            decision = "manual_review"
            entry_errors.append("term and sense_id are required")
        elif resolution is not None:
            used_resolution_keys.add(sense_id)
            resolution_error = _resolution_error(
                resolution,
                candidates=candidate_ids,
                multiple_senses=multiple_senses,
            )
            if resolution_error:
                decision = "manual_review"
                entry_errors.append(resolution_error)
            else:
                decision = str(resolution["decision"])
        elif multiple_senses:
            decision = "manual_review"
            entry_errors.append(f"同词存在多个义项，必须决定分层或拆分：{term}")
        elif len(candidates) == 0:
            decision = "create_new"
        elif len(candidates) == 1:
            decision = "manual_review"
            entry_errors.append(
                f"现有同词卡缺少义项身份，必须确认同义项后才能复用：{term}"
            )
        else:
            decision = "manual_review"
            entry_errors.append(f"同词存在多张旧卡，必须选择主卡并合并：{term}")

        canonical = ""
        retire: list[str] = []
        reason = ""
        if decision == "create_new":
            reason = "全库快照中没有规范词面一致的基础卡，允许进入新建候选。"
        elif resolution is not None and decision != "manual_review":
            canonical = str(resolution.get("canonical_card_id") or "")
            retire = list(resolution.get("retire_card_ids") or [])
            reason = str(resolution.get("reason") or "").strip()

        entry = {
            "term": term,
            "sense_id": sense_id,
            "normalized_term": normalized,
            "match_terms": match_terms,
            "candidate_card_ids": candidate_ids,
            "candidate_titles": candidate_titles,
            "decision": decision,
            "canonical_card_id": canonical,
            "retire_card_ids": retire,
            "proof_snapshot_hash": report_snapshot_hash,
            "reason": reason or "存在未解决的全库重复或义项冲突，禁止自动写入。",
        }
        entries.append(entry)
        errors.extend(entry_errors)

    for unknown_key in sorted(set(resolutions) - used_resolution_keys):
        errors.append(f"resolution targets unknown sense_id: {unknown_key}")

    owners: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        canonical = str(entry.get("canonical_card_id") or "")
        if canonical and entry.get("decision") in {
            "reuse_existing",
            "merge_existing",
            "layer_senses",
        }:
            owners[canonical].append(entry)
    for card_id, owner_entries in sorted(owners.items()):
        shared_layer = len({entry.get("normalized_term") for entry in owner_entries}) == 1 and all(
            entry.get("decision") == "layer_senses" for entry in owner_entries
        )
        if len(owner_entries) > 1 and not shared_layer:
            errors.append(f"card_id assigned to multiple semantic identities: {card_id}")

    report = {
        "schema_version": 1,
        "status": "blocked" if errors else "passed",
        "snapshot_hash": report_snapshot_hash,
        "semantic_registry_hash": semantic_registry_hash(records),
        "entries": entries,
        "errors": errors,
    }
    report["reconciliation_hash"] = reconciliation_hash(report)
    return report


def validate_library_reconciliation(
    report: object,
    snapshot: dict,
    records: list[dict],
) -> list[str]:
    errors = validate_library_reconciliation_binding(report, snapshot)
    if not isinstance(report, dict):
        return errors
    if report.get("semantic_registry_hash") != semantic_registry_hash(records):
        errors.append("reconciliation semantic registry hash mismatch")
    entries = report.get("entries")
    if isinstance(entries, list):
        expected_keys = sorted(str(record.get("sense_id") or "") for record in records)
        actual_keys = sorted(
            str(entry.get("sense_id") or "")
            for entry in entries
            if isinstance(entry, dict)
        )
        if actual_keys != expected_keys:
            errors.append("reconciliation entries do not cover every semantic identity")
        records_by_sense = {
            str(record.get("sense_id") or ""): record for record in records
        }
        records_by_term: dict[str, list[dict]] = defaultdict(list)
        for record in records:
            records_by_term[normalize_term(record.get("term"))].append(record)
        entries_by_sense = {
            str(entry.get("sense_id") or ""): entry
            for entry in entries
            if isinstance(entry, dict)
        }
        for same_term_records in records_by_term.values():
            if len(same_term_records) < 2:
                continue
            same_term_entries = [
                entries_by_sense.get(str(record.get("sense_id") or ""), {})
                for record in same_term_records
            ]
            dispositions = {
                (
                    entry.get("decision"),
                    entry.get("canonical_card_id"),
                    tuple(entry.get("retire_card_ids") or []),
                )
                for entry in same_term_entries
            }
            if len(dispositions) != 1 or next(iter(dispositions), (None,))[0] != "layer_senses":
                term = str(same_term_records[0].get("term") or "")
                errors.append(
                    f"multiple senses require one shared layer_senses decision: {term}"
                )
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            sense_id = str(entry.get("sense_id") or "")
            record = records_by_sense.get(sense_id)
            if record is None:
                continue
            aliases = record.get("aliases", [])
            if not isinstance(aliases, list):
                errors.append(f"semantic aliases are invalid: {sense_id}")
                continue
            expected_match_terms = list(
                dict.fromkeys(
                    [
                        str(record.get("term") or "").strip(),
                        *(str(alias).strip() for alias in aliases),
                    ]
                )
            )
            if entry.get("match_terms") != expected_match_terms:
                errors.append(f"reconciliation aliases differ from semantic registry: {sense_id}")
    return list(dict.fromkeys(errors))


def validate_library_reconciliation_binding(
    report: object,
    snapshot: dict,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(report, dict) or strict_json_error(report):
        return ["library reconciliation must be a strict JSON object"]
    if report.get("schema_version") != 1:
        errors.append("library reconciliation schema mismatch")
    if report.get("status") != "passed":
        errors.append("library reconciliation is not passed")
    if report.get("snapshot_hash") != _snapshot_hash(snapshot):
        errors.append("reconciliation snapshot hash mismatch")
    try:
        parsed = _parse_snapshot_cards(snapshot)
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(f"invalid reconciliation snapshot: {exc}")
        parsed = []
    base_by_key: dict[str, list] = defaultdict(list)
    for card in parsed:
        if card.card_type == "base":
            base_by_key[normalize_term(card.term)].append(card)
    for cards in base_by_key.values():
        cards.sort(key=lambda card: (card.card_id, card.title))
    entries = report.get("entries")
    if not isinstance(entries, list) or any(
        not isinstance(entry, dict) for entry in entries
    ):
        errors.append("reconciliation entries must be a list of objects")
    else:
        allowed = {"reuse_existing", "create_new", "merge_existing", "layer_senses"}
        for entry in entries:
            sense_id = str(entry.get("sense_id") or "")
            term = str(entry.get("term") or "")
            normalized = normalize_term(term)
            match_terms = entry.get("match_terms")
            if not isinstance(match_terms, list) or any(
                not isinstance(value, str) or not value.strip() for value in match_terms
            ):
                errors.append(f"reconciliation match terms are invalid: {sense_id}")
                match_terms = [term]
            match_keys = list(dict.fromkeys(normalize_term(value) for value in match_terms))
            candidates_by_id = {
                card.card_id: card
                for key in match_keys
                for card in base_by_key.get(key, [])
            }
            candidates = sorted(
                candidates_by_id.values(), key=lambda card: (card.card_id, card.title)
            )
            candidate_ids = [card.card_id for card in candidates]
            candidate_titles = [card.title for card in candidates]
            decision = entry.get("decision")
            if entry.get("normalized_term") != normalized:
                errors.append(f"reconciliation normalized term mismatch: {sense_id}")
            if (
                entry.get("candidate_card_ids") != candidate_ids
                or entry.get("candidate_titles") != candidate_titles
            ):
                errors.append(
                    f"reconciliation candidates differ from full snapshot: {sense_id}"
                )
            if decision not in allowed:
                errors.append(f"unresolved reconciliation entry: {sense_id}")
            elif decision == "create_new" and candidate_ids:
                errors.append(f"create_new has a reusable same-term card: {sense_id}")
            elif decision == "reuse_existing" and (
                len(candidate_ids) != 1
                or entry.get("canonical_card_id") != candidate_ids[0]
                or entry.get("retire_card_ids") != []
            ):
                errors.append(f"reuse_existing does not bind the sole candidate: {sense_id}")
            elif decision in {"merge_existing", "layer_senses"}:
                canonical = entry.get("canonical_card_id")
                retire = entry.get("retire_card_ids")
                if not isinstance(retire, list) or canonical not in candidate_ids or set(
                    retire
                ) != set(candidate_ids) - {canonical}:
                    errors.append(f"duplicate disposition is incomplete: {sense_id}")
            if entry.get("proof_snapshot_hash") != report.get("snapshot_hash"):
                errors.append(f"reconciliation entry snapshot proof mismatch: {sense_id}")
    try:
        if report.get("reconciliation_hash") != reconciliation_hash(report):
            errors.append("reconciliation hash mismatch")
    except (TypeError, ValueError, OverflowError, RecursionError):
        errors.append("reconciliation hash mismatch")
    return list(dict.fromkeys(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--resolutions", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        snapshot = load_strict_json(args.snapshot)
        registry_payload = load_strict_json(args.registry)
        resolutions = load_strict_json(args.resolutions) if args.resolutions else {}
        if not isinstance(snapshot, dict) or not isinstance(registry_payload, dict):
            raise ValueError("snapshot and registry must be objects")
        records = registry_payload.get("records")
        if not isinstance(records, list):
            raise ValueError("registry records must be a list")
        report = build_library_reconciliation(
            snapshot,
            records,
            resolutions=resolutions,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "entries": len(report["entries"]),
                    "errors": len(report["errors"]),
                    "reconciliation_hash": report["reconciliation_hash"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0 if report["status"] == "passed" else 1
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "errors": [str(exc)]}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
