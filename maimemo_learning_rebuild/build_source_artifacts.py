"""Build the frozen source catalog and per-card provenance ledger."""

from __future__ import annotations

import argparse
import copy
import json
import os
from collections import Counter
from pathlib import Path

from .markji import parse_card
from .sources import build_source_entry, validate_card_provenance, validate_source_catalog


def _relative_path(path: str | Path, artifact_dir: Path) -> str:
    return Path(os.path.relpath(Path(path).resolve(), artifact_dir.resolve())).as_posix()


def portable_artifacts(catalog: dict, provenance: dict, artifact_dir: Path) -> tuple[dict, dict]:
    """Return publishable copies without user names or absolute machine paths."""
    public_catalog = copy.deepcopy(catalog)
    public_provenance = copy.deepcopy(provenance)
    public_catalog["generated_from"] = "<LOCAL_SOURCE_ROOT>"
    for source in public_catalog.get("sources", []):
        source["path"] = _relative_path(source["path"], artifact_dir)
    public_provenance["snapshot"] = _relative_path(
        public_provenance["snapshot"], artifact_dir
    )
    return public_catalog, public_provenance


def _source_specs(source_root: Path) -> list[tuple[Path, str, str, str, str]]:
    desktop = Path.home() / "Desktop"
    specs: list[tuple[Path, str, str, str, str]] = [
        (desktop / "20260107 选词刷题4_文稿.docx", "20260107", "original_docx", "course-20260107", "teacher_evidence"),
        (desktop / "20260108 选词刷题5_文稿.docx", "20260108", "original_docx", "course-20260108", "teacher_evidence"),
        (source_root / "20260107_选词刷题4_成语实词完整整理_清晰指代修订版.docx", "20260107", "reviewed_guide_docx", "course-20260107", "secondary_reference"),
        (source_root / "20260108 选词刷题5_词汇与老师解释（待核）.docx", "20260108", "reviewed_guide_docx", "course-20260108", "secondary_reference"),
        (source_root / "20260108_选词刷题5_成语实词完整整理.docx", "20260108", "reviewed_guide_docx", "course-20260108", "secondary_reference"),
        (source_root / "maimemo_20260108" / "registry.json", "20260108", "derived_registry_json", "course-20260108", "historical_only"),
        (source_root / "maimemo_four_poems" / "extracted_registry.json", "four-poems", "derived_registry_json", "course-four-poems", "historical_only"),
        (source_root / "maimemo_four_poems" / "audit_readonly" / "current_library_snapshot_2026-08-17.json", "live-snapshot", "api_snapshot_json", "live-library-20260817", "historical_only"),
    ]
    for lesson in ("第一讲", "第二讲", "第三讲"):
        stem = f"逻辑填空400词{lesson}-四诗风雅颂_文稿"
        group = f"course-four-poems-{lesson}"
        specs.extend(
            [
                (desktop / f"{stem}.docx", "four-poems", "original_docx", group, "teacher_evidence"),
                (source_root / "four_poems_transcripts" / f"{stem}.txt", "four-poems", "transcript_txt", group, "teacher_evidence"),
            ]
        )
    for path in sorted((source_root / "judgment_archive_v2").glob("judgments_*.json")):
        specs.append((path, "20260107", "judgment_archive_json", "course-20260107", "historical_only"))
    return specs


def build_catalog(source_root: Path) -> dict:
    sources = [
        build_source_entry(
            path,
            batch=batch,
            carrier_type=carrier_type,
            source_group_id=group,
            trust_role=role,
        )
        for path, batch, carrier_type, group, role in _source_specs(source_root)
    ]
    return {
        "schema_version": 1,
        "generated_from": str(source_root.resolve()),
        "sources": sources,
    }


