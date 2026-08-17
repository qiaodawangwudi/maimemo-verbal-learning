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
    def test_readback_resolves_expected_runtime_root_placeholder(self):
        group_content = "[P#H1#近义辨析｜甲、乙]\n---\n辨析"
        live_base = (
            "[P#H1#基础词义｜甲]\n---\n"
            "[Card#ID/mkjr_new_group#近义辨析｜甲、乙]"
        )
        expected_base = live_base.replace(
            "mkjr_new_group", "{{root:近义辨析｜甲、乙}}"
        )
        cards = [
            live_card("g1", "mkjr_new_group", "近义辨析｜甲、乙", group_content),
            live_card("b1", "mkjr_base", "基础词义｜甲", live_base),
        ]
        expected = [
            {"title": "近义辨析｜甲、乙", "content": group_content},
            {"title": "基础词义｜甲", "content": expected_base},
        ]
        plan = {
            "expected_after": 2,
            "actions": [
                {"title": "近义辨析｜甲、乙"},
                {"title": "基础词义｜甲"},
            ],
        }

        report = verify_readback(cards, expected, plan)

        self.assertTrue(report["ok"], report["errors"])

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
