import json
import unittest
from pathlib import Path

from maimemo_learning_rebuild.groups import (
    audit_group_overlaps,
    validate_group_registry,
    validate_group_semantics,
)
from maimemo_learning_rebuild.build_group_registry import synthesize_group_review


def record(term, order, edges):
    return {
        "term": term,
        "registry_order": order,
        "meaning": f"{term}的准确词义",
        "distinctive_feature": f"{term}的独特落点",
        "comparison_edges": [
            {"other_term": other, "minimum_difference": f"{term}与{other}的最小差别"}
            for other in edges
        ],
    }


class GroupGraphTests(unittest.TestCase):
    def test_synthesis_connects_every_member_with_useful_minimum_differences(self):
        records = {
            "甲": {
                **record("甲", 1, ["乙"]),
                "status": "ready",
                "distinctive_feature": "甲落在原因。",
                "dimensions": [{"axis": "落点", "judgment": "原因"}],
                "misuse_boundary": "没有原因时不用。",
            },
            "乙": {
                **record("乙", 2, ["甲"]),
                "status": "ready",
                "distinctive_feature": "乙落在过程。",
                "dimensions": [{"axis": "落点", "judgment": "过程"}],
                "misuse_boundary": "没有过程时不用。",
            },
            "丙": {
                **record("丙", 3, []),
                "status": "ready",
                "distinctive_feature": "丙落在结果。",
                "dimensions": [{"axis": "落点", "judgment": "结果"}],
                "misuse_boundary": "没有结果时不用。",
            },
        }
        records["甲"]["comparison_edges"][0]["minimum_difference"] = "甲看原因；乙看过程。"
        records["乙"]["comparison_edges"][0]["minimum_difference"] = "甲看原因；乙看过程。"
        group = {
            "group_id": "g",
            "current_title": "近义辨析｜甲、乙、丙",
            "status": "pending",
            "purpose": "待审",
            "members": ["甲", "乙", "丙"],
            "decision": "keep",
            "overlap_reasons": {},
            "audit": {"current_pairs": [["乙", "丙"]], "missing_base_terms": []},
        }

        result = synthesize_group_review(group, records)

        self.assertEqual("pending", result["status"])
        self.assertEqual(
            "independent comparison edge review required", result["pending_reason"]
        )
        self.assertEqual(
            [("甲", "乙"), ("乙", "丙")],
            [(item["left"], item["right"]) for item in result["minimum_differences"]],
        )
        self.assertEqual("甲看原因；乙看过程。", result["minimum_differences"][0]["text"])
        self.assertIn("乙落在过程", result["minimum_differences"][1]["text"])
        self.assertIn("丙落在结果", result["minimum_differences"][1]["text"])
        self.assertEqual([], validate_group_semantics(result, records))

    def test_ready_group_rejects_disconnected_minimum_difference_graph(self):
        records = {
            "甲": record("甲", 1, []),
            "乙": record("乙", 2, []),
            "丙": record("丙", 3, []),
        }
        group = {
            "group_id": "g",
            "status": "ready",
            "purpose": "区分三个词",
            "members": ["甲", "乙", "丙"],
            "decision": "keep",
            "minimum_differences": [{"left": "甲", "right": "乙", "text": "甲乙不同。"}],
        }

        self.assertIn(
            "disconnected minimum-difference graph: g 丙",
            validate_group_semantics(group, records),
        )

    def test_real_registry_contains_125_connected_reviewed_groups(self):
        root = Path(__file__).parents[2]
        payload = json.loads(
            (
                root
                / "maimemo_learning_rebuild"
                / "artifacts"
                / "group_registry.json"
            ).read_text(encoding="utf-8")
        )

        self.assertEqual({"ready": 125}, payload["totals"]["statuses"])
        by_title = {group["current_title"]: group for group in payload["groups"]}
        ready = by_title["近义辨析｜时不我待、迫在眉睫、刻不容缓"]
        self.assertEqual("ready", ready["status"])
        self.assertGreaterEqual(len(ready["minimum_differences"]), 2)
        self.assertTrue(ready["dimensions"])
        rebuilt = by_title["近义辨析｜包罗万象、应有尽有、一应俱全"]
        self.assertEqual("ready", rebuilt["status"])
        self.assertGreaterEqual(len(rebuilt["minimum_differences"]), 2)
        self.assertEqual(
            "ready",
            by_title["近义辨析｜瞻前顾后、优柔寡断、举棋不定"]["status"],
        )
        self.assertTrue(
            all(
                item.get("source_card_id", "").startswith("mkjc_public_")
                and item.get("root_id", "").startswith("mkjr_public_")
                for item in payload["groups"]
            )
        )

    def test_overlap_audit_distinguishes_exact_subset_and_partial(self):
        groups = [
            {"group_id": "a", "members": ["甲", "乙"]},
            {"group_id": "b", "members": ["乙", "甲"]},
            {"group_id": "c", "members": ["甲", "乙", "丙"]},
            {"group_id": "d", "members": ["乙", "丙", "丁"]},
        ]

        overlaps = audit_group_overlaps(groups)
        overlap_types = {
            (item["left_group_id"], item["right_group_id"]): item["type"]
            for item in overlaps
        }

        self.assertEqual("exact", overlap_types[("a", "b")])
        self.assertEqual("subset", overlap_types[("a", "c")])
        self.assertEqual("partial", overlap_types[("c", "d")])

    def test_retained_overlap_requires_pair_specific_reason(self):
        records = {
            "甲": record("甲", 1, ["乙"]),
            "乙": record("乙", 2, ["甲", "丙"]),
            "丙": record("丙", 3, ["乙"]),
        }
        groups = [
            {
                "group_id": "g1",
                "status": "ready",
                "purpose": "甲乙辨析",
                "members": ["甲", "乙"],
                "decision": "keep",
                "overlap_reasons": {},
            },
            {
                "group_id": "g2",
                "status": "ready",
                "purpose": "乙丙辨析",
                "members": ["乙", "丙"],
                "decision": "keep",
                "overlap_reasons": {},
            },
        ]

        errors = validate_group_registry(groups, records)

        self.assertIn("unexplained overlap: g1 g2", errors)
        groups[0]["overlap_reasons"]["g2"] = "乙分别连接两个不同判断轴。"
        self.assertNotIn("unexplained overlap: g1 g2", validate_group_registry(groups, records))

    def test_group_requires_stable_order_and_connected_comparison_view(self):
        records = {
            "甲": record("甲", 1, ["乙"]),
            "乙": record("乙", 2, []),
        }
        group = {
            "group_id": "g",
            "status": "ready",
            "purpose": "测试",
            "members": ["乙", "甲"],
            "decision": "keep",
        }

        errors = validate_group_semantics(group, records)

        self.assertIn("unstable member order: g", errors)
        self.assertIn("disconnected minimum-difference graph: g 甲", errors)

    def test_mega_group_rejects_disconnected_comparison_view(self):
        terms = [f"词{i}" for i in range(7)]
        records = {
            term: record(term, index, [terms[index + 1]] if index < 6 else [])
            for index, term in enumerate(terms)
        }
        group = {
            "group_id": "mega",
            "status": "ready",
            "purpose": "大组测试",
            "members": terms,
            "decision": "keep",
        }

        errors = validate_group_semantics(group, records)

        self.assertIn(
            "disconnected minimum-difference graph: mega 词1、词2、词3、词4、词5、词6",
            errors,
        )

    def test_ready_group_rejects_more_than_six_members_even_when_connected(self):
        terms = [f"词{i}" for i in range(7)]
        records = {term: record(term, index, []) for index, term in enumerate(terms)}
        group = {
            "group_id": "mega",
            "status": "ready",
            "purpose": "过大的辨析组",
            "members": terms,
            "decision": "keep",
            "minimum_differences": [
                {"left": terms[index], "right": terms[index + 1], "text": "差别明确。"}
                for index in range(6)
            ],
        }

        self.assertIn("comparison group exceeds learning limit: mega 7", validate_group_semantics(group, records))

    def test_synthesis_repurposes_mega_group_to_strongest_six_member_cluster(self):
        terms = [f"词{i}" for i in range(8)]
        records = {}
        for index, term in enumerate(terms):
            neighbors = []
            if 1 <= index <= 6:
                if index > 1:
                    neighbors.append(terms[index - 1])
                if index < 6:
                    neighbors.append(terms[index + 1])
            records[term] = {
                **record(term, index, neighbors),
                "status": "ready",
                "dimensions": [],
                "misuse_boundary": f"{term}的边界。",
            }
        group = {
            "group_id": "mega",
            "current_title": "近义辨析｜" + "、".join(terms),
            "status": "pending",
            "purpose": "待拆",
            "members": terms,
            "decision": "split",
            "overlap_reasons": {},
            "audit": {"current_pairs": [], "missing_base_terms": []},
        }

        result = synthesize_group_review(group, records)

        self.assertEqual(terms[1:7], result["members"])
        self.assertEqual([terms[0], terms[7]], result["excluded_members"])
        self.assertEqual("repurpose", result["decision"])
        self.assertEqual("pending", result["status"])
        self.assertEqual([], validate_group_semantics(result, records))

    def test_pending_group_preserves_structural_decision_without_fake_semantics(self):
        records = {
            "甲": {"term": "甲", "registry_order": 1},
            "乙": {"term": "乙", "registry_order": 2},
        }
        group = {
            "group_id": "pending",
            "status": "pending",
            "purpose": "语义证据尚待恢复",
            "members": ["甲", "乙"],
            "decision": "repurpose",
        }

        self.assertEqual([], validate_group_semantics(group, records))


if __name__ == "__main__":
    unittest.main()
