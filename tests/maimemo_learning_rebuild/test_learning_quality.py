import copy
import unittest

from maimemo_learning_rebuild.learning_quality import (
    evaluate_learning_quality,
    learning_review_hash,
    validate_independent_review,
)


def ready_record(
    term="固本强基",
    meaning="巩固根本并强化基础。",
    distinctive_feature="既稳固根基，又提升基础能力。",
):
    return {
        "term": term,
        "sense_id": f"{term}::补充义::001",
        "status": "ready",
        "meaning": meaning,
        "distinctive_feature": distinctive_feature,
    }


def ready_group():
    return {
        "group_id": "g-risk",
        "status": "ready",
        "members": ["因噎废食", "投鼠忌器"],
        "minimum_differences": [
            {
                "left": "因噎废食",
                "right": "投鼠忌器",
                "text": "因噎废食停止必要行动；投鼠忌器顾忌牵连对象。",
                "shared_basis": "面对行动风险时是否继续行动",
                "axis": "顾忌对象与行动结果",
                "left_landing": "因风险而停止本应继续的行动",
                "right_landing": "因担心牵连关联对象而不敢行动",
                "evidence_ids": ["ev-risk-001", "ev-risk-002"],
                "review_status": "pass",
            }
        ],
    }


def empty_review():
    return {
        "complete": True,
        "reviewer_context_isolated": True,
        "resolutions": [],
    }


