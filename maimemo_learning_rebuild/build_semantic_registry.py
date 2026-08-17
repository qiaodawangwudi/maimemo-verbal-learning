"""Assemble the authoritative semantic registry without promoting weak candidates."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from .markji import parse_card
from .models import validate_semantic_record
from .review import review_registry_precheck
from .sources import (
    _docx_locations,
    _transcript_locations,
    load_source_catalog,
    validate_evidence,
)


LESSON_FIVE_REQUIRED_OVERRIDE_FIELDS = {
    "meaning",
    "distinctive_feature",
    "recognition_cues",
    "dimensions",
    "comparison_edges",
    "misuse_boundary",
}

FOUR_POEMS_REQUIRED_OVERRIDE_FIELDS = LESSON_FIVE_REQUIRED_OVERRIDE_FIELDS


def apply_lesson_five_override(
    record: dict, override: dict, batch_name: str
) -> dict:
    """Promote only a complete, manually reviewed replacement for a quarantined candidate."""
    if override.get("status") != "ready":
        blocker = override.get("review_blocker")
        if blocker and blocker not in record.setdefault("review_blockers", []):
            record["review_blockers"].append(blocker)
        return record
    missing = sorted(
        field
        for field in LESSON_FIVE_REQUIRED_OVERRIDE_FIELDS
        if field not in override or override[field] in (None, "")
    )
    if missing:
        blocker = "人工覆盖缺少完整学习字段"
        if blocker not in record.setdefault("review_blockers", []):
            record["review_blockers"].append(blocker)
        return record
    record.update({field: override[field] for field in LESSON_FIVE_REQUIRED_OVERRIDE_FIELDS})
    if "source_kind" in override:
        record["source_kind"] = override["source_kind"]
    if "evidence" in override:
        record["evidence"] = override["evidence"]
    record["status"] = "ready"
    record["typical_contexts"] = override.get("typical_contexts", [])
    record.pop("candidate", None)
    record.pop("review_blockers", None)
    provenance = record.setdefault("provenance", {})
    provenance.pop("derived_content_quarantined", None)
    provenance["manual_semantic_review"] = batch_name
    return record


def apply_four_poems_override(record: dict, override: dict, batch_name: str) -> dict:
    """Apply a complete reviewed meaning and, when supplied, its exact source evidence."""
    missing = sorted(
        field
        for field in FOUR_POEMS_REQUIRED_OVERRIDE_FIELDS
        if field not in override or override[field] in (None, "")
    )
    if missing:
        blocker = "人工覆盖缺少完整学习字段"
        if blocker not in record.setdefault("review_blockers", []):
            record["review_blockers"].append(blocker)
        return record
    record.update({field: override[field] for field in FOUR_POEMS_REQUIRED_OVERRIDE_FIELDS})
    if "source_kind" in override:
        record["source_kind"] = override["source_kind"]
    if "evidence" in override:
        record["evidence"] = override["evidence"]
    record["status"] = "ready"
    record["typical_contexts"] = override.get("typical_contexts", [])
    record.pop("candidate", None)
    record.pop("review_blockers", None)
    record["provenance"] = {
        "batch": "four-poems",
        "manual_semantic_review": batch_name,
    }
    return record


def _load_records(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8-sig")).get("records", [])


def _target_terms(source_root: Path) -> tuple[list[str], set[str]]:
    snapshot_path = source_root / "maimemo_four_poems" / "audit_readonly" / "current_library_snapshot_2026-08-17.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8-sig"))
    parsed = [parse_card(card) for card in snapshot.get("cards", [])]
    base_terms = [card.term for card in parsed if card.card_type == "base"]
    four_poems = _load_records(source_root / "maimemo_four_poems" / "extracted_registry.json")
    ordered = list(base_terms)
    seen = set(ordered)
    for record in four_poems:
        if record["term"] not in seen:
            ordered.append(record["term"])
            seen.add(record["term"])
    return ordered, seen


def _full_evidence(
    source_name: str,
    locations: list[str],
    catalog_by_name: dict[str, dict],
) -> list[dict]:
    source = catalog_by_name[source_name]
    path = Path(source["path"])
    indexed = (
        _docx_locations(path)
        if path.suffix.lower() == ".docx"
        else _transcript_locations(path)
    )
    return [
        {"source": source_name, "location": location, "quote": indexed[location]}
        for location in locations
        if location in indexed
    ]


def _filter_edges(edges: list[dict], target_terms: set[str]) -> tuple[list[dict], list[dict]]:
    kept = []
    for original in edges:
        if original.get("other_term") not in target_terms:
            continue
        edge = dict(original)
        other = str(edge.get("other_term") or "")
        text = str(edge.get("minimum_difference") or "")
        edge["minimum_difference"] = text
        kept.append(edge)
    dropped = [edge for edge in edges if edge.get("other_term") not in target_terms]
    return kept, dropped


def _make_edge_references_explicit(term: str, edges: list[dict]) -> list[dict]:
    explicit: list[dict] = []
    for original in edges:
        edge = dict(original)
        pair = f"{term}与{edge.get('other_term', '')}"
        text = str(edge.get("minimum_difference") or "")
        edge["minimum_difference"] = text.replace("两者", pair).replace("二者", pair)
        explicit.append(edge)
    return explicit


def _finalize_candidate(record: dict, catalog: dict) -> dict:
    if record.get("status") != "ready":
        return record
    errors = validate_semantic_record(record)
    if record.get("source_kind") == "teacher_transcript":
        for evidence in record.get("evidence", []):
            errors.extend(validate_evidence(catalog, evidence))
    if errors:
        record["status"] = "pending"
        record["review_blockers"] = sorted(set(errors))
    return record


def build_registry(source_root: Path, catalog: dict) -> tuple[dict, list[dict]]:
    ordered_terms, target_terms = _target_terms(source_root)
    catalog_by_name = {source["name"]: source for source in catalog["sources"]}
    approved_path = Path(__file__).parent / "examples" / "approved_learning_examples.json"
    approved = json.loads(approved_path.read_text(encoding="utf-8"))
    approved_by_term = {record["term"]: record for record in approved["records"]}
    overrides_path = Path(__file__).parent / "artifacts" / "semantic_overrides_20260108.json"
    lesson_five_notes = json.loads(
        overrides_path.read_text(encoding="utf-8")
    )["records"]
    lesson_five_overrides: dict[str, tuple[dict, str]] = {}
    for path in sorted(
        (Path(__file__).parent / "artifacts").glob(
            "semantic_overrides_20260108_batch*.json"
        )
    ):
        batch = json.loads(path.read_text(encoding="utf-8"))["records"]
        duplicates = set(lesson_five_overrides) & set(batch)
        if duplicates:
            raise ValueError(f"duplicate 20260108 overrides: {sorted(duplicates)}")
        lesson_five_overrides.update(
            {term: (override, path.stem) for term, override in batch.items()}
        )
    four_poems_overrides: dict[str, tuple[dict, str]] = {}
    for path in sorted(
        (Path(__file__).parent / "artifacts").glob(
            "semantic_overrides_four_poems_batch*.json"
        )
    ):
        batch = json.loads(path.read_text(encoding="utf-8"))["records"]
        duplicates = set(four_poems_overrides) & set(batch)
        if duplicates:
            raise ValueError(f"duplicate four-poems overrides: {sorted(duplicates)}")
        four_poems_overrides.update(
            {term: (override, path.stem) for term, override in batch.items()}
        )

    archive_by_term: dict[str, tuple[dict, str]] = {}
    for path in sorted((source_root / "judgment_archive_v2").glob("judgments_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        for record in payload.get("records", []):
            archive_by_term.setdefault(record["term"], (record, path.name))
    lesson_five = _load_records(source_root / "maimemo_20260108" / "registry.json")
    lesson_five_by_term = {record["term"]: record for record in lesson_five}
    four_poems = _load_records(source_root / "maimemo_four_poems" / "extracted_registry.json")
    four_poems_by_term = {record["term"]: record for record in four_poems}

    lesson_five_source = "20260108 选词刷题5_文稿.docx"
    lesson_five_locations = _docx_locations(catalog_by_name[lesson_five_source]["path"])
    lesson_five_term_locations = {
        term: [location for location, text in lesson_five_locations.items() if term in text]
        for term in target_terms
    }

    records: list[dict] = []
    log: list[dict] = []
    for index, term in enumerate(ordered_terms):
        provenance: dict
        if term in archive_by_term:
            source, archive_name = archive_by_term[term]
            edges, dropped = _filter_edges(source.get("comparison_edges", []), target_terms)
            edges = _make_edge_references_explicit(term, edges)
            locations = [item["paragraph"] for item in source.get("source_evidence", [])]
            record = {
                "term": term,
                "sense_id": f"{term}::20260107课程义::001",
                "status": "ready" if source.get("archive_status") == "ready" else "pending",
                "source_kind": "teacher_transcript",
                "meaning": source.get("course_sense", ""),
                "distinctive_feature": source.get("semantic_core", ""),
                "recognition_cues": [item["judgment"] for item in source.get("dimensions", [])[:2]],
                "dimensions": source.get("dimensions", []),
                "comparison_edges": edges,
                "misuse_boundary": source.get("misuse_boundary", ""),
                "typical_contexts": [],
                "evidence": _full_evidence(
                    "20260107 选词刷题4_文稿.docx", locations, catalog_by_name
                ),
                "registry_order": index,
                "provenance": {"batch": "20260107", "judgment_archive": archive_name},
            }
            if dropped:
                record["excluded_edges_outside_library"] = dropped
            provenance = {"tier": "reviewed_archive_rebound_to_original"}
        elif term in lesson_five_by_term:
            source = lesson_five_by_term[term]
            edges, dropped = _filter_edges(source.get("comparison_edges", []), target_terms)
            edges = _make_edge_references_explicit(term, edges)
            locations = lesson_five_term_locations.get(term, [])[:3]
            evidence = _full_evidence(lesson_five_source, locations, catalog_by_name)
            note = lesson_five_notes.get(term)
            record = {
                "term": term,
                "sense_id": source.get("sense_id") or f"{term}::20260108课程义::001",
                "status": "pending",
                "source_kind": "teacher_transcript" if locations else "secondary_reference",
                "evidence": evidence,
                "registry_order": index,
                "candidate": {
                    "course_sense": source.get("course_sense", ""),
                    "semantic_core": source.get("semantic_core", ""),
                    "dimensions": source.get("dimensions", []),
                    "comparison_edges": edges,
                    "misuse_boundary": (
                        note.get("misuse_boundary")
                        if note
                        else source.get("misuse_boundary", "")
                    ),
                },
                "review_blockers": [
                    "20260108派生档案按单题选项生成全连接比较边，未经逐词人工语义重建，不得升为ready。"
                ],
                "provenance": {
                    "batch": "20260108",
                    "derived_registry": "maimemo_20260108/registry.json",
                    "derived_content_quarantined": True,
                },
            }
            if not locations:
                record["review_blockers"].append(
                    "原始课程文稿中未按规范词面定位，不能只凭派生讲义升为ready。"
                )
            if source.get("status") != "ready":
                record["review_blockers"].append(
                    "派生判断档案本身标为pending，必须重新裁定后才能升为ready。"
                )
            if note:
                record["provenance"]["manual_boundary_review_only"] = True
                if note.get("review_blocker"):
                    record["review_blockers"].append(note["review_blocker"])
            if dropped:
                record["excluded_edges_outside_library"] = dropped
            if term in lesson_five_overrides:
                override, batch_name = lesson_five_overrides[term]
                record = apply_lesson_five_override(record, override, batch_name)
            provenance = {"tier": "derived_guide_quarantined_pending_manual_rebuild"}
        elif term in approved_by_term:
            source = dict(approved_by_term[term])
            evidence: list[dict] = []
            for item in source.get("evidence", []):
                evidence.extend(
                    _full_evidence(
                        item["source"], [item["location"]], catalog_by_name
                    )
                )
            source["evidence"] = evidence
            source["registry_order"] = index
            source["provenance"] = {"batch": "approved_examples", "manual_review": True}
            record = source
            provenance = {"tier": "manually_reviewed_example"}
        elif term in four_poems_by_term:
            source = four_poems_by_term[term]
            record = {
                "term": term,
                "sense_id": source.get("sense_id") or f"{term}::逻辑填空400词课程义::001",
                "status": "pending",
                "source_kind": source.get("source_kind", "historical_only"),
                "registry_order": index,
                "evidence": source.get("evidence", []),
                "candidate": {
                    "course_sense": source.get("course_sense", ""),
                    "semantic_core": source.get("semantic_core", ""),
                    "dimensions": source.get("dimensions", []),
                    "misuse_boundary": source.get("misuse_boundary", ""),
                },
                "review_blockers": [
                    "旧抽取的词义与语义核心重复，且缺少可靠最小差别；必须重新阅读原段落。"
                ],
                "provenance": {"batch": "four-poems", "source_index_only": True},
            }
            override_entry = four_poems_overrides.get(term)
            if override_entry:
                override, batch_name = override_entry
                record = apply_four_poems_override(record, override, batch_name)
            provenance = {
                "tier": (
                    "manually_reviewed_from_transcript"
                    if override_entry
                    else "source_index_pending_semantic_rebuild"
                )
            }
        else:
            record = {
                "term": term,
                "sense_id": f"{term}::历史卡待核::001",
                "status": "pending",
                "source_kind": "historical_only",
                "registry_order": index,
                "review_blockers": ["只有线上旧卡，尚未定位课程来源。"],
                "provenance": {"batch": "historical-card-only"},
            }
            provenance = {"tier": "historical_only"}

        record = _finalize_candidate(record, catalog)
        records.append(record)
        if record["status"] == "ready":
            log.append(
                {
                    "term": term,
                    "status": "ready",
                    "meaning_answer": record["meaning"],
                    "distinctive_answer": record["distinctive_feature"],
                    "decision_dimensions": record.get("dimensions", []),
                    "transfer_boundary": record["misuse_boundary"],
                    "provenance": provenance,
                }
            )
        else:
            log.append(
                {
                    "term": term,
                    "status": record["status"],
                    "unresolved_reason": record.get("review_blockers", []),
                    "provenance": provenance,
                }
            )

    counts = Counter(record["status"] for record in records)
    registry = {
        "schema_version": 1,
        "authority": "single_authoritative_semantic_registry",
        "scope": "605 current base cards plus 16 missing four-poems terms",
        "totals": {"records": len(records), "statuses": dict(sorted(counts.items()))},
        "records": records,
    }
    return registry, log


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--groups", type=Path, required=True)
    parser.add_argument("--registry-output", type=Path, required=True)
    parser.add_argument("--log-output", type=Path, required=True)
    args = parser.parse_args()
    catalog = load_source_catalog(args.sources)
    group_payload = json.loads(args.groups.read_text(encoding="utf-8-sig"))
    registry, log = build_registry(args.source_root, catalog)
    report = review_registry_precheck(
        registry["records"], catalog, group_payload.get("groups", [])
    )
    if report["hard_errors"]:
        for detail in report["details"]:
            print(json.dumps(detail, ensure_ascii=False))
        return 1
    args.registry_output.parent.mkdir(parents=True, exist_ok=True)
    args.registry_output.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.log_output.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in log),
        encoding="utf-8",
    )
    print(json.dumps({key: value for key, value in report.items() if key != "details"}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
