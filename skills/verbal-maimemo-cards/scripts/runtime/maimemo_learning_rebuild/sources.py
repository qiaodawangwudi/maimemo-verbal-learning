"""Source catalog, evidence checks, and per-card provenance validation."""

from __future__ import annotations

import hashlib
import argparse
import copy
import json
import os
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree


TRUST_ROLES = {
    "teacher_evidence",
    "user_supplement",
    "secondary_reference",
    "historical_only",
}
PROVENANCE_STATES = {
    "teacher_source_found",
    "user_supplement",
    "historical_only",
    "mixed_sources",
    "unresolved",
}


def _relative_path(path: str | Path, artifact_dir: Path) -> str:
    return Path(os.path.relpath(Path(path).resolve(), artifact_dir.resolve())).as_posix()


def portable_artifacts(
    catalog: dict, provenance: dict, artifact_dir: Path
) -> tuple[dict, dict]:
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


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_source_entry(
    path: str | Path,
    *,
    batch: str,
    carrier_type: str,
    source_group_id: str,
    trust_role: str,
) -> dict:
    source_path = Path(path).resolve()
    return {
        "source_id": hashlib.sha256(str(source_path).encode("utf-8")).hexdigest()[:16],
        "path": str(source_path),
        "name": source_path.name,
        "batch": batch,
        "carrier_type": carrier_type,
        "source_group_id": source_group_id,
        "trust_role": trust_role,
        "sha256": file_sha256(source_path),
    }


def load_source_catalog(path: str | Path) -> dict:
    catalog_path = Path(path).resolve()
    catalog = json.loads(catalog_path.read_text(encoding="utf-8-sig"))
    for source in catalog.get("sources", []):
        source_path = Path(source["path"])
        if not source_path.is_absolute():
            source["path"] = str((catalog_path.parent / source_path).resolve())
    return catalog


def validate_source_catalog(catalog: dict) -> list[str]:
    errors: list[str] = []
    ids = [str(source.get("source_id") or "") for source in catalog.get("sources", [])]
    for source_id, count in Counter(ids).items():
        if source_id and count > 1:
            errors.append(f"duplicate source_id: {source_id}")
    for source in catalog.get("sources", []):
        path = str(source.get("path") or "")
        if not Path(path).exists():
            errors.append(f"missing source file: {path}")
        elif source.get("sha256") != file_sha256(path):
            errors.append(f"source hash mismatch: {path}")
        role = str(source.get("trust_role") or "")
        if role not in TRUST_ROLES:
            errors.append(f"unknown trust role: {role}")
        for field in ("source_id", "name", "batch", "carrier_type", "source_group_id"):
            if not str(source.get(field) or "").strip():
                errors.append(f"source missing {field}: {path}")
    return errors


def _transcript_locations(path: str | Path) -> dict[str, str]:
    locations: dict[str, str] = {}
    for raw_line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if "\t" not in raw_line:
            continue
        location, text = raw_line.split("\t", 1)
        locations[location] = text
    return locations


def _docx_locations(path: str | Path) -> dict[str, str]:
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:body/w:p", namespace):
        text = "".join(
            node.text or "" for node in paragraph.findall(".//w:t", namespace)
        ).strip()
        if text:
            paragraphs.append(text)
    return {f"P{index:04d}": text for index, text in enumerate(paragraphs, 1)}


def validate_evidence(catalog: dict, evidence: dict) -> list[str]:
    errors: list[str] = []
    source_name = str(evidence.get("source") or "")
    matches = [
        source
        for source in catalog.get("sources", [])
        if source.get("name") == source_name or source.get("source_id") == source_name
    ]
    if not matches:
        return [f"unknown evidence source: {source_name}"]
    source = matches[0]
    if source.get("trust_role") != "teacher_evidence":
        errors.append(f"source is not teacher evidence: {source_name}")
    location = str(evidence.get("location") or "")
    source_path = Path(source["path"])
    locations = (
        _docx_locations(source_path)
        if source_path.suffix.lower() == ".docx"
        else _transcript_locations(source_path)
    )
    if location not in locations:
        errors.append(f"unknown evidence location: {source_name} {location}")
    elif locations[location] != str(evidence.get("quote") or ""):
        errors.append(f"evidence quote mismatch: {source_name} {location}")
    return errors


def validate_card_provenance(
    provenance: dict,
    expected_card_ids: set[str],
    *,
    catalog: dict | None = None,
) -> list[str]:
    errors: list[str] = []
    entries = provenance.get("cards", [])
    ids = [str(entry.get("card_id") or "") for entry in entries]
    for card_id, count in Counter(ids).items():
        if card_id and count > 1:
            errors.append(f"duplicate provenance card_id: {card_id}")
    present = set(ids)
    for card_id in sorted(expected_card_ids - present):
        errors.append(f"missing provenance card_id: {card_id}")
    for card_id in sorted(present - expected_card_ids):
        errors.append(f"unknown provenance card_id: {card_id}")
    for entry in entries:
        state = str(entry.get("state") or "")
        if state not in PROVENANCE_STATES:
            errors.append(f"unknown provenance state: {state}")
        if catalog is not None:
            source_roles = {
                str(source.get("source_id")): str(source.get("trust_role"))
                for source in catalog.get("sources", [])
            }
            all_source_ids = list(entry.get("source_ids", [])) + list(
                entry.get("historical_source_ids", [])
            )
            for source_id in all_source_ids:
                if source_id not in source_roles:
                    errors.append(
                        f"unknown provenance source: {entry.get('card_id')} {source_id}"
                    )
                elif state == "user_supplement" and source_roles[source_id] == "teacher_evidence":
                    errors.append(
                        "user supplement claims teacher source: "
                        f"{entry.get('card_id')} {source_id}"
                    )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", nargs=2, metavar=("CATALOG", "PROVENANCE"))
    args = parser.parse_args()
    if not args.validate:
        parser.error("--validate is required")
    catalog_path, provenance_path = map(Path, args.validate)
    catalog = load_source_catalog(catalog_path)
    provenance = json.loads(provenance_path.read_text(encoding="utf-8-sig"))
    snapshot_path = Path(provenance["snapshot"])
    if not snapshot_path.is_absolute():
        snapshot_path = (provenance_path.resolve().parent / snapshot_path).resolve()
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8-sig"))
    expected_card_ids = {str(card.get("id") or "") for card in snapshot.get("cards", [])}
    errors = validate_source_catalog(catalog) + validate_card_provenance(
        provenance, expected_card_ids, catalog=catalog
    )
    if errors:
        for error in errors:
            print(error)
        return 1
    print(
        json.dumps(
            {
                "sources": len(catalog.get("sources", [])),
                "cards": len(provenance.get("cards", [])),
                "states": dict(
                    sorted(
                        Counter(
                            entry["state"] for entry in provenance.get("cards", [])
                        ).items()
                    )
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
