import unittest

from maimemo_learning_rebuild.models import (
    validate_action_record,
    validate_group_record,
    validate_semantic_record,
)


def valid_record():
    return {
        "term": "因噎废食",
        "sense_id": "因噎废食::课程义::001",
        "status": "ready",
        "source_kind": "teacher_transcript",
        "meaning": "因害怕出问题而停止本应继续的行动。",
        "distinctive_feature": "由问题或风险恐惧触发，并导致必要行动被放弃。",
        "dimensions": [
            {"axis": "触发条件", "judgment": "已经出过问题或担心出问题。"}
        ],
        "comparison_edges": [
            {
                "other_term": "投鼠忌器",
                "minimum_difference": "因噎废食怕问题；投鼠忌器怕牵连。",
            }
        ],
        "misuse_boundary": "没有停止必要行动时不宜使用。",
        "evidence": [
            {"source": "lesson.txt", "location": "P001", "quote": "老师原话"}
        ],
    }


class SemanticRecordTests(unittest.TestCase):
    def test_ready_record_accepts_complete_learning_fields_and_evidence(self):
        self.assertEqual([], validate_semantic_record(valid_record()))

    def test_ready_record_rejects_repeated_meaning_and_feature(self):
        record = valid_record()
        record["distinctive_feature"] = record["meaning"]

        self.assertIn(
            "meaning equals distinctive_feature",
            validate_semantic_record(record),
        )

    def test_teacher_record_requires_evidence(self):
        record = valid_record()
        record["evidence"] = []

        self.assertIn(
            "teacher_transcript record requires evidence",
            validate_semantic_record(record),
        )

    def test_user_supplement_may_be_ready_without_teacher_evidence(self):
        record = valid_record()
        record["source_kind"] = "user_directed_supplement"
        record["evidence"] = []

        self.assertEqual([], validate_semantic_record(record))

    def test_pending_record_does_not_require_learner_fields(self):
        record = {
            "term": "待核词",
            "sense_id": "待核词::待核::001",
            "status": "pending",
            "source_kind": "historical_only",
            "evidence": [],
        }

        self.assertEqual([], validate_semantic_record(record))

    def test_record_rejects_ambiguous_references(self):
        record = valid_record()
        record["comparison_edges"][0]["minimum_difference"] = "前者更重。"

        self.assertIn("ambiguous reference: 前者", validate_semantic_record(record))


class GroupRecordTests(unittest.TestCase):
    def test_group_accepts_known_unique_members(self):
        group = {
            "group_id": "g001",
            "members": ["因噎废食", "投鼠忌器"],
            "purpose": "顾虑来源不同",
            "status": "ready",
        }

        self.assertEqual(
            [], validate_group_record(group, ["因噎废食", "投鼠忌器"])
        )

    def test_group_rejects_unknown_and_duplicate_members(self):
        group = {
            "group_id": "g001",
            "members": ["因噎废食", "未知词", "因噎废食"],
            "purpose": "顾虑来源不同",
            "status": "ready",
        }

        errors = validate_group_record(group, ["因噎废食", "投鼠忌器"])
        self.assertIn("duplicate group member: 因噎废食", errors)
        self.assertIn("unknown group member: 未知词", errors)


class ActionRecordTests(unittest.TestCase):
    def test_update_requires_existing_card_id(self):
        action = {
            "action": "update",
            "title": "基础词义｜因噎废食",
            "card_id": None,
            "content_hash": "abc",
            "reason": "改进学习内容",
        }

        self.assertIn(
            "update requires card_id",
            validate_action_record(action),
        )

    def test_action_rejects_unknown_value(self):
        action = {
            "action": "delete",
            "title": "基础词义｜因噎废食",
            "card_id": "mkjc_1",
            "content_hash": "abc",
            "reason": "不支持删除",
        }

        self.assertIn("unknown action: delete", validate_action_record(action))


if __name__ == "__main__":
    unittest.main()
