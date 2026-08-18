import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs" / "reviews" / "huasheng1000-preview-audit.json"


class Huasheng1000PreviewAuditTests(unittest.TestCase):
    def test_preview_audit_is_complete_private_and_read_only(self):
        data = json.loads(AUDIT.read_text(encoding="utf-8"))
        self.assertEqual(data["scope"], "preview_only_no_maimemo_write")
        self.assertEqual(data["source_inventory"]["target_terms"], 974)
        self.assertEqual(data["outputs"], {
            "basic_cards": 974,
            "comparison_cards": 104,
            "application_cards": 974,
        })
        self.assertEqual(data["quality"]["status"], "passed")
        self.assertEqual(data["quality"]["application_contract_errors"], 0)
        self.assertEqual(data["quality"]["answer_hidden_review_errors"], 0)
        self.assertFalse(data["library_reconciliation"]["full_live_library_completeness_proven"])
        self.assertEqual(
            data["library_reconciliation"]["write_gate"],
            "blocked_pending_full_live_snapshot",
        )
        self.assertFalse(data["privacy"]["raw_course_material_uploaded"])
        self.assertFalse(data["privacy"]["card_content_uploaded"])
        for digest in data["private_local_artifact_sha256"].values():
            self.assertRegex(digest, re.compile(r"^[0-9a-f]{64}$"))


if __name__ == "__main__":
    unittest.main()
