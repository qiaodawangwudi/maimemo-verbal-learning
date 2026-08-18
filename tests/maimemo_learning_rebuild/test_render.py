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
            "uniqueness_rationale": "停止本应继续的改革是决定性线索，只有因噎废食符合。",
            "construction": {
                "mode": "authored",
                "semantic_basis": ["因噎废食::课程义::001"],
                "source_basis": [],
                "construction_note": "依据核定词义与辨析边界自主创作。",
            },
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
        self.assertIn("【答案唯一性】", back)
        self.assertIn("【题目性质】]自主创作", back)

    def test_frozen_examples_cover_the_three_approved_groups(self):
        path = (
            Path(__file__).parents[2]
            / "maimemo_learning_rebuild"
            / "examples"
            / "approved_learning_examples.json"
        )
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(1, len(payload["groups"]))
        self.assertEqual(
            [["甲词", "乙词"]],
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
            self.assertIn("【核心辨析】", rendered)

    def test_base_card_puts_keyword_core_first_and_omits_group_repetition(self):
        record = {
            "term": "因噎废食",
            "meaning": "因出过问题或怕出问题，索性停止本应继续的行动。",
            "distinctive_feature": "风险恐惧触发，结果是把必要行动整体停掉。",
            "core_discrimination": "担心问题发生 + 停止必要行动",
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
        ordered_labels = ["【核心辨析】", "【词义】", "【题干关键词】", "【易错边界】"]
        positions = [rendered.index(label) for label in ordered_labels]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("【核心辨析】]担心问题发生 + 停止必要行动", rendered)
        self.assertNotIn("特别之处", rendered)
        self.assertNotIn("一眼辨析", rendered)
        self.assertNotIn("因噎废食 × 投鼠忌器", rendered)
        self.assertNotIn("【多维判断】", rendered)
        self.assertNotIn(record["comparison_edges"][0]["minimum_difference"], rendered)
        self.assertIn("【易错边界】", rendered)
        self.assertIn("【典型语境】", rendered)
        self.assertNotEqual(record["meaning"], record["distinctive_feature"])
        self.assertNotIn("需结合题干逻辑对应点使用", rendered)
        self.assertTrue(rendered.rstrip().endswith("[Card#ID/mkjr_group#近义辨析｜因噎废食、投鼠忌器]"))

    def test_comparison_card_explains_each_member_once_without_pairwise_echoes(self):
        records = [
            {
                "term": "根深蒂固",
                "meaning": "思想、观念或现象根基牢固，难以动摇。",
                "distinctive_feature": "突出已经形成的稳固状态，不必强调负面累积过程。",
                "core_discrimination": "根基牢固 + 难以动摇",
            },
            {
                "term": "积重难返",
                "meaning": "问题或不良现象长期累积加重，已经难以改变。",
                "distinctive_feature": "同时要求长期累积、负面对象和难以扭转。",
                "core_discrimination": "负面问题长期累积 + 难以扭转",
            },
            {
                "term": "冰冻三尺",
                "meaning": "严重局面不是短期造成，而是长期因素逐渐积累形成。",
                "distinctive_feature": "强调当前局面的长期成因，不必表达已经无法改变。",
                "core_discrimination": "严重局面 + 长期积累形成",
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
            "selection_rules": [
                {"term": "根深蒂固", "text": "强调根基牢固、状态难改"},
                {"term": "积重难返", "text": "强调负面问题久积且难以扭转"},
                {"term": "冰冻三尺", "text": "强调严重局面由长期因素造成"},
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
            self.assertIn(f"【{record['term']}】]{record['core_discrimination']}", rendered)
            self.assertEqual(1, rendered.count(record["core_discrimination"]))
        for edge in group["minimum_differences"]:
            self.assertNotIn(edge["text"], rendered)
        self.assertIn("【核心辨析】", rendered)
        self.assertIn("【怎么选】", rendered)
        self.assertNotIn("特别之处", rendered)
        self.assertNotIn("【最小差别】", rendered)
        self.assertNotIn("【多维判断】", rendered)

    def test_base_card_uses_approved_keyword_formulas(self):
        cases = {
            "近水楼台": "接近某人/某事 + 优先获得利益或机会",
            "投鼠忌器": "顾虑伤及关联对象 + 不敢行动或放弃行动",
        }
        for term, core in cases.items():
            with self.subTest(term=term):
                rendered = render_base_card(
                    {
                        "term": term,
                        "meaning": "用于测试的准确完整词义。",
                        "distinctive_feature": "旧兼容字段不得显示。",
                        "core_discrimination": core,
                        "recognition_cues": [],
                        "comparison_edges": [],
                        "dimensions": [],
                        "misuse_boundary": "",
                        "typical_contexts": [],
                    },
                    [],
                )
                self.assertIn(f"【核心辨析】]{core}", rendered)
                self.assertLess(rendered.index("【核心辨析】"), rendered.index("【词义】"))

    def test_meaning_is_omitted_when_it_only_repeats_the_core(self):
        rendered = render_base_card(
            {
                "term": "改进",
                "meaning": "针对缺点作改善，范围最宽。",
                "distinctive_feature": "兼容字段。",
                "core_discrimination": "针对缺点作改善 + 范围最宽",
                "recognition_cues": [],
                "comparison_edges": [],
                "dimensions": [],
                "misuse_boundary": "",
                "typical_contexts": [],
            },
            [],
        )

        self.assertEqual(1, rendered.count("针对缺点作改善"))
        self.assertNotIn("【词义】", rendered)

    def test_reviewed_selection_condition_is_shown_once_without_full_edge_echo(self):
        records = [
            {"term": "甲", "meaning": "甲的完整词义。", "distinctive_feature": "甲落点。"},
            {"term": "乙", "meaning": "乙的完整词义。", "distinctive_feature": "乙落点。"},
        ]
        condition = "题干强调行动停止选甲；强调顾虑对象选乙"
        full_edge = "甲看行动停止；乙看顾虑对象；" + condition
        group = {
            "members": ["甲", "乙"],
            "minimum_differences": [
                {
                    "left": "甲",
                    "right": "乙",
                    "text": full_edge,
                    "question_selection_condition": condition,
                }
            ],
        }

        rendered = render_comparison_card(group, records)

        self.assertEqual(1, rendered.count(condition))
        self.assertNotIn(full_edge, rendered)


if __name__ == "__main__":
    unittest.main()
