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
        "coverage": {
            "sources": 2,
            "segments": 2,
            "candidates": 1,
            "reviewed_segments": 2,
        },
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

    def test_public_projection_ignores_nested_and_non_scalar_private_values(self):
        inventory = complete_inventory()
        inventory["coverage"]["private"] = {
            "local_path": "C:/SECRET/raw.txt",
            "raw_content": "DO_NOT_PUBLISH",
        }
        inventory["segments"][0]["approved_excerpt"] = {
            "text": "DO_NOT_PUBLISH_NESTED",
            "local_path": "/private/source.txt",
        }
        inventory["sources"][0]["sha256"] = {
            "value": "a" * 64,
            "raw_content": "DO_NOT_PUBLISH_HASH_CONTAINER",
        }

        errors = validate_source_inventory(inventory)
        serialized = json.dumps(
            public_inventory_view(inventory), ensure_ascii=False, sort_keys=True
        )

        self.assertIn("source field must be a string: s1: sha256", errors)
        self.assertIn(
            "segment field must be a bounded string: s1:p1: approved_excerpt",
            errors,
        )
        self.assertNotIn("private", serialized)
        self.assertNotIn("DO_NOT_PUBLISH", serialized)
        self.assertNotIn("C:/SECRET", serialized)
        self.assertNotIn("/private/source.txt", serialized)

    def test_public_repository_path_must_be_normalized_and_relative(self):
        invalid_paths = (
            "C:/SECRET/transcript.txt",
            "/private/transcript.txt",
            "../private/transcript.txt",
            "sources\\transcript.txt",
            "sources//transcript.txt",
        )
        for repository_path in invalid_paths:
            with self.subTest(repository_path=repository_path):
                inventory = complete_inventory()
                inventory["sources"][0]["repository_path"] = repository_path

                errors = validate_source_inventory(inventory)
                public_view = public_inventory_view(inventory)

                self.assertIn(
                    "public source repository path is not normalized relative: s1",
                    errors,
                )
                self.assertNotIn(
                    "repository_path", public_view["sources"][0]
                )

    def test_private_unknown_values_do_not_change_public_inventory_hash(self):
        inventory = complete_inventory()
        with_private_metadata = copy.deepcopy(inventory)
        with_private_metadata["coverage"]["private"] = {
            "local_path": "D:/machine/private.txt",
            "raw_content": "PRIVATE",
        }
        with_private_metadata["sources"][0]["unknown"] = {
            "raw_content": "PRIVATE_SOURCE"
        }
        with_private_metadata["segments"][0]["unknown"] = [
            {"local_path": "/private/segment"}
        ]

        self.assertEqual(
            source_inventory_hash(inventory),
            source_inventory_hash(with_private_metadata),
        )

    def test_requires_explicit_inventory_sections_and_coverage(self):
        errors = validate_source_inventory({})

        self.assertIn("missing inventory section: sources", errors)
        self.assertIn("missing inventory section: segments", errors)
        self.assertIn("missing inventory section: candidates", errors)
        self.assertIn("missing inventory section: frozen_cards", errors)
        self.assertIn("missing inventory section: coverage", errors)

    def test_coverage_counters_are_complete_nonnegative_and_match_records(self):
        inventory = complete_inventory()
        inventory["coverage"] = {
            "sources": 1,
            "segments": 1,
            "candidates": -1,
            "reviewed_segments": "2",
        }

        errors = validate_source_inventory(inventory)

        self.assertIn("coverage count mismatch: sources: expected 2, got 1", errors)
        self.assertIn("coverage count mismatch: segments: expected 2, got 1", errors)
        self.assertIn(
            "coverage counter must be a nonnegative integer: candidates", errors
        )
        self.assertIn(
            "coverage counter must be a nonnegative integer: reviewed_segments",
            errors,
        )

        inventory["coverage"].pop("segments")
        self.assertIn(
            "missing coverage counter: segments",
            validate_source_inventory(inventory),
        )

    def test_omitted_records_are_detected_by_coverage_cross_check(self):
        inventory = complete_inventory()
        inventory["segments"].pop()

        errors = validate_source_inventory(inventory)

        self.assertIn("coverage count mismatch: segments: expected 1, got 2", errors)
        self.assertIn(
            "coverage count mismatch: reviewed_segments: expected 1, got 2",
            errors,
        )

    def test_explicit_empty_inventory_is_valid(self):
        inventory = {
            "sources": [],
            "segments": [],
            "candidates": [],
            "frozen_cards": [],
            "coverage": {
                "sources": 0,
                "segments": 0,
                "candidates": 0,
                "reviewed_segments": 0,
            },
        }

        self.assertEqual([], validate_source_inventory(inventory))

    def test_excluded_segment_requires_stable_segment_or_source_location(self):
        invalid_segments = (
            {"status": "excluded_with_reason", "reason": "duplicate"},
            {
                "source_id": "s1",
                "status": "excluded_with_reason",
                "reason": "duplicate",
            },
            {
                "location": "p1",
                "status": "excluded_with_reason",
                "reason": "duplicate",
            },
        )
        for segment in invalid_segments:
            with self.subTest(segment=segment):
                inventory = complete_inventory()
                inventory["segments"][0] = segment

                self.assertIn(
                    "excluded segment lacks source location",
                    validate_source_inventory(inventory),
                )

    def test_malformed_json_types_return_errors_instead_of_exceptions(self):
        self.assertEqual(
            ["inventory must be an object"], validate_source_inventory([])
        )

        malformed_section = complete_inventory()
        malformed_section["sources"] = {"not": "a list"}
        malformed_section["coverage"] = []
        section_errors = validate_source_inventory(malformed_section)
        self.assertIn("inventory section must be a list: sources", section_errors)
        self.assertIn(
            "inventory section must be an object: coverage", section_errors
        )

        malformed_entries = complete_inventory()
        malformed_entries["sources"] = [
            {"source_id": "bad", "privacy": {"scope": "public_ok"}},
            "not-an-object",
        ]
        malformed_entries["segments"] = [
            {"source_id": "s1", "location": "p1", "status": []},
            "not-an-object",
        ]
        malformed_entries["candidates"] = [
            {"term": "坏值", "decision": {"state": "include"}},
            "not-an-object",
        ]
        malformed_entries["frozen_cards"] = [
            {"card_id": "bad-card", "privacy": []},
            "not-an-object",
        ]
        malformed_entries["coverage"] = {
            "sources": 2,
            "segments": 2,
            "candidates": 2,
            "reviewed_segments": 0,
        }

        entry_errors = validate_source_inventory(malformed_entries)

        self.assertIn(
            'invalid source privacy: bad: {"scope":"public_ok"}', entry_errors
        )
        self.assertIn("source entry must be an object", entry_errors)
        self.assertIn("segment entry must be an object", entry_errors)
        self.assertIn("candidate entry must be an object", entry_errors)
        self.assertIn("frozen card entry must be an object", entry_errors)

    def test_validation_error_order_is_independent_of_record_order(self):
        inventory = complete_inventory()
        inventory["sources"] = [
            {"source_id": "z-source", "privacy": "invalid-z"},
            {"source_id": "a-source", "privacy": "invalid-a"},
            "not-an-object",
        ]
        reversed_inventory = copy.deepcopy(inventory)
        reversed_inventory["sources"].reverse()

        errors = validate_source_inventory(inventory)

        self.assertEqual(sorted(errors), errors)
        self.assertEqual(errors, validate_source_inventory(reversed_inventory))

    def test_container_values_in_public_scalar_fields_are_validation_errors(self):
        inventory = complete_inventory()
        inventory["segments"][0]["location"] = {"page": "p1"}
        inventory["candidates"][0]["source_location"] = ["s1:p1"]
        inventory["frozen_cards"][0]["card_id"] = {"value": "card-1"}

        errors = validate_source_inventory(inventory)

        self.assertIn(
            "segment field must be a bounded string: s1:: location", errors
        )
        self.assertIn(
            "candidate field must be a bounded string: 因噎废食: source_location",
            errors,
        )
        self.assertIn(
            "frozen card field must be a string: <unknown>: card_id", errors
        )

    def test_public_identifiers_and_hashes_reject_absolute_path_strings(self):
        inventory = complete_inventory()
        inventory["sources"][0]["sha256"] = "C:/SECRET/hash.txt"
        inventory["segments"][0]["location"] = "/private/segment.txt"
        inventory["candidates"][0]["source_location"] = (
            "D:/SECRET/candidate.txt"
        )
        inventory["frozen_cards"][0]["card_id"] = "/private/card.txt"

        errors = validate_source_inventory(inventory)
        serialized = json.dumps(
            public_inventory_view(inventory), ensure_ascii=False, sort_keys=True
        )

        self.assertIn("source hash is not sha256: s1: sha256", errors)
        self.assertIn(
            "segment field is not a public identifier: s1:: location", errors
        )
        self.assertIn(
            "candidate field is not a public identifier: 因噎废食: source_location",
            errors,
        )
        self.assertIn(
            "frozen card field is not a public identifier: <unknown>: card_id",
            errors,
        )
        self.assertNotIn("C:/SECRET", serialized)
        self.assertNotIn("D:/SECRET", serialized)
        self.assertNotIn("/private", serialized)


if __name__ == "__main__":
    unittest.main()
