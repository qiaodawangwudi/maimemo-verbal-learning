import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from maimemo_learning_rebuild.sources import (
    build_source_entry,
    load_source_catalog,
    validate_card_provenance,
    validate_evidence,
    validate_source_catalog,
)
from maimemo_learning_rebuild.build_source_artifacts import portable_artifacts


class SourceCatalogTests(unittest.TestCase):
    def test_public_artifacts_replace_machine_paths_with_relative_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact_dir = root / "repo" / "artifacts"
            source = root / "private" / "lesson.txt"
            snapshot = root / "private" / "snapshot.json"
            source.parent.mkdir(parents=True)
            artifact_dir.mkdir(parents=True)
            source.write_text("lesson", encoding="utf-8")
            snapshot.write_text("{}", encoding="utf-8")
            catalog = {
                "generated_from": str(root.resolve()),
                "sources": [{"path": str(source.resolve())}],
            }
            provenance = {"snapshot": str(snapshot.resolve())}

            public_catalog, public_provenance = portable_artifacts(
                catalog, provenance, artifact_dir
            )

            self.assertEqual("<LOCAL_SOURCE_ROOT>", public_catalog["generated_from"])
            self.assertFalse(Path(public_catalog["sources"][0]["path"]).is_absolute())
            self.assertFalse(Path(public_provenance["snapshot"]).is_absolute())
            self.assertNotIn(str(root.resolve()), json.dumps(public_catalog))
            self.assertNotIn(str(root.resolve()), json.dumps(public_provenance))

    def test_teacher_evidence_requires_exact_source_location_and_quote(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "lesson.txt"
            transcript.write_text("P0001\t老师原话\n", encoding="utf-8")
            catalog = {
                "sources": [
                    build_source_entry(
                        transcript,
                        batch="test",
                        carrier_type="transcript_txt",
                        source_group_id="course-1",
                        trust_role="teacher_evidence",
                    )
                ]
            }

            self.assertEqual(
                [],
                validate_evidence(
                    catalog,
                    {"source": "lesson.txt", "location": "P0001", "quote": "老师原话"},
                ),
            )
            self.assertIn(
                "evidence quote mismatch: lesson.txt P0001",
                validate_evidence(
                    catalog,
                    {"source": "lesson.txt", "location": "P0001", "quote": "错误原话"},
                ),
            )

    def test_teacher_docx_evidence_uses_nonempty_paragraph_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            docx = Path(directory) / "lesson.docx"
            document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p><w:r><w:t>第一段老师原话</w:t></w:r></w:p><w:p/><w:p><w:r><w:t>第二段原话</w:t></w:r></w:p>
</w:body></w:document>"""
            with zipfile.ZipFile(docx, "w") as archive:
                archive.writestr("word/document.xml", document_xml)
            catalog = {
                "sources": [
                    build_source_entry(
                        docx,
                        batch="test",
                        carrier_type="original_docx",
                        source_group_id="course-1",
                        trust_role="teacher_evidence",
                    )
                ]
            }

            self.assertEqual(
                [],
                validate_evidence(
                    catalog,
                    {"source": "lesson.docx", "location": "P0002", "quote": "第二段原话"},
                ),
            )

    def test_catalog_loader_resolves_relative_paths_from_catalog_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transcript = root / "lesson.txt"
            transcript.write_text("P0001\t老师原话\n", encoding="utf-8")
            catalog_path = root / "catalog.json"
            catalog_path.write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "source_id": "lesson",
                                "path": "lesson.txt",
                                "name": "lesson.txt",
                                "batch": "test",
                                "carrier_type": "transcript_txt",
                                "source_group_id": "course-1",
                                "trust_role": "teacher_evidence",
                                "sha256": build_source_entry(
                                    transcript,
                                    batch="test",
                                    carrier_type="transcript_txt",
                                    source_group_id="course-1",
                                    trust_role="teacher_evidence",
                                )["sha256"],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            loaded = load_source_catalog(catalog_path)

            self.assertEqual(str(transcript.resolve()), loaded["sources"][0]["path"])

    def test_catalog_rejects_missing_files_and_unknown_trust_roles(self):
        catalog = {
            "sources": [
                {
                    "source_id": "missing",
                    "path": "Z:/not-present.txt",
                    "name": "not-present.txt",
                    "batch": "test",
                    "carrier_type": "transcript_txt",
                    "source_group_id": "course-1",
                    "trust_role": "invented_role",
                    "sha256": "abc",
                }
            ]
        }

        errors = validate_source_catalog(catalog)

        self.assertIn("missing source file: Z:/not-present.txt", errors)
        self.assertIn("unknown trust role: invented_role", errors)

    def test_provenance_requires_exactly_one_entry_per_snapshot_card(self):
        provenance = {
            "cards": [
                {"card_id": "mkjc_1", "state": "teacher_source_found", "source_ids": ["s1"]},
                {"card_id": "mkjc_1", "state": "historical_only", "source_ids": []},
            ]
        }

        errors = validate_card_provenance(provenance, {"mkjc_1", "mkjc_2"})

        self.assertIn("duplicate provenance card_id: mkjc_1", errors)
        self.assertIn("missing provenance card_id: mkjc_2", errors)

    def test_user_supplement_cannot_claim_teacher_source(self):
        provenance = {
            "cards": [
                {
                    "card_id": "mkjc_1",
                    "state": "user_supplement",
                    "source_ids": ["teacher-1"],
                }
            ]
        }
        catalog = {
            "sources": [
                {
                    "source_id": "teacher-1",
                    "trust_role": "teacher_evidence",
                }
            ]
        }

        errors = validate_card_provenance(
            provenance, {"mkjc_1"}, catalog=catalog
        )

        self.assertIn(
            "user supplement claims teacher source: mkjc_1 teacher-1", errors
        )

    def test_provenance_rejects_unknown_historical_source(self):
        provenance = {
            "cards": [
                {
                    "card_id": "mkjc_1",
                    "state": "historical_only",
                    "source_ids": [],
                    "historical_source_ids": ["missing-history"],
                }
            ]
        }

        errors = validate_card_provenance(
            provenance, {"mkjc_1"}, catalog={"sources": []}
        )

        self.assertIn(
            "unknown provenance source: mkjc_1 missing-history", errors
        )

    def test_derivatives_of_one_course_can_share_a_source_group(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docx = root / "lesson.docx"
            transcript = root / "lesson.txt"
            docx.write_bytes(b"teacher carrier")
            transcript.write_text("P0001\t老师原话\n", encoding="utf-8")

            entries = [
                build_source_entry(
                    docx,
                    batch="lesson",
                    carrier_type="original_docx",
                    source_group_id="course-lesson",
                    trust_role="teacher_evidence",
                ),
                build_source_entry(
                    transcript,
                    batch="lesson",
                    carrier_type="transcript_txt",
                    source_group_id="course-lesson",
                    trust_role="teacher_evidence",
                ),
            ]

            self.assertEqual(
                {"course-lesson"}, {entry["source_group_id"] for entry in entries}
            )


if __name__ == "__main__":
    unittest.main()
