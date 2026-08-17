import unittest
import json
from pathlib import Path

from maimemo_learning_rebuild.planning import build_action_plan, validate_action_plan


def snapshot_card(card_id, root_id, title, content=None):
    body = content or f"[P#H1#{title}]\n\n问题\n\n---\n\n旧内容"
    return {
        "id": card_id,
        "root_id": root_id,
        "grammar_version": 3,
        "content": body,
    }


def semantic(term, status="ready"):
    record = {
        "term": term,
        "sense_id": f"{term}::课程义::001",
        "status": status,
        "source_kind": "user_directed_supplement",
        "registry_order": 1,
    }
    if status == "ready":
        record.update(
            {
                "meaning": f"{term}的准确含义。",
                "distinctive_feature": f"{term}的独特落点。",
                "recognition_cues": ["识别线索"],
                "dimensions": [],
                "comparison_edges": [],
                "misuse_boundary": "缺少必要条件时不使用。",
                "evidence": [],
            }
        )
    return record


class PlanningTests(unittest.TestCase):
    def test_real_offline_plan_is_deterministic_and_count_safe(self):
        root = Path(__file__).parents[2]
        artifact_root = root / "maimemo_learning_rebuild" / "artifacts"
        source_root = root.parents[1]
        snapshot = json.loads(
            (
                source_root
                / "maimemo_four_poems"
                / "audit_readonly"
                / "current_library_snapshot_2026-08-17.json"
            ).read_text(encoding="utf-8-sig")
        )
        registry = json.loads(
            (artifact_root / "master_semantic_registry.json").read_text(encoding="utf-8")
        )["records"]
        groups = json.loads(
            (artifact_root / "group_registry.json").read_text(encoding="utf-8")
        )["groups"]

        first_plan, first_cards = build_action_plan(snapshot, registry, groups)
        second_plan, second_cards = build_action_plan(snapshot, registry, groups)

        self.assertEqual(first_plan["plan_hash"], second_plan["plan_hash"])
        self.assertEqual(first_cards, second_cards)
        self.assertEqual(
            {"create": 2, "manual-review": 529, "update": 215},
            first_plan["action_counts"],
        )
        self.assertEqual(732, first_plan["expected_after"])
        self.assertEqual([], validate_action_plan(first_plan, snapshot))

    def test_plan_updates_existing_creates_missing_and_holds_pending(self):
        snapshot = {
            "cards": [
                snapshot_card("c1", "r1", "基础词义｜甲"),
                snapshot_card("c2", "r2", "基础词义｜乙"),
            ]
        }
        registry = [semantic("甲"), semantic("乙", "pending"), semantic("丙")]

        plan, final_cards = build_action_plan(snapshot, registry, [])
        actions = {action["title"]: action for action in plan["actions"]}

        self.assertEqual("update", actions["基础词义｜甲"]["action"])
        self.assertEqual("c1", actions["基础词义｜甲"]["card_id"])
        self.assertEqual("manual-review", actions["基础词义｜乙"]["action"])
        self.assertEqual("create", actions["基础词义｜丙"]["action"])
        self.assertEqual(3, plan["expected_after"])
        self.assertEqual(2, len(final_cards))

    def test_validation_rejects_create_when_equivalent_card_exists(self):
        snapshot = {"cards": [snapshot_card("c1", "r1", "基础词义｜甲")]}
        plan = {
            "before": 1,
            "expected_after": 2,
            "actions": [
                {
                    "title": "基础词义｜甲",
                    "action": "create",
                    "content_hash": "abc",
                    "reason": "错误创建",
                    "record_status": "ready",
                }
            ],
        }

        errors = validate_action_plan(plan, snapshot)

        self.assertIn("create duplicates existing title: 基础词义｜甲", errors)

    def test_validation_rejects_mutation_for_pending_record_and_bad_count(self):
        snapshot = {"cards": []}
        plan = {
            "before": 0,
            "expected_after": 0,
            "actions": [
                {
                    "title": "基础词义｜待核词",
                    "action": "create",
                    "content_hash": "abc",
                    "reason": "不应创建",
                    "record_status": "pending",
                }
            ],
        }

        errors = validate_action_plan(plan, snapshot)

        self.assertIn("pending record has mutating action: 基础词义｜待核词", errors)
        self.assertIn("action count equation mismatch", errors)


if __name__ == "__main__":
    unittest.main()
