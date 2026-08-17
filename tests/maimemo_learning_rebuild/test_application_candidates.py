import unittest

from maimemo_learning_rebuild.application_candidates import extract_context_candidates


class ApplicationCandidateTests(unittest.TestCase):
    def test_extracts_source_bound_context_and_masks_answer(self):
        record = {
            "term": "因噎废食",
            "evidence": [
                {
                    "source": "课程原文",
                    "location": "P17",
                    "quote": "有一个孩子接种后出现不良反应，不能因此停止所有必要接种，这样做就是因噎废食。",
                }
            ],
        }

        candidates = extract_context_candidates(record, ["因噎废食", "投鼠忌器"])

        self.assertEqual(1, len(candidates))
        self.assertNotIn("因噎废食", candidates[0]["prompt"])
        self.assertIn("______", candidates[0]["prompt"])
        self.assertEqual("因噎废食", candidates[0]["answer"])
        self.assertEqual("课程原文", candidates[0]["source"])
        self.assertEqual("P17", candidates[0]["location"])

    def test_rejects_definition_lecture_and_sentences_leaking_another_option(self):
        record = {
            "term": "因噎废食",
            "evidence": [
                {
                    "source": "课程原文",
                    "location": "P18",
                    "quote": (
                        "因噎废食这个词主要是说因为害怕问题而停止行动。"
                        "这里同时出现因噎废食和投鼠忌器，答案已经泄露。"
                    ),
                }
            ],
        }

        candidates = extract_context_candidates(record, ["因噎废食", "投鼠忌器"])

        self.assertEqual([], candidates)


if __name__ == "__main__":
    unittest.main()
