import json
import unittest
from pathlib import Path

from maimemo_learning_rebuild.models import validate_group_record, validate_semantic_record
from maimemo_learning_rebuild.render import (
    render_application_card,
    render_base_card,
    render_comparison_card,
)


class LayeredRenderTests(unittest.TestCase):
    def test_application_card_hides_analysis_until_after_context_and_options(self):
        application = {
            "title": "语境应用｜因噎废食、投鼠忌器｜风险触发",
            "prompt": "某地担心改革过程中出现问题，索性停止了已经启动且有必要继续的改革。填入哪个词最准确？",
            "options": ["因噎废食", "投鼠忌器"],
            "answer": "因噎废食",
            "clue_extraction": ["担心改革出问题", "停止本应继续的行动"],
            "fit_reasoning": "因噎废食要求因问题或风险担忧而整体放弃必要行动，与题干因果链完全一致。",
            "distractor_rejections": {
                "投鼠忌器": "投鼠忌器要求顾忌行动会牵连旁人旁物，题干不存在被牵连的关联对象。"
            },
            "transfer_rule": "先找行为结果；停止必要行动对应因噎废食，因顾忌关联对象而不敢行动对应投鼠忌器。",
        }

        rendered = render_application_card(application)
        front, back = rendered.split("\n---\n")

        self.assertIn(application["prompt"], front)
        self.assertIn("A. 因噎废食", front)
        self.assertIn("B. 投鼠忌器", front)
        self.assertNotIn("【答案】", front)
        self.assertIn("【答案】]因噎废食", back)
        self.assertIn("【题干线索】", back)
        self.assertIn("【为什么匹配】", back)
        self.assertIn("【排除投鼠忌器】", back)
        self.assertIn("【迁移规则】", back)

    def test_frozen_examples_cover_the_three_approved_groups(self):
        path = (
            Path(__file__).parents[2]
            / "maimemo_learning_rebuild"
            / "examples"
            / "approved_learning_examples.json"
        )
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(3, len(payload["groups"]))
        self.assertEqual(
            [
                ["因噎废食", "投鼠忌器"],
                ["走马观花", "浮光掠影"],
                ["根深蒂固", "积重难返", "冰冻三尺"],
            ],
            [group["members"] for group in payload["groups"]],
        )
        records = {record["term"]: record for record in payload["records"]}
        for record in records.values():
            self.assertEqual([], validate_semantic_record(record))
        for group in payload["groups"]:
            self.assertEqual([], validate_group_record(group, records))
            rendered = render_comparison_card(
                group, [records[term] for term in group["members"]]
            )
            self.assertEqual(1, rendered.count("\n---\n"))
            self.assertIn("【最小差别】", rendered)

    def test_base_card_orders_recall_before_deep_learning(self):
        record = {
            "term": "因噎废食",
            "meaning": "因出过问题或怕出问题，索性停止本应继续的行动。",
            "distinctive_feature": "风险恐惧触发，结果是把必要行动整体停掉。",
            "recognition_cues": ["先有问题或风险担忧", "后有停止必要行动"],
            "comparison_edges": [
                {
                    "other_term": "投鼠忌器",
                    "minimum_difference": "因噎废食怕出问题而停；投鼠忌器怕牵连旁人旁物而不敢动。",
                }
            ],
            "dimensions": [
                {"axis": "触发条件", "judgment": "已有问题，或担心问题发生。"},
                {"axis": "动作结果", "judgment": "本应继续的行动被整体停止。"},
            ],
            "misuse_boundary": "只有害怕或犹豫，却没有停止必要行动时，不足以使用。",
            "typical_contexts": ["不能因为个别事故就停止必要改革。"],
        }
        refs = [
            {
                "title": "近义辨析｜因噎废食、投鼠忌器",
                "root_id": "mkjr_group",
            }
        ]

        rendered = render_base_card(record, refs)

        self.assertEqual(1, rendered.count("\n---\n"))
        ordered_labels = ["【词义】", "【特别之处】", "【做题识别点】", "【一眼辨析】"]
        positions = [rendered.index(label) for label in ordered_labels]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("因噎废食 × 投鼠忌器", rendered)
        self.assertIn("【多维判断】", rendered)
        self.assertIn("【易错边界】", rendered)
        self.assertIn("【典型语境】", rendered)
        self.assertNotEqual(record["meaning"], record["distinctive_feature"])
        self.assertNotIn("需结合题干逻辑对应点使用", rendered)
        self.assertTrue(rendered.rstrip().endswith("[Card#ID/mkjr_group#近义辨析｜因噎废食、投鼠忌器]"))

    def test_comparison_card_exposes_member_features_and_useful_dimensions(self):
        records = [
            {
                "term": "根深蒂固",
                "meaning": "思想、观念或现象根基牢固，难以动摇。",
                "distinctive_feature": "突出已经形成的稳固状态，不必强调负面累积过程。",
            },
            {
                "term": "积重难返",
                "meaning": "问题或不良现象长期累积加重，已经难以改变。",
                "distinctive_feature": "同时要求长期累积、负面对象和难以扭转。",
            },
            {
                "term": "冰冻三尺",
                "meaning": "严重局面不是短期造成，而是长期因素逐渐积累形成。",
                "distinctive_feature": "强调当前局面的长期成因，不必表达已经无法改变。",
            },
        ]
        group = {
            "title": "近义辨析｜根深蒂固、积重难返、冰冻三尺",
            "members": ["根深蒂固", "积重难返", "冰冻三尺"],
            "minimum_differences": [
                {
                    "left": "根深蒂固",
                    "right": "积重难返",
                    "text": "根深蒂固看稳固状态；积重难返还要求负面问题长期累积且难以扭转。",
                },
                {
                    "left": "积重难返",
                    "right": "冰冻三尺",
                    "text": "积重难返落在难以改变；冰冻三尺落在局面并非一日形成。",
                },
            ],
            "dimensions": [
                {
                    "axis": "长期过程",
                    "judgments": {
                        "根深蒂固": "不要求明说",
                        "积重难返": "必须",
                        "冰冻三尺": "必须",
                    },
                },
                {
                    "axis": "落点",
                    "judgments": {
                        "根深蒂固": "稳固状态",
                        "积重难返": "难以扭转",
                        "冰冻三尺": "长期成因",
                    },
                },
                {
                    "axis": "对象方向",
                    "judgments": {
                        "根深蒂固": "可中性，依对象定褒贬",
                        "积重难返": "负面问题或现象",
                        "冰冻三尺": "多指负面局面",
                    },
                },
            ],
        }

        rendered = render_comparison_card(group, records)

        for record in records:
            self.assertIn(f"【{record['term']}｜词义】]{record['meaning']}", rendered)
            self.assertIn(f"【{record['term']}｜特别之处】]{record['distinctive_feature']}", rendered)
        for edge in group["minimum_differences"]:
            self.assertIn(edge["text"], rendered)
            self.assertNotIn(edge["text"], [record["meaning"] for record in records])
        self.assertIn("长期过程", rendered)
        self.assertIn("稳固状态", rendered)
        self.assertIn("难以扭转", rendered)
        self.assertIn("负面问题或现象", rendered)


if __name__ == "__main__":
    unittest.main()
