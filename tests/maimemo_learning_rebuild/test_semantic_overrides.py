import unittest

from maimemo_learning_rebuild.semantic_overrides import apply_reviewed_override


class SemanticOverrideTests(unittest.TestCase):
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

        result = apply_reviewed_override(record, override, "review-01")

        self.assertEqual("ready", result["status"])
        self.assertNotIn("candidate", result)
        self.assertNotIn("review_blockers", result)
        self.assertNotIn("derived_content_quarantined", result["provenance"])
        self.assertEqual("review-01", result["provenance"]["manual_semantic_review"])

    def test_dictionary_supplement_does_not_claim_teacher_authorship(self):
        record = {
            "term": "甲",
            "status": "pending",
            "source_kind": "teacher_transcript",
            "evidence": [{"source": "课堂", "location": "P1", "quote": "只提到词面"}],
            "candidate": {"course_sense": "不足"},
            "review_blockers": ["讲解不足"],
            "provenance": {"derived_content_quarantined": True},
        }
        override = {
            "status": "ready",
            "source_kind": "secondary_reference",
            "meaning": "词典核定含义。",
            "distinctive_feature": "可操作的区别。",
            "recognition_cues": ["识别线索。"],
            "dimensions": [{"axis": "对象", "judgment": "特定对象。"}],
            "comparison_edges": [],
            "misuse_boundary": "缺少条件时不用。",
            "evidence": [{"source": "词典", "location": "网址", "quote": "词典释义。"}],
        }

        result = apply_reviewed_override(record, override, "dictionary-review")

        self.assertEqual("secondary_reference", result["source_kind"])
        self.assertEqual(override["evidence"], result["evidence"])
        self.assertEqual("dictionary-review", result["provenance"]["manual_semantic_review"])

    def test_boundary_note_cannot_promote_a_record(self):
        record = {
            "term": "甲",
            "status": "pending",
            "candidate": {"course_sense": "机器候选"},
            "review_blockers": ["派生内容待审"],
            "provenance": {"derived_content_quarantined": True},
        }

        result = apply_reviewed_override(
            record,
            {"status": "ready", "misuse_boundary": "只有边界。"},
            "boundary-notes",
        )

        self.assertEqual("pending", result["status"])
        self.assertIn("candidate", result)
        self.assertIn("人工覆盖缺少完整学习字段", result["review_blockers"])
    def test_manual_evidence_replaces_truncated_extracted_evidence(self):
        record = {
            "term": "甲",
            "status": "pending",
            "evidence": [{"source": "旧来源", "location": "P0001", "quote": "截断。"}],
            "candidate": {"course_sense": "旧候选"},
            "review_blockers": ["待重建"],
            "provenance": {"source_index_only": True},
        }
        override = {
            "status": "ready",
            "source_kind": "secondary_reference",
            "meaning": "准确词义。",
            "distinctive_feature": "可做题的最小差别。",
            "recognition_cues": ["识别线索。"],
            "dimensions": [{"axis": "对象", "judgment": "特定对象。"}],
            "comparison_edges": [],
            "misuse_boundary": "缺少特定对象时不用。",
            "evidence": [
                {"source": "原课逐字稿.txt", "location": "P0002", "quote": "完整原话。"}
            ],
        }

        result = apply_reviewed_override(
            record, override, "review-20", provenance={"source_batch": "course-a"}
        )

        self.assertEqual("ready", result["status"])
        self.assertEqual("secondary_reference", result["source_kind"])
        self.assertEqual(override["evidence"], result["evidence"])
        self.assertNotIn("candidate", result)
        self.assertNotIn("review_blockers", result)
        self.assertEqual("review-20", result["provenance"]["manual_semantic_review"])
        self.assertEqual("course-a", result["provenance"]["source_batch"])


if __name__ == "__main__":
    unittest.main()
