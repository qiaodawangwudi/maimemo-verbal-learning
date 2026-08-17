import unittest

from maimemo_learning_rebuild.markji import parse_card


class MarkjiParserTests(unittest.TestCase):
    def test_parses_layered_base_card_and_root_reference(self):
        card = {
            "id": "mkjc_base",
            "root_id": "mkjr_base",
            "grammar_version": 3,
            "content": (
                "[P#H1#基础词义｜因噎废食]\n\n问题\n\n---\n\n"
                "[T#B#词义：]因害怕问题而停做。\n\n"
                "[Card#ID/mkjr_compare#查看完整辨析：因噎废食、投鼠忌器]"
            ),
        }

        parsed = parse_card(card)

        self.assertEqual("基础词义｜因噎废食", parsed.title)
        self.assertEqual("base", parsed.card_type)
        self.assertEqual("因噎废食", parsed.term)
        self.assertEqual((), parsed.members)
        self.assertEqual(("mkjr_compare",), parsed.references)

    def test_parses_comparison_members_in_title_order(self):
        card = {
            "id": "mkjc_group",
            "root_id": "mkjr_group",
            "grammar_version": 3,
            "content": "[P#H1#近义辨析｜因噎废食、投鼠忌器]\n\n问题\n\n---\n\n答案",
        }

        parsed = parse_card(card)

        self.assertEqual("comparison", parsed.card_type)
        self.assertEqual(("因噎废食", "投鼠忌器"), parsed.members)
        self.assertEqual(frozenset({"因噎废食", "投鼠忌器"}), parsed.member_set)

    def test_rejects_malformed_heading(self):
        card = {
            "id": "mkjc_bad",
            "root_id": "mkjr_bad",
            "grammar_version": 3,
            "content": "没有标题\n\n---\n\n答案",
        }

        with self.assertRaisesRegex(ValueError, "missing Markji H1 title"):
            parse_card(card)

    def test_rejects_record_id_as_card_reference(self):
        card = {
            "id": "mkjc_bad_ref",
            "root_id": "mkjr_bad_ref",
            "grammar_version": 3,
            "content": (
                "[P#H1#基础词义｜因噎废食]\n\n问题\n\n---\n\n"
                "[Card#ID/mkjc_wrong#错误引用]"
            ),
        }

        with self.assertRaisesRegex(ValueError, "non-root card reference"):
            parse_card(card)


if __name__ == "__main__":
    unittest.main()
