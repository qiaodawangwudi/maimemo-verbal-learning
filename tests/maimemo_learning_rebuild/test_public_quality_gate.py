import unittest

from maimemo_learning_rebuild.public_quality_gate import evaluate_public_gate
from maimemo_learning_rebuild.reconciliation import build_library_reconciliation


class PublicQualityGateTests(unittest.TestCase):
    def test_missing_library_reconciliation_is_a_hard_error(self):
        errors = evaluate_public_gate(
            {"records": []},
            {"groups": []},
            {"expected_after": 0, "actions": []},
            {"complete": True, "cards": []},
        )

        self.assertIn("public gate library reconciliation is missing", errors)

    def test_rejects_plan_reconciliation_bound_to_another_semantic_registry(self):
        original = [{"term": "甲", "sense_id": "甲::义项::001", "status": "ready"}]
        changed = [{"term": "乙", "sense_id": "乙::义项::001", "status": "ready"}]
        reconciliation = build_library_reconciliation({"cards": []}, original)

        errors = evaluate_public_gate(
            {"records": changed},
            {"groups": []},
            {
                "expected_after": 0,
                "actions": [],
                "library_reconciliation": reconciliation,
            },
            {"complete": True, "cards": []},
        )

        self.assertIn("public gate semantic registry differs from reconciliation", errors)

    def test_rejects_incomplete_semantics_groups_plan_and_cards(self):
        errors = evaluate_public_gate(
            {"records": [{"status": "pending"}]},
            {"groups": [{"status": "pending", "audit": {"missing_base_terms": ["甲"]}}]},
            {"expected_after": 2, "actions": [{"action": "manual-review"}]},
            {"complete": False, "cards": []},
        )

        self.assertEqual(7, len(errors))

    def test_accepts_only_complete_release_artifacts(self):
        records = [{"term": "甲", "sense_id": "甲::义项::001", "status": "ready"}]
        reconciliation = build_library_reconciliation({"cards": []}, records)
        errors = evaluate_public_gate(
            {"records": records},
            {"groups": [{"status": "ready", "audit": {"missing_base_terms": []}}]},
            {
                "expected_after": 2,
                "actions": [{"action": "update"}],
                "library_reconciliation": reconciliation,
            },
            {"complete": True, "cards": [{}, {}]},
        )

        self.assertEqual([], errors)

    def test_missing_current_base_is_resolved_by_frozen_create_action(self):
        records = [{"term": "甲", "sense_id": "甲::义项::001", "status": "ready"}]
        reconciliation = build_library_reconciliation({"cards": []}, records)
        errors = evaluate_public_gate(
            {"records": records},
            {
                "groups": [
                    {
                        "status": "ready",
                        "audit": {"missing_base_terms": ["甲"]},
                    }
                ]
            },
            {
                "expected_after": 2,
                "actions": [{"title": "基础词义｜甲", "action": "create"}],
                "library_reconciliation": reconciliation,
            },
            {"complete": True, "cards": [{}, {}]},
        )

        self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
