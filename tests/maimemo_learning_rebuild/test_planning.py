import copy
import unittest
import json
from pathlib import Path

from maimemo_learning_rebuild.application_blind_review import blind_review_hash
from maimemo_learning_rebuild.application_quality_gate import application_review_hash
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
    def test_plan_binds_application_and_blind_reviews(self):
        snapshot = {"cards": []}
        registry = [semantic("甲")]
        application_review = {"complete": True, "applications": []}
        blind_review = {"complete": True, "reviews": []}

        plan, _ = build_action_plan(
            snapshot,
            registry,
            [],
            application_review,
            blind_review,
        )

        self.assertEqual(
            application_review_hash(application_review),
            plan["application_review_hash"],
        )
        self.assertEqual(blind_review_hash(blind_review), plan["blind_review_hash"])
        self.assertEqual(
            [],
            validate_action_plan(
                plan,
                snapshot,
                application_review,
                blind_review,
            ),
        )

    def test_validation_rejects_changed_application_or_blind_review(self):
        snapshot = {"cards": []}
        registry = [semantic("甲")]
        application_review = {"complete": True, "applications": []}
        blind_review = {"complete": True, "reviews": []}
        plan, _ = build_action_plan(
            snapshot,
            registry,
            [],
            application_review,
            blind_review,
        )
        changed_application_review = copy.deepcopy(application_review)
        changed_application_review["complete"] = False
        changed_blind_review = copy.deepcopy(blind_review)
        changed_blind_review["complete"] = False

        application_errors = validate_action_plan(
            plan,
            snapshot,
            changed_application_review,
            blind_review,
        )
        blind_errors = validate_action_plan(
            plan,
            snapshot,
            application_review,
            changed_blind_review,
        )
        malformed_blind_errors = validate_action_plan(
            plan,
            snapshot,
            application_review,
            [],
        )

        self.assertIn(
            "action plan is not bound to current application review",
            application_errors,
        )
        self.assertIn(
            "action plan is not bound to current blind review",
            blind_errors,
        )
        self.assertIn(
            "action plan is not bound to current blind review",
            malformed_blind_errors,
        )

    def test_validation_fails_closed_when_bound_reviews_are_not_supplied(self):
        snapshot = {"cards": []}
        registry = [semantic("甲")]
        application_review = {"complete": True, "applications": []}
        blind_review = {"complete": True, "reviews": []}
        plan, _ = build_action_plan(
            snapshot,
            registry,
            [],
            application_review,
            blind_review,
        )

        errors = validate_action_plan(plan, snapshot)

        self.assertIn("current application review is missing", errors)
        self.assertIn("current blind review is missing", errors)


    def test_new_deck_uses_runtime_root_placeholder_for_created_comparison(self):
        snapshot = {"cards": []}
        registry = [semantic("甲"), semantic("乙")]
        group = {
            "group_id": "group::old-root",
            "source_card_id": "old-card",
            "root_id": "mkjr_old_deck_root",
            "status": "ready",
            "title": "近义辨析｜甲、乙",
            "members": ["甲", "乙"],
            "minimum_differences": [
                {"left": "甲", "right": "乙", "text": "甲强调当前状态，乙强调变化过程。"}
            ],
            "dimensions": [],
            "misuse_boundary": "缺少相应判断条件时不得混用。",
        }

        plan, final_cards = build_action_plan(snapshot, registry, [group])

        comparison_action = next(
            item for item in plan["actions"] if item["title"] == "近义辨析｜甲、乙"
        )
        base_card = next(item for item in final_cards if item["title"] == "基础词义｜甲")
        self.assertEqual("create", comparison_action["action"])
        self.assertIn("{{root:近义辨析｜甲、乙}}", base_card["content"])
        self.assertNotIn("mkjr_old_deck_root", base_card["content"])

    def test_plan_creates_reviewed_application_card_and_counts_it(self):
        snapshot = {"cards": []}
        registry = [semantic("因噎废食"), semantic("投鼠忌器")]
        application = {
            "title": "语境应用｜因噎废食、投鼠忌器｜风险触发",
            "prompt": "某地担心改革过程中出现问题，索性停止已经启动且有必要继续的改革。填入哪个词最准确？",
            "options": ["因噎废食", "投鼠忌器"],
            "answer": "因噎废食",
            "clue_extraction": ["担心改革出问题", "停止本应继续的行动"],
            "fit_reasoning": "因噎废食要求风险担忧导致必要行动被整体放弃。",
            "distractor_rejections": {
                "投鼠忌器": "投鼠忌器要求顾忌行动会伤及关联对象，题干没有关联对象。"
            },
            "transfer_rule": "先判断是停止必要行动，还是因顾忌关联对象而不敢行动。",
            "uniqueness_rationale": "停止必要行动是决定性线索，只支持因噎废食。",
            "construction": {
                "mode": "authored",
                "semantic_basis": [
                    "因噎废食::课程义::001",
                    "投鼠忌器::课程义::001",
                ],
                "source_basis": [],
                "construction_note": "依据核定词义和最小差别自主创作。",
            },
        }
        review = {"complete": True, "applications": [application]}

        plan, final_cards = build_action_plan(snapshot, registry, [], review)

        action = next(item for item in plan["actions"] if item["title"] == application["title"])
        card = next(item for item in final_cards if item["title"] == application["title"])
        self.assertEqual("create", action["action"])
        self.assertEqual("application", card["card_type"])
        self.assertEqual(application, card["application"])
        self.assertIn("【排除投鼠忌器】", card["content"])
        self.assertEqual(3, plan["expected_after"])

    def test_real_offline_plan_is_deterministic_and_count_safe(self):
        root = Path(__file__).parents[2]
        artifact_root = root / "maimemo_learning_rebuild" / "artifacts"
        source_root = root.parents[1]
        snapshot = json.loads(
            self._required_private_snapshot(source_root).read_text(encoding="utf-8-sig")
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
            {"create": 16, "update": 730},
            first_plan["action_counts"],
        )
        self.assertEqual(746, first_plan["expected_after"])
        self.assertEqual([], validate_action_plan(first_plan, snapshot))

    def _required_private_snapshot(self, source_root: Path) -> Path:
        path = (
            source_root
            / "maimemo_four_poems"
            / "audit_readonly"
            / "current_library_snapshot_2026-08-17.json"
        )
        if not path.exists():
            self.skipTest("private live-library snapshot is intentionally not published")
        return path

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
