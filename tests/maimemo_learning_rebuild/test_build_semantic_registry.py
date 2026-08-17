import unittest

from maimemo_learning_rebuild.build_semantic_registry import (
    apply_lesson_five_override,
)


class LessonFiveOverrideTests(unittest.TestCase):
    def test_complete_manual_override_replaces_quarantined_candidate(self):
        record = {
            "term": "甲",
            "status": "pending",
            "candidate": {"course_sense": "机器候选"},
            "review_blockers": ["派生内容待审"],
            "provenance": {"derived_content_quarantined": True},
        }
        override = {
            "status": "ready",
            "meaning": "准确词义。",
            "distinctive_feature": "区别于近义词的落点。",
            "recognition_cues": ["题干线索。"],
            "dimensions": [{"axis": "对象", "judgment": "特定对象。"}],
            "comparison_edges": [],
            "misuse_boundary": "缺少特定对象时不使用。",
        }

        result = apply_lesson_five_override(record, override, "batch01")

        self.assertEqual("ready", result["status"])
        self.assertNotIn("candidate", result)
        self.assertNotIn("review_blockers", result)
        self.assertNotIn("derived_content_quarantined", result["provenance"])
        self.assertEqual("batch01", result["provenance"]["manual_semantic_review"])

    def test_boundary_note_cannot_promote_a_record(self):
        record = {
            "term": "甲",
            "status": "pending",
            "candidate": {"course_sense": "机器候选"},
            "review_blockers": ["派生内容待审"],
            "provenance": {"derived_content_quarantined": True},
        }

        result = apply_lesson_five_override(
            record,
            {"status": "ready", "misuse_boundary": "只有边界。"},
            "boundary-notes",
        )

        self.assertEqual("pending", result["status"])
        self.assertIn("candidate", result)
        self.assertIn("人工覆盖缺少完整学习字段", result["review_blockers"])


if __name__ == "__main__":
    unittest.main()
