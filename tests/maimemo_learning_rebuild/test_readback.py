import unittest

from maimemo_learning_rebuild.readback import verify_readback


def live_card(card_id, root_id, title, content):
    return {
        "id": card_id,
        "root_id": root_id,
        "grammar_version": 3,
        "content": content,
    }


class ReadbackTests(unittest.TestCase):
    def test_complete_readback_matches_titles_content_versions_and_counts(self):
        cards = [
            live_card("c1", "r1", "基础词义｜甲", "[P#H1#基础词义｜甲]\n---\n新内容")
        ]
        expected = [
            {"title": "基础词义｜甲", "content": "[P#H1#基础词义｜甲]\n---\n新内容"}
        ]
        plan = {"expected_after": 1, "actions": [{"title": "基础词义｜甲"}]}

        report = verify_readback(cards, expected, plan)

        self.assertTrue(report["ok"], report["errors"])

    def test_readback_reports_unplanned_addition_content_and_reference_failures(self):
        cards = [
            live_card(
                "c1",
                "r1",
                "基础词义｜甲",
                "[P#H1#基础词义｜甲]\n[Card#ID/mkjr_missing#组]",
            ),
            live_card("c2", "r2", "基础词义｜多余", "[P#H1#基础词义｜多余]\n---\n内容"),
        ]
        expected = [{"title": "基础词义｜甲", "content": "[P#H1#基础词义｜甲]\n---\n应有内容"}]
        plan = {"expected_after": 1, "actions": [{"title": "基础词义｜甲"}]}

        report = verify_readback(cards, expected, plan)

        self.assertFalse(report["ok"])
        self.assertIn("live count mismatch: expected 1 got 2", report["errors"])
        self.assertIn("content mismatch: 基础词义｜甲", report["errors"])
        self.assertIn("unplanned live title: 基础词义｜多余", report["errors"])
        self.assertIn("missing root reference target: 基础词义｜甲 mkjr_missing", report["errors"])


if __name__ == "__main__":
    unittest.main()
