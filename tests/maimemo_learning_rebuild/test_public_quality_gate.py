import unittest

from maimemo_learning_rebuild.public_quality_gate import evaluate_public_gate


class PublicQualityGateTests(unittest.TestCase):
    def test_rejects_incomplete_semantics_groups_plan_and_cards(self):
        errors = evaluate_public_gate(
            {"records": [{"status": "pending"}]},
            {"groups": [{"status": "pending", "audit": {"missing_base_terms": ["甲"]}}]},
            {"expected_after": 2, "actions": [{"action": "manual-review"}]},
            {"complete": False, "cards": []},
        )

        self.assertEqual(6, len(errors))

    def test_accepts_only_complete_release_artifacts(self):
        errors = evaluate_public_gate(
            {"records": [{"status": "ready"}]},
            {"groups": [{"status": "ready", "audit": {"missing_base_terms": []}}]},
            {"expected_after": 2, "actions": [{"action": "update"}]},
            {"complete": True, "cards": [{}, {}]},
        )

        self.assertEqual([], errors)

    def test_missing_current_base_is_resolved_by_frozen_create_action(self):
        errors = evaluate_public_gate(
            {"records": [{"status": "ready"}]},
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
            },
            {"complete": True, "cards": [{}, {}]},
        )

        self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
