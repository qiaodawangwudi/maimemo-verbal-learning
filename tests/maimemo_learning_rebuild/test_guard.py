import copy
import unittest

from maimemo_learning_rebuild.guard import evaluate_guard as _evaluate_guard
from maimemo_learning_rebuild.learning_quality import (
    evaluate_learning_quality,
    learning_review_hash,
)
from maimemo_learning_rebuild.planning import build_action_plan


APPLICATION_REVIEW = {"complete": True, "applications": []}
BLIND_REVIEW = {"complete": True, "reviews": []}


def evaluate_guard(**kwargs):
    return _evaluate_guard(
        application_review=APPLICATION_REVIEW,
        blind_review=BLIND_REVIEW,
        **kwargs,
    )


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
    plan, cards = build_action_plan(
        snapshot, registry, [], APPLICATION_REVIEW, BLIND_REVIEW
    )
    independent_review = {
        "complete": True,
        "reviewer_context_isolated": True,
        "resolutions": [],
    }
    independent_review["review_hash"] = learning_review_hash(independent_review)
    approval = {
        "chapter_id": "chapter",
        "plan_hash": plan["plan_hash"],
        "action_counts": plan["action_counts"],
        "learning_review_hash": independent_review["review_hash"],
    }
    return snapshot, registry, [], cards, plan, approval, independent_review


def reviewed_fixture(record, resolution):
    snapshot, _, groups, _, _, _, _ = safe_fixture()
    registry = [record]
    plan, cards = build_action_plan(
        snapshot, registry, groups, APPLICATION_REVIEW, BLIND_REVIEW
    )
    independent_review = {
        "complete": True,
        "reviewer_context_isolated": True,
        "resolutions": [
            {
                "subject_id": record["sense_id"],
                "issue": "meaning and feature are near-duplicates",
                "reviewer_context_isolated": True,
                **resolution,
            }
        ],
    }
    independent_review["review_hash"] = learning_review_hash(independent_review)
    approval = {
        "chapter_id": "chapter",
        "plan_hash": plan["plan_hash"],
        "action_counts": plan["action_counts"],
        "learning_review_hash": independent_review["review_hash"],
    }
    return snapshot, registry, groups, cards, plan, approval, independent_review