class LearningQualityTests(unittest.TestCase):
    def test_flags_paraphrased_meaning_and_feature(self):
        record = ready_record(
            term="固本强基",
            meaning="基础已经牢固，并进一步得到强化。",
            distinctive_feature="巩固原有根基，同时强化既有基础。",
        )

        self.assertIn(
            "meaning and feature are near-duplicates: 固本强基",
            evaluate_learning_quality([record], [], empty_review()),
        )

    def test_human_resolution_cannot_clear_near_duplicate_flag(self):
        record = ready_record(
            term="固本强基",
            meaning="基础已经牢固，并进一步得到强化。",
            distinctive_feature="巩固原有根基，同时强化既有基础。",
        )
        resolutions = (
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

        for resolution in resolutions:
            with self.subTest(resolution=resolution):
                review = empty_review()
                review["resolutions"] = [
                    {
                        "subject_id": record["sense_id"],
                        "issue": "meaning and feature are near-duplicates",
                        "reviewer_context_isolated": True,
                        **resolution,
                    }
                ]
                self.assertIn(
                    "meaning and feature are near-duplicates: 固本强基",
                    evaluate_learning_quality([record], [], review),
                )

    def test_near_duplicate_resolution_requires_rewrite_required_decision(self):
        record = ready_record()
        review = empty_review()
        review["resolutions"] = [
            {
                "subject_id": record["sense_id"],
                "issue": "meaning and feature are near-duplicates",
                "decision": "rewrite_not_required",
                "reason": "人工观察认为字段落点不同，但算法仍判定内容近似，暂不改写。",
                "reviewer_context_isolated": True,
            }
        ]

        self.assertIn(
            "independent learning review is incomplete",
            validate_independent_review(review),
        )

        review["resolutions"][0]["decision"] = "rewrite_required"
        self.assertEqual([], validate_independent_review(review))

    def test_actual_rewrite_clears_algorithmic_flag(self):
        record = ready_record(
            meaning="指先稳住根本条件，再增强支撑长期发展的基础能力。",
            distinctive_feature="题干必须同时出现巩固根本与提升基础能力两个动作。",
        )
        review = empty_review()
        review["resolutions"] = [
            {
                "subject_id": record["sense_id"],
                "issue": "meaning and feature are near-duplicates",
                "decision": "rewrite_required",
                "reason": "已按审查要求改写词义与判断特征，并重新运行算法核验两者不再近似。",
                "reviewer_context_isolated": True,
            }
        ]

        self.assertEqual([], validate_independent_review(review))
        self.assertEqual([], evaluate_learning_quality([record], [], review))

    def test_non_isolated_or_vague_resolution_cannot_clear_flag(self):
        record = ready_record(
            term="固本强基",
            meaning="基础已经牢固，并进一步得到强化。",
            distinctive_feature="巩固原有根基，同时强化既有基础。",
        )
        review = empty_review()
        review["resolutions"] = [
            {
                "subject_id": record["sense_id"],
                "issue": "meaning and feature are near-duplicates",
                "decision": "pass",
                "reason": "不同",
                "reviewer_context_isolated": False,
            }
        ]

        self.assertIn(
            "meaning and feature are near-duplicates: 固本强基",
            evaluate_learning_quality([record], [], review),
        )

    def test_non_string_resolution_fields_cannot_clear_flag(self):
        record = ready_record(
            term="固本强基",
            meaning="基础已经牢固，并进一步得到强化。",
            distinctive_feature="巩固原有根基，同时强化既有基础。",
        )
        valid = {
            "subject_id": record["sense_id"],
            "issue": "meaning and feature are near-duplicates",
            "decision": "rewrite_required",
            "reason": (
                "当前meaning与feature仍重复表达巩固基础，必须改写后重新运行算法核验。"
            ),
            "reviewer_context_isolated": True,
        }
        malformed_values = {
            "subject_id": [record["sense_id"]],
            "issue": {"value": "meaning and feature are near-duplicates"},
            "decision": {"value": "rewrite_required"},
            "reason": {"detail": "词义和特征确实存在不同的动作落点"},
        }

        for field, value in malformed_values.items():
            with self.subTest(field=field):
                resolution = {**valid, field: value}
                review = {**empty_review(), "resolutions": [resolution]}
                self.assertIn(
                    "independent learning review is incomplete",
                    validate_independent_review(review),
                )
                self.assertIn(
                    "meaning and feature are near-duplicates: 固本强基",
                    evaluate_learning_quality([record], [], review),
                )

    def test_unknown_decision_or_placeholder_reason_cannot_clear_flag(self):
        record = ready_record(
            term="固本强基",
            meaning="基础已经牢固，并进一步得到强化。",
            distinctive_feature="巩固原有根基，同时强化既有基础。",
        )
        invalid_pairs = (
            ("pass", "词义说明状态变化，特征说明两个不同的动作落点。"),
            ("rewrite_required", "不同不同不同不同不同不同"),
            ("rewrite_required", "已经人工审查确认没有问题"),
        )

        for decision, reason in invalid_pairs:
            with self.subTest(decision=decision, reason=reason):
                review = empty_review()
                review["resolutions"] = [
                    {
                        "subject_id": record["sense_id"],
                        "issue": "meaning and feature are near-duplicates",
                        "decision": decision,
                        "meaning_observation": "基础已经牢固，并进一步得到强化",
                        "feature_observation": "巩固原有根基，同时强化既有基础",
                        "reason": reason,
                        "reviewer_context_isolated": True,
                    }
                ]
                self.assertIn(
                    "independent learning review is incomplete",
                    validate_independent_review(review),
                )
                self.assertIn(
                    "meaning and feature are near-duplicates: 固本强基",
                    evaluate_learning_quality([record], [], review),
                )

    def test_rewrite_required_keeps_flag_without_fabricating_observations(self):
        record = ready_record(
            term="固本强基",
            meaning="基础已经牢固，并进一步得到强化。",
            distinctive_feature="巩固原有根基，同时强化既有基础。",
        )
        review = empty_review()
        review["resolutions"] = [
            {
                "subject_id": record["sense_id"],
                "issue": "meaning and feature are near-duplicates",
                "decision": "rewrite_required",
                "reason": "两字段目前无法形成可核验的不同学习落点，必须先改写再复审。",
                "reviewer_context_isolated": True,
            }
        ]

        self.assertIn(
            "meaning and feature are near-duplicates: 固本强基",
            evaluate_learning_quality([record], [], review),
        )

    def test_edge_requires_shared_basis_axis_and_both_landings(self):
        group = ready_group()
        group["minimum_differences"][0] = {
            "left": "因噎废食",
            "right": "投鼠忌器",
            "text": "二者含义不同。",
        }

        self.assertIn(
            "comparison edge lacks reviewed contrast contract",
            evaluate_learning_quality([], [group], empty_review()),
        )

    def test_complete_reviewed_edge_passes_learning_quality_gate(self):
        self.assertEqual(
            [],
            evaluate_learning_quality([], [ready_group()], empty_review()),
        )

    def test_every_ready_edge_contract_field_and_evidence_id_must_be_string(self):
        invalid_fields = {
            "shared_basis": 1,
            "axis": ["动作结果"],
            "left_landing": {"value": "停止行动"},
            "right_landing": ["顾忌对象"],
        }
        for field, value in invalid_fields.items():
            with self.subTest(field=field):
                group = ready_group()
                group["minimum_differences"][0][field] = value
                self.assertIn(
                    "comparison edge lacks reviewed contrast contract",
                    evaluate_learning_quality([], [group], empty_review()),
                )

        for evidence_id in (1, {"id": "ev-risk-001"}, ["ev-risk-001"]):
            with self.subTest(evidence_id=evidence_id):
                group = ready_group()
                group["minimum_differences"][0]["evidence_ids"] = [evidence_id]
                self.assertIn(
                    "comparison edge lacks reviewed contrast contract",
                    evaluate_learning_quality([], [group], empty_review()),
                )

    def test_each_ready_edge_is_checked_for_reviewed_contract(self):
        group = ready_group()
        second = copy.deepcopy(group["minimum_differences"][0])
        second["left"] = "投鼠忌器"
        second["right"] = "削足适履"
        second["evidence_ids"] = ["ev-risk-003"]
        second["axis"] = 7
        group["minimum_differences"].append(second)

        self.assertIn(
            "comparison edge lacks reviewed contrast contract",
            evaluate_learning_quality([], [group], empty_review()),
        )

    def test_review_hash_is_canonical_and_detects_content_change(self):
        review = empty_review()
        review["resolutions"] = [
            {
                "subject_id": "固本强基::补充义::001",
                "issue": "meaning and feature are near-duplicates",
                "decision": "rewrite_required",
                "meaning_observation": "基础已经牢固，并进一步得到强化",
                "feature_observation": "巩固原有根基，同时强化既有基础",
                "reason": (
                    "meaning观察“基础已经牢固，并进一步得到强化”，而feature观察"
                    "“巩固原有根基，同时强化既有基础”；前者陈述状态，后者陈述动作。"
                ),
                "reviewer_context_isolated": True,
            }
        ]
        digest = learning_review_hash(review)
        stored = {**review, "review_hash": digest}

        self.assertEqual(digest, learning_review_hash(stored))
        changed = copy.deepcopy(stored)
        changed["resolutions"][0]["feature_observation"] = "强化已有基础"
        self.assertNotEqual(digest, learning_review_hash(changed))


if __name__ == "__main__":
    unittest.main()