def _load_records(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return list(payload.get("records", []))


def _catalog_indexes(catalog: dict) -> tuple[dict[str, str], dict[str, list[str]]]:
    by_name = {source["name"]: source["source_id"] for source in catalog["sources"]}
    by_group: dict[str, list[str]] = {}
    for source in catalog["sources"]:
        by_group.setdefault(source["source_group_id"], []).append(source["source_id"])
    return by_name, by_group


def build_provenance(source_root: Path, catalog: dict) -> dict:
    snapshot_path = source_root / "maimemo_four_poems" / "audit_readonly" / "current_library_snapshot_2026-08-17.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8-sig"))
    four_poems = _load_records(source_root / "maimemo_four_poems" / "extracted_registry.json")
    lesson_five = _load_records(source_root / "maimemo_20260108" / "registry.json")
    archive_records: dict[str, str] = {}
    for archive_path in sorted((source_root / "judgment_archive_v2").glob("judgments_*.json")):
        payload = json.loads(archive_path.read_text(encoding="utf-8-sig"))
        for record in payload.get("records", []):
            archive_records.setdefault(record["term"], archive_path.name)

    by_name, by_group = _catalog_indexes(catalog)
    snapshot_source = by_name[snapshot_path.name]
    four_poems_by_term = {record["term"]: record for record in four_poems}
    lesson_five_terms = {record["term"] for record in lesson_five}

    def base_provenance(term: str) -> dict:
        if term in four_poems_by_term:
            record = four_poems_by_term[term]
            if record.get("source_kind") == "user_directed_supplement":
                return {
                    "state": "user_supplement",
                    "source_ids": [],
                    "historical_source_ids": [by_name["extracted_registry.json"]],
                    "note": "课程逐字稿未找到讲解；保留为用户明确补充，后续需通用语义核定。",
                }
            teacher_ids = sorted(
                {
                    by_name[evidence["source"]]
                    for evidence in record.get("evidence", [])
                    if evidence.get("source") in by_name
                }
            )
            return {
                "state": "teacher_source_found",
                "source_ids": teacher_ids,
                "historical_source_ids": [by_name["extracted_registry.json"]],
                "note": "已有逐字稿段落与原话锚点；旧语义字段仍须重新审查。",
            }
        if term in lesson_five_terms:
            return {
                "state": "mixed_sources",
                "source_ids": by_group["course-20260108"],
                "historical_source_ids": [by_name["registry.json"]],
                "note": "存在原始课程文稿，但现有逐词定位来自派生讲义，须回到原稿复核。",
            }
        if term in archive_records:
            return {
                "state": "mixed_sources",
                "source_ids": by_group["course-20260107"],
                "historical_source_ids": [by_name[archive_records[term]]],
                "note": "存在原始课程文稿和旧判断档案；档案摘引不是独立老师证据，须回原稿复核。",
            }
        return {
            "state": "historical_only",
            "source_ids": [snapshot_source],
            "historical_source_ids": [snapshot_source],
            "note": "目前只能确认线上旧卡，尚未建立课程来源归属。",
        }

    cards: list[dict] = []
    base_by_term: dict[str, dict] = {}
    parsed_cards = [parse_card(card) for card in snapshot.get("cards", [])]
    for parsed in parsed_cards:
        if parsed.card_type != "base":
            continue
        details = base_provenance(parsed.term)
        entry = {
            "card_id": parsed.card_id,
            "root_id": parsed.root_id,
            "title": parsed.title,
            "card_type": "base",
            "terms": [parsed.term],
            **details,
        }
        cards.append(entry)
        base_by_term[parsed.term] = entry

    for parsed in parsed_cards:
        if parsed.card_type != "comparison":
            continue
        members = [base_by_term.get(term) for term in parsed.members]
        if any(member is None for member in members):
            state = "unresolved"
        else:
            states = {member["state"] for member in members if member is not None}
            if states == {"teacher_source_found"}:
                state = "teacher_source_found"
            elif states == {"user_supplement"}:
                state = "user_supplement"
            elif states == {"historical_only"}:
                state = "historical_only"
            elif "unresolved" in states:
                state = "unresolved"
            else:
                state = "mixed_sources"
        source_ids = sorted(
            {
                source_id
                for member in members
                if member is not None
                for source_id in member["source_ids"]
            }
        )
        historical_ids = sorted(
            {
                source_id
                for member in members
                if member is not None
                for source_id in member["historical_source_ids"]
            }
        )
        cards.append(
            {
                "card_id": parsed.card_id,
                "root_id": parsed.root_id,
                "title": parsed.title,
                "card_type": "comparison",
                "terms": list(parsed.members),
                "state": state,
                "source_ids": source_ids,
                "historical_source_ids": historical_ids,
                "note": "由成员基础卡来源状态汇总；组合本身的教学合理性将在辨析图谱阶段单独审查。",
            }
        )

    state_counts = Counter(card["state"] for card in cards)
    type_counts = Counter(card["card_type"] for card in cards)
    return {
        "schema_version": 1,
        "snapshot": str(snapshot_path.resolve()),
        "totals": {
            "cards": len(cards),
            "by_type": dict(sorted(type_counts.items())),
            "by_state": dict(sorted(state_counts.items())),
        },
        "cards": cards,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    catalog = build_catalog(args.source_root)
    provenance = build_provenance(args.source_root, catalog)
    catalog_errors = validate_source_catalog(catalog)
    expected_ids = {entry["card_id"] for entry in provenance["cards"]}
    provenance_errors = validate_card_provenance(
        provenance, expected_ids, catalog=catalog
    )
    errors = catalog_errors + provenance_errors
    if errors:
        for error in errors:
            print(error)
        return 1
    args.output_dir.mkdir(parents=True, exist_ok=True)
    catalog, provenance = portable_artifacts(catalog, provenance, args.output_dir)
    (args.output_dir / "source_catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "card_provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(provenance["totals"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