class WriteGuardTests(unittest.TestCase):
    def test_safe_complete_plan_passes(self):
        snapshot, registry, groups, cards, plan, approval, independent_review = safe_fixture()

        result = evaluate_guard(
            snapshot=snapshot,
            registry=registry,
            groups=groups,
            final_cards=cards,
            plan=plan,
            catalog={"sources": []},
            approval=approval,
            target_chapter_id="chapter",
            independent_review=independent_review,
        )

        self.assertTrue(result.ok, result.errors)

    def test_pending_record_missing_approval_and_wrong_chapter_are_blocked(self):
        snapshot, registry, groups, cards, plan, _, independent_review = safe_fixture()
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
            independent_review=independent_review,
        )

        self.assertIn("registry has non-ready records: 1", result.errors)
        self.assertIn("missing write approval", result.errors)
        self.assertIn("wrong target chapter: wrong", result.errors)

    def test_repeated_fields_generic_warning_and_changed_plan_hash_are_blocked(self):
        snapshot, registry, groups, cards, plan, approval, independent_review = safe_fixture()
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
            independent_review=independent_review,
        )

        self.assertTrue(any("meaning equals distinctive_feature" in error for error in result.errors))
        self.assertTrue(any("generic misuse boundary" in error for error in result.errors))
        self.assertIn("action count equation mismatch", result.errors)
        self.assertIn("plan hash mismatch", result.errors)

    def test_approval_must_match_hash_counts_and_chapter(self):
        snapshot, registry, groups, cards, plan, approval, independent_review = safe_fixture()
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
            independent_review=independent_review,
        )

        self.assertIn("approval plan hash mismatch", result.errors)
        self.assertIn("approval action counts mismatch", result.errors)
        self.assertIn("approval chapter mismatch", result.errors)

    def test_missing_independent_review_is_blocked(self):
        snapshot, registry, groups, cards, plan, approval, _ = safe_fixture()

        result = evaluate_guard(
            snapshot=snapshot,
            registry=registry,
            groups=groups,
            final_cards=cards,
            plan=plan,
            catalog={"sources": []},
            approval=approval,
            target_chapter_id="chapter",
            independent_review=None,
        )

        self.assertIn("missing independent learning review", result.errors)

    def test_malformed_independent_review_is_rejected_as_incomplete(self):
        snapshot, registry, groups, cards, plan, approval, _ = safe_fixture()

        result = evaluate_guard(
            snapshot=snapshot,
            registry=registry,
            groups=groups,
            final_cards=cards,
            plan=plan,
            catalog={"sources": []},
            approval=approval,
            target_chapter_id="chapter",
            independent_review=[],
        )

        self.assertIn("independent learning review is incomplete", result.errors)

    def test_resolutions_must_exist_and_be_a_list_of_objects(self):
        for malformed in ("missing", None, {}, "not-a-list", [1]):
            with self.subTest(malformed=malformed):
                snapshot, registry, groups, cards, plan, approval, review = safe_fixture()
                review.pop("review_hash")
                if malformed == "missing":
                    review.pop("resolutions")
                else:
                    review["resolutions"] = malformed
                approval["learning_review_hash"] = learning_review_hash(review)

                result = evaluate_guard(
                    snapshot=snapshot,
                    registry=registry,
                    groups=groups,
                    final_cards=cards,
                    plan=plan,
                    catalog={"sources": []},
                    approval=approval,
                    target_chapter_id="chapter",
                    independent_review=review,
                )

                self.assertFalse(result.ok)
                self.assertIn("independent learning review is incomplete", result.errors)

    def test_near_duplicate_rewrite_not_required_resolution_is_incomplete(self):
        snapshot, registry, groups, cards, plan, approval, review = safe_fixture()
        review.pop("review_hash")
        review["resolutions"] = [
            {
                "subject_id": registry[0]["sense_id"],
                "issue": "meaning and feature are near-duplicates",
                "decision": "rewrite_not_required",
                "reason": "已经完成独立人工审核没有发现问题，可以保持当前两个字段。",
                "reviewer_context_isolated": True,
            }
        ]
        approval["learning_review_hash"] = learning_review_hash(review)

        result = evaluate_guard(
            snapshot=snapshot,
            registry=registry,
            groups=groups,
            final_cards=cards,
            plan=plan,
            catalog={"sources": []},
            approval=approval,
            target_chapter_id="chapter",
            independent_review=review,
        )

        self.assertFalse(result.ok)
        self.assertIn("independent learning review is incomplete", result.errors)

    def test_near_duplicate_explanations_cannot_bypass_guard(self):
        cases = (
            {
                "decision": "rewrite_not_required",
                "meaning_observation": "基础已经牢固，并进一步得到强化",
                "feature_observation": "巩固原有根基，同时强化既有基础",
                "reason": (
                    "基础已经牢固，并进一步得到强化巩固原有根基，同时强化既有基础，"
                    "而两者不同所以不同。"
                ),
            },
            {
                "decision": "rewrite_not_required",
                "meaning_observation": "基础已经牢固",
                "feature_observation": "强化既有基础",
                "reason": "基础已经牢固强化既有基础，两者就是不同内容且落点不同。",
            },
            {
                "decision": "rewrite_required",
                "meaning_observation": "meaning陈述基础牢固的状态结果",
                "feature_observation": "feature重复巩固与强化基础的动作",
                "reason": (
                    "当前meaning仅陈述基础状态结果，feature仍重复巩固与强化动作，"
                    "内容尚未完成改写。"
                ),
            },
        )

        for resolution in cases:
            with self.subTest(resolution=resolution):
                record = ready_record("固本强基")
                record["meaning"] = "基础已经牢固，并进一步得到强化。"
                record["distinctive_feature"] = "巩固原有根基，同时强化既有基础。"
                fixture = reviewed_fixture(record, resolution)
                snapshot, registry, groups, cards, plan, approval, review = fixture

                self.assertIn(
                    "meaning and feature are near-duplicates: 固本强基",
                    evaluate_learning_quality(registry, groups, review),
                )
                result = evaluate_guard(
                    snapshot=snapshot,
                    registry=registry,
                    groups=groups,
                    final_cards=cards,
                    plan=plan,
                    catalog={"sources": []},
                    approval=approval,
                    target_chapter_id="chapter",
                    independent_review=review,
                )

                self.assertFalse(result.ok)
                self.assertIn(
                    "meaning and feature are near-duplicates: 固本强基",
                    result.errors,
                )

    def test_actual_record_rewrite_passes_guard(self):
        record = ready_record("固本强基")
        record["meaning"] = "指先稳住根本条件，再增强支撑长期发展的基础能力。"
        record["distinctive_feature"] = (
            "题干必须同时出现巩固根本与提升基础能力两个动作。"
        )
        resolution = {
            "decision": "rewrite_required",
            "reason": "已按审查要求改写词义与判断特征，并重新运行算法核验两者不再近似。",
        }
        fixture = reviewed_fixture(record, resolution)
        snapshot, registry, groups, cards, plan, approval, review = fixture

        self.assertEqual([], evaluate_learning_quality(registry, groups, review))
        result = evaluate_guard(
            snapshot=snapshot,
            registry=registry,
            groups=groups,
            final_cards=cards,
            plan=plan,
            catalog={"sources": []},
            approval=approval,
            target_chapter_id="chapter",
            independent_review=review,
        )

        self.assertTrue(result.ok, result.errors)

    def test_changed_incomplete_and_non_isolated_reviews_are_blocked(self):
        snapshot, registry, groups, cards, plan, approval, review = safe_fixture()
        review["complete"] = False
        review["reviewer_context_isolated"] = False

        result = evaluate_guard(
            snapshot=snapshot,
            registry=registry,
            groups=groups,
            final_cards=cards,
            plan=plan,
            catalog={"sources": []},
            approval=approval,
            target_chapter_id="chapter",
            independent_review=review,
        )

        self.assertIn("independent learning review hash mismatch", result.errors)
        self.assertIn("independent learning review is incomplete", result.errors)
        self.assertIn("independent learning review is not context-isolated", result.errors)

    def test_approval_must_bind_current_learning_review_hash(self):
        snapshot, registry, groups, cards, plan, approval, review = safe_fixture()
        approval["learning_review_hash"] = "stale"

        result = evaluate_guard(
            snapshot=snapshot,
            registry=registry,
            groups=groups,
            final_cards=cards,
            plan=plan,
            catalog={"sources": []},
            approval=approval,
            target_chapter_id="chapter",
            independent_review=review,
        )

        self.assertIn("approval learning review hash mismatch", result.errors)

    def test_approval_hash_can_bind_review_without_redundant_self_hash(self):
        snapshot, registry, groups, cards, plan, approval, review = safe_fixture()
        review.pop("review_hash")

        result = evaluate_guard(
            snapshot=snapshot,
            registry=registry,
            groups=groups,
            final_cards=cards,
            plan=plan,
            catalog={"sources": []},
            approval=approval,
            target_chapter_id="chapter",
            independent_review=review,
        )

        self.assertTrue(result.ok, result.errors)


if __name__ == "__main__":
    unittest.main()
