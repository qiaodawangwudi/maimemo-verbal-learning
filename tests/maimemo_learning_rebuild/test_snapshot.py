import json
import unittest
from pathlib import Path

from maimemo_learning_rebuild.snapshot import audit_snapshot, load_snapshot


def card(card_id, root_id, title, references=(), grammar_version=3):
    links = "\n".join(
        f"[Card#ID/{reference}#查看辨析]" for reference in references
    )
    return {
        "id": card_id,
        "root_id": root_id,
        "grammar_version": grammar_version,
        "content": f"[P#H1#{title}]\n\n问题\n\n---\n\n答案\n{links}",
    }


class SnapshotAuditTests(unittest.TestCase):
    def test_audits_counts_references_and_duplicate_titles(self):
        snapshot = {
            "cards": [
                card(
                    "mkjc_1",
                    "mkjr_1",
                    "基础词义｜因噎废食",
                    references=("mkjr_2",),
                ),
                card(
                    "mkjc_2",
                    "mkjr_2",
                    "近义辨析｜因噎废食、投鼠忌器",
                ),
            ]
        }

        result = audit_snapshot(snapshot)

        self.assertEqual(2, result["total"])
        self.assertEqual(1, result["base"])
        self.assertEqual(1, result["comparison"])
        self.assertEqual([], result["duplicate_titles"])
        self.assertEqual([], result["missing_reference_targets"])

    def test_reports_duplicate_titles_and_missing_reference_targets(self):
        snapshot = {
            "cards": [
                card("mkjc_1", "mkjr_1", "基础词义｜因噎废食", ("mkjr_missing",)),
                card("mkjc_2", "mkjr_2", "基础词义｜因噎废食"),
            ]
        }

        result = audit_snapshot(snapshot)

        self.assertEqual(["基础词义｜因噎废食"], result["duplicate_titles"])
        self.assertEqual(
            [
                {
                    "title": "基础词义｜因噎废食",
                    "reference": "mkjr_missing",
                }
            ],
            result["missing_reference_targets"],
        )

    def test_real_frozen_snapshot_matches_verified_baseline(self):
        project_root = Path(__file__).resolve().parents[4]
        path = project_root / "maimemo_four_poems" / "audit_readonly" / "current_library_snapshot_2026-08-17.json"
        self.assertTrue(path.exists(), path)

        result = audit_snapshot(load_snapshot(path))

        self.assertEqual(730, result["total"])
        self.assertEqual(605, result["base"])
        self.assertEqual(125, result["comparison"])
        self.assertEqual(0, result["other"])
        self.assertEqual([], result["duplicate_titles"])
        self.assertEqual([], result["missing_root_ids"])
        self.assertEqual([], result["bad_grammar_versions"])


if __name__ == "__main__":
    unittest.main()
