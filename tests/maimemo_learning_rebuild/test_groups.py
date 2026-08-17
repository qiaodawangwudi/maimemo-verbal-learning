import json
import unittest
from pathlib import Path

from maimemo_learning_rebuild.groups import (
    audit_group_overlaps,
    validate_group_registry,
    validate_group_semantics,
)


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
    def test_real_registry_promotes_only_evidence_complete_groups(self):
        root = Path(__file__).parents[2]
        payload = json.loads(
            (
                root
                / "maimemo_learning_rebuild"
                / "artifacts"
                / "group_registry.json"
            ).read_text(encoding="utf-8")
        )

        self.assertEqual({"pending": 115, "ready": 10}, payload["totals"]["statuses"])
        by_title = {group["current_title"]: group for group in payload["groups"]}
        ready = by_title["近义辨析｜时不我待、迫在眉睫、刻不容缓"]
        self.assertEqual("ready", ready["status"])
        self.assertGreaterEqual(len(ready["minimum_differences"]), 2)
        self.assertTrue(ready["dimensions"])
        self.assertEqual(
            "pending",
            by_title["近义辨析｜包罗万象、应有尽有、一应俱全"]["status"],
        )
        self.assertEqual(
            "ready",
            by_title["近义辨析｜瞻前顾后、优柔寡断、举棋不定"]["status"],
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

    def test_group_requires_stable_order_and_reciprocal_edges(self):
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
        self.assertIn("missing reciprocal edge: 甲 -> 乙", errors)

    def test_mega_group_rejects_unconnected_members(self):
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

        self.assertIn("mega group has unconnected member: 词0", errors)

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
