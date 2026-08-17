import copy
import unittest

from maimemo_learning_rebuild.guard import evaluate_guard
from maimemo_learning_rebuild.planning import build_action_plan


def ready_record(term="甲"):
    return {
        "term": term,
        "sense_id": f"{term}::补充义::001",
        "status": "ready",
        "source_kind": "user_directed_supplement",
        "meaning": f"{term}的准确词义。",
        "distinctive_feature": f"{term}的独特判断落点。",
        "recognition_cues": ["识别线索"],
        "dimensions": [],
        "comparison_edges": [],
        "misuse_boundary": "没有必要语义条件时不使用。",
        "evidence": [],
        "registry_order": 1,
    }


def safe_fixture():
    snapshot = {
        "deck_id": "deck",
        "chapter": {"id": "chapter", "name": "默认积累"},
        "cards": [
            {
                "id": "c1",
                "root_id": "r1",
                "grammar_version": 3,
                "content": "[P#H1#基础词义｜甲]\n\n问题\n\n---\n\n旧内容",
            }
        ],
    }
    registry = [ready_record()]
    plan, cards = build_action_plan(snapshot, registry, [])
    approval = {
        "chapter_id": "chapter",
        "plan_hash": plan["plan_hash"],
        "action_counts": plan["action_counts"],
    }
    return snapshot, registry, [], cards, plan, approval


class WriteGuardTests(unittest.TestCase):
    def test_safe_complete_plan_passes(self):
        snapshot, registry, groups, cards, plan, approval = safe_fixture()

        result = evaluate_guard(
            snapshot=snapshot,
            registry=registry,
            groups=groups,
            final_cards=cards,
            plan=plan,
            catalog={"sources": []},
            approval=approval,
            target_chapter_id="chapter",
        )

        self.assertTrue(result.ok, result.errors)

    def test_pending_record_missing_approval_and_wrong_chapter_are_blocked(self):
        snapshot, registry, groups, cards, plan, _ = safe_fixture()
        registry[0] = {
            "term": "甲",
            "sense_id": "甲::待核::001",
            "status": "pending",
            "source_kind": "historical_only",
        }

        result = evaluate_guard(
            snapshot=snapshot,
            registry=registry,
            groups=groups,
            final_cards=cards,
            plan=plan,
            catalog={"sources": []},
            approval=None,
            target_chapter_id="wrong",
        )

        self.assertIn("registry has non-ready records: 1", result.errors)
        self.assertIn("missing write approval", result.errors)
        self.assertIn("wrong target chapter: wrong", result.errors)

    def test_repeated_fields_generic_warning_and_changed_plan_hash_are_blocked(self):
        snapshot, registry, groups, cards, plan, approval = safe_fixture()
        registry[0]["distinctive_feature"] = registry[0]["meaning"]
        registry[0]["misuse_boundary"] = "需结合题干逻辑对应点使用。"
        plan["expected_after"] = 99

        result = evaluate_guard(
            snapshot=snapshot,
            registry=registry,
            groups=groups,
            final_cards=cards,
            plan=plan,
            catalog={"sources": []},
            approval=approval,
            target_chapter_id="chapter",
        )

        self.assertTrue(any("meaning equals distinctive_feature" in error for error in result.errors))
        self.assertTrue(any("generic misuse boundary" in error for error in result.errors))
        self.assertIn("action count equation mismatch", result.errors)
        self.assertIn("plan hash mismatch", result.errors)

    def test_approval_must_match_hash_counts_and_chapter(self):
        snapshot, registry, groups, cards, plan, approval = safe_fixture()
        bad = copy.deepcopy(approval)
        bad["plan_hash"] = "changed"
        bad["action_counts"] = {"create": 999}
        bad["chapter_id"] = "elsewhere"

        result = evaluate_guard(
            snapshot=snapshot,
            registry=registry,
            groups=groups,
            final_cards=cards,
            plan=plan,
            catalog={"sources": []},
            approval=bad,
            target_chapter_id="chapter",
        )

        self.assertIn("approval plan hash mismatch", result.errors)
        self.assertIn("approval action counts mismatch", result.errors)
        self.assertIn("approval chapter mismatch", result.errors)


if __name__ == "__main__":
    unittest.main()
