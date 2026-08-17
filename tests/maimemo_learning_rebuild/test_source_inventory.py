import copy
import json
import unittest

from maimemo_learning_rebuild.source_inventory import (
    public_inventory_view,
    source_inventory_hash,
    validate_source_inventory,
)


def complete_inventory():
    return {
        "sources": [
            {
                "source_id": "s1",
                "privacy": "public_ok",
                "sha256": "a" * 64,
                "repository_path": "sources/transcript.txt",
                "local_path": "C:/private/transcript.txt",
                "raw_content": "public source raw content",
            },
            {
                "source_id": "s2",
                "privacy": "local_only",
                "sha256": "b" * 64,
                "local_path": "C:/private/notes.txt",
                "raw_content": "private source raw content",
            },
        ],
        "segments": [
            {
                "source_id": "s1",
                "location": "p1",
                "status": "reviewed",
                "approved_excerpt": "可公开的短证据",
                "raw_content": "full segment content",
            },
            {
                "source_id": "s2",
                "location": "p2",
                "status": "no_vocabulary",
                "raw_content": "private segment content",
            },
        ],
        "candidates": [
            {
                "term": "因噎废食",
                "decision": "include",
                "source_location": "s1:p1",
            }
        ],
        "frozen_cards": [{"card_id": "card-1", "privacy": "public_ok"}],
        "coverage": {"sources": 2, "segments": 2, "reviewed_segments": 2},
    }


class SourceInventoryTests(unittest.TestCase):
    def test_accepts_complete_inventory(self):
        self.assertEqual([], validate_source_inventory(complete_inventory()))

    def test_rejects_unclassified_segment_and_candidate(self):
        inventory = complete_inventory()
        inventory["segments"][0]["status"] = "unclassified"
        inventory["candidates"][0].pop("decision")

        errors = validate_source_inventory(inventory)

        self.assertIn("unclassified source segment: s1:p1", errors)
        self.assertIn("candidate lacks decision: 因噎废食", errors)

    def test_local_only_source_cannot_have_public_repository_path(self):
        inventory = complete_inventory()
        inventory["sources"][0]["privacy"] = "local_only"
        inventory["sources"][0]["repository_path"] = "sources/transcript.txt"

        self.assertIn(
            "local-only source exposes repository path",
            validate_source_inventory(inventory),
        )

    def test_rejects_unknown_source_privacy_and_candidate_decision(self):
        inventory = complete_inventory()
        inventory["sources"][0]["privacy"] = "internal"
        inventory["candidates"][0]["decision"] = "pending"

        errors = validate_source_inventory(inventory)

        self.assertIn("invalid source privacy: s1: internal", errors)
        self.assertIn("invalid candidate decision: 因噎废食: pending", errors)

    def test_exclusions_and_corrections_require_reason_and_source_location(self):
        inventory = complete_inventory()
        inventory["segments"][0]["status"] = "excluded_with_reason"
        inventory["candidates"] = [
            {"term": "排除词", "decision": "exclude"},
            {"term": "纠错词", "decision": "asr_corrected"},
        ]

        errors = validate_source_inventory(inventory)

        self.assertIn("excluded segment lacks reason: s1:p1", errors)
        self.assertIn("candidate exclude lacks reason: 排除词", errors)
        self.assertIn("candidate exclude lacks source location: 排除词", errors)
        self.assertIn("candidate asr_corrected lacks reason: 纠错词", errors)
        self.assertIn(
            "candidate asr_corrected lacks source location: 纠错词", errors
        )

    def test_frozen_cards_must_be_explicitly_public_ok(self):
        inventory = complete_inventory()
        inventory["frozen_cards"] = [
            {"card_id": "missing-classification"},
            {"card_id": "private-card", "privacy": "local_only"},
        ]

        errors = validate_source_inventory(inventory)

        self.assertIn(
            "frozen derived card is not public_ok: missing-classification", errors
        )
        self.assertIn("frozen derived card is not public_ok: private-card", errors)

    def test_public_view_keeps_release_metadata_but_removes_private_content(self):
        inventory = complete_inventory()

        public_view = public_inventory_view(inventory)
        serialized = json.dumps(public_view, ensure_ascii=False)

        self.assertEqual("s1", public_view["sources"][0]["source_id"])
        self.assertEqual("a" * 64, public_view["sources"][0]["sha256"])
        self.assertEqual(
            "sources/transcript.txt", public_view["sources"][0]["repository_path"]
        )
        self.assertEqual(
            "可公开的短证据", public_view["segments"][0]["approved_excerpt"]
        )
        self.assertEqual(inventory["coverage"], public_view["coverage"])
        self.assertNotIn("local_path", serialized)
        self.assertNotIn("raw_content", serialized)
        self.assertNotIn("C:/private", serialized)
        self.assertNotIn("private source raw content", serialized)
        self.assertNotIn("private segment content", serialized)

    def test_inventory_hash_is_canonical_and_excludes_local_machine_paths(self):
        inventory = complete_inventory()
        reordered = {
            "coverage": copy.deepcopy(inventory["coverage"]),
            "frozen_cards": copy.deepcopy(inventory["frozen_cards"]),
            "candidates": copy.deepcopy(inventory["candidates"]),
            "segments": copy.deepcopy(inventory["segments"]),
            "sources": copy.deepcopy(inventory["sources"]),
        }
        reordered["sources"][0]["local_path"] = "D:/another-machine/transcript.txt"
        reordered["sources"][1]["local_path"] = "D:/another-machine/notes.txt"

        digest = source_inventory_hash(inventory)

        self.assertEqual(64, len(digest))
        self.assertEqual(digest, source_inventory_hash(reordered))
        reordered["segments"][0]["status"] = "no_vocabulary"
        self.assertNotEqual(digest, source_inventory_hash(reordered))


if __name__ == "__main__":
    unittest.main()
