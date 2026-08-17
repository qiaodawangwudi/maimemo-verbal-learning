import copy
import unittest

from maimemo_learning_rebuild.learning_quality import (
    evaluate_learning_quality,
    learning_review_hash,
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

    def test_valid_isolated_resolution_clears_algorithmic_flag(self):
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
                "decision": "rewrite_not_required",
                "reason": "词义说明状态变化，特征说明同时包含巩固与强化两个动作落点。",
                "reviewer_context_isolated": True,
            }
        ]

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
            "decision": "rewrite_not_required",
            "reason": "词义说明状态变化，特征说明两个不同的动作落点。",
            "reviewer_context_isolated": True,
        }
        malformed_values = {
            "subject_id": [record["sense_id"]],
            "issue": {"value": "meaning and feature are near-duplicates"},
            "decision": {"value": "rewrite_not_required"},
            "reason": {"detail": "词义和特征确实存在不同的动作落点"},
        }

        for field, value in malformed_values.items():
            with self.subTest(field=field):
                resolution = {**valid, field: value}
                review = {**empty_review(), "resolutions": [resolution]}
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
            ("rewrite_not_required", "不同不同不同不同不同不同"),
            ("rewrite_not_required", "已经人工审查确认没有问题"),
        )

        for decision, reason in invalid_pairs:
            with self.subTest(decision=decision, reason=reason):
                review = empty_review()
                review["resolutions"] = [
                    {
                        "subject_id": record["sense_id"],
                        "issue": "meaning and feature are near-duplicates",
                        "decision": decision,
                        "reason": reason,
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
        digest = learning_review_hash(review)
        stored = {**review, "review_hash": digest}

        self.assertEqual(digest, learning_review_hash(stored))
        changed = copy.deepcopy(stored)
        changed["complete"] = False
        self.assertNotEqual(digest, learning_review_hash(changed))


if __name__ == "__main__":
    unittest.main()
