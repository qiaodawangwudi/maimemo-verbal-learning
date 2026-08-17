import unittest

from maimemo_learning_rebuild.application_quality_gate import (
    application_review_hash,
    evaluate_application_gate,
)


def semantic_record(term: str, sense_id: str) -> dict:
    return {"term": term, "sense_id": sense_id, "status": "ready"}


def comparison_group(group_id: str, members: list[str]) -> dict:
    return {"group_id": group_id, "members": members, "status": "ready"}


def application_card(title: str) -> dict:
    return {
        "title": title,
        "card_type": "application",
        "application": {
            "prompt": "某地担心改革出错，索性停止本应继续推进的改革。应选哪个词？",
            "options": ["因噎废食", "投鼠忌器"],
            "answer": "因噎废食",
            "clue_extraction": ["担心出错", "停止必要行动"],
            "fit_reasoning": "因噎废食要求风险担忧导致必要行动被整体放弃。",
            "distractor_rejections": {
                "投鼠忌器": "投鼠忌器要求顾忌行动会伤及关联对象，题干没有关联对象。"
            },
            "transfer_rule": "先判断结果是停止必要行动，还是因顾忌关联对象而不敢行动。",
            "uniqueness_rationale": "停止全部必要行动是决定性线索，只支持因噎废食。",
            "construction": {
                "mode": "authored",
                "semantic_basis": [
                    "因噎废食::课程义::001",
                    "投鼠忌器::课程义::001",
                ],
                "source_basis": [],
                "construction_note": "依据核定词义和最小差别自主创作书面语境。",
            },
        },
    }


def bound_plan(review: dict, titles: list[str]) -> dict:
    return {
        "application_review_hash": application_review_hash(review),
        "actions": [{"title": title} for title in titles],
    }


class ApplicationQualityGateTests(unittest.TestCase):
    def setUp(self):
        self.registry = {
            "records": [
                semantic_record("因噎废食", "因噎废食::课程义::001"),
                semantic_record("投鼠忌器", "投鼠忌器::课程义::001"),
            ]
        }
        self.groups = {
            "groups": [comparison_group("g-risk", ["因噎废食", "投鼠忌器"])]
        }

    def test_missing_review_artifact_blocks_release(self):
        errors = evaluate_application_gate(
            self.registry,
            self.groups,
            {},
            {"cards": []},
            {},
        )

        self.assertIn("application review is not marked complete", errors)
        self.assertIn("application review missing semantic decisions: 2", errors)
        self.assertIn("application review missing comparison-group decisions: 1", errors)

    def test_create_decision_requires_a_matching_application_card(self):
        review = {
            "complete": True,
            "decisions": [
                {
                    "subject_type": "semantic",
                    "subject_id": "因噎废食::课程义::001",
                    "decision": "not_needed",
                    "reason": "该词的独立误用边界已由同组语境训练覆盖，无需重复建卡。",
                },
                {
                    "subject_type": "semantic",
                    "subject_id": "投鼠忌器::课程义::001",
                    "decision": "not_needed",
                    "reason": "该词的独立误用边界已由同组语境训练覆盖，无需重复建卡。",
                },
                {
                    "subject_type": "comparison_group",
                    "subject_id": "g-risk",
                    "decision": "create",
                    "reason": "只有放进风险触发和关联对象不同的语境，才能训练二者的选择。",
                    "training_goal": "区分停止必要行动与顾忌关联对象。",
                    "card_title": "语境应用｜因噎废食、投鼠忌器｜风险触发",
                },
            ],
        }

        errors = evaluate_application_gate(
            self.registry,
            self.groups,
            review,
            {"cards": []},
            bound_plan(review, []),
        )

        self.assertIn(
            "application decision has no matching card: 语境应用｜因噎废食、投鼠忌器｜风险触发",
            errors,
        )

    def test_rejects_answer_only_or_weak_application_card(self):
        title = "语境应用｜因噎废食、投鼠忌器｜风险触发"
        review = {
            "complete": True,
            "decisions": [
                {
                    "subject_type": "semantic",
                    "subject_id": "因噎废食::课程义::001",
                    "decision": "not_needed",
                    "reason": "该词的独立误用边界已由同组语境训练覆盖，无需重复建卡。",
                },
                {
                    "subject_type": "semantic",
                    "subject_id": "投鼠忌器::课程义::001",
                    "decision": "not_needed",
                    "reason": "该词的独立误用边界已由同组语境训练覆盖，无需重复建卡。",
                },
                {
                    "subject_type": "comparison_group",
                    "subject_id": "g-risk",
                    "decision": "create",
                    "reason": "只有放进风险触发和关联对象不同的语境，才能训练二者的选择。",
                    "training_goal": "区分停止必要行动与顾忌关联对象。",
                    "card_title": title,
                },
            ],
        }
        weak_card = {
            "title": title,
            "card_type": "application",
            "application": {
                "prompt": "应该选哪个词？",
                "options": ["因噎废食", "投鼠忌器"],
                "answer": "因噎废食",
            },
        }

        errors = evaluate_application_gate(
            self.registry,
            self.groups,
            review,
            {"cards": [weak_card]},
            bound_plan(review, [title]),
        )

        self.assertIn(f"application card lacks usable context: {title}", errors)
        self.assertIn(f"application card lacks clue extraction: {title}", errors)
        self.assertIn(f"application card lacks fit reasoning: {title}", errors)
        self.assertIn(f"application card lacks distractor rejection: {title}", errors)
        self.assertIn(f"application card lacks transfer rule: {title}", errors)

    def test_rejects_raw_spoken_prompt_and_unsupported_construction_mode(self):
        title = "语境应用｜因噎废食、投鼠忌器｜风险触发"
        review = {
            "complete": True,
            "decisions": [
                {
                    "subject_type": "semantic",
                    "subject_id": "因噎废食::课程义::001",
                    "decision": "not_needed",
                    "reason": "该词的独立误用边界已由同组语境训练覆盖，无需重复建卡。",
                },
                {
                    "subject_type": "semantic",
                    "subject_id": "投鼠忌器::课程义::001",
                    "decision": "not_needed",
                    "reason": "该词的独立误用边界已由同组语境训练覆盖，无需重复建卡。",
                },
                {
                    "subject_type": "comparison_group",
                    "subject_id": "g-risk",
                    "decision": "create",
                    "reason": "只有放进风险触发和关联对象不同的语境，才能训练二者的选择。",
                    "training_goal": "区分停止必要行动与顾忌关联对象。",
                    "card_title": title,
                },
            ],
        }
        card = application_card(title)
        card["application"]["prompt"] = "同学们，咱们来看一下，这道题选因噎废食对不对？"
        card["application"]["construction"]["mode"] = "raw_transcript"

        errors = evaluate_application_gate(
            self.registry,
            self.groups,
            review,
            {"cards": [card]},
            bound_plan(review, [title]),
        )

        self.assertIn(f"application card uses unsupported construction mode: {title}", errors)
        self.assertIn(f"application card contains classroom speech: {title}", errors)

    def test_rejects_unadapted_source_sentence_and_missing_uniqueness_rationale(self):
        title = "语境应用｜因噎废食、投鼠忌器｜风险触发"
        source_sentence = "某地因担心改革出错，索性停止本应继续推进的改革。"
        self.registry["records"][0]["evidence"] = [
            {"source": "原题", "location": "P1", "quote": source_sentence}
        ]
        review = {
            "complete": True,
            "decisions": [
                {
                    "subject_type": "semantic",
                    "subject_id": "因噎废食::课程义::001",
                    "decision": "not_needed",
                    "reason": "该词的独立误用边界已由同组语境训练覆盖，无需重复建卡。",
                },
                {
                    "subject_type": "semantic",
                    "subject_id": "投鼠忌器::课程义::001",
                    "decision": "not_needed",
                    "reason": "该词的独立误用边界已由同组语境训练覆盖，无需重复建卡。",
                },
                {
                    "subject_type": "comparison_group",
                    "subject_id": "g-risk",
                    "decision": "create",
                    "reason": "只有放进风险触发和关联对象不同的语境，才能训练二者的选择。",
                    "training_goal": "区分停止必要行动与顾忌关联对象。",
                    "card_title": title,
                },
            ],
        }
        card = application_card(title)
        card["application"]["prompt"] = source_sentence
        card["application"]["uniqueness_rationale"] = ""

        errors = evaluate_application_gate(
            self.registry,
            self.groups,
            review,
            {"cards": [card]},
            bound_plan(review, [title]),
        )

        self.assertIn(f"application card copies source wording: {title}", errors)
        self.assertIn(f"application card lacks uniqueness rationale: {title}", errors)

    def test_accepts_complete_review_and_explanatory_application_card(self):
        title = "语境应用｜因噎废食、投鼠忌器｜风险触发"
        review = {
            "complete": True,
            "decisions": [
                {
                    "subject_type": "semantic",
                    "subject_id": "因噎废食::课程义::001",
                    "decision": "not_needed",
                    "reason": "该词的独立误用边界已由同组语境训练覆盖，无需重复建卡。",
                },
                {
                    "subject_type": "semantic",
                    "subject_id": "投鼠忌器::课程义::001",
                    "decision": "not_needed",
                    "reason": "该词的独立误用边界已由同组语境训练覆盖，无需重复建卡。",
                },
                {
                    "subject_type": "comparison_group",
                    "subject_id": "g-risk",
                    "decision": "create",
                    "reason": "只有放进风险触发和关联对象不同的语境，才能训练二者的选择。",
                    "training_goal": "区分停止必要行动与顾忌关联对象。",
                    "card_title": title,
                },
            ],
        }

        errors = evaluate_application_gate(
            self.registry,
            self.groups,
            review,
            {"cards": [application_card(title)]},
            bound_plan(review, [title]),
        )

        self.assertEqual([], errors)

    def test_rejects_plan_not_bound_to_review_or_missing_application_action(self):
        title = "语境应用｜因噎废食、投鼠忌器｜风险触发"
        review = {
            "complete": True,
            "decisions": [
                {
                    "subject_type": "semantic",
                    "subject_id": "因噎废食::课程义::001",
                    "decision": "not_needed",
                    "reason": "该词的独立误用边界已由同组语境训练覆盖，无需重复建卡。",
                },
                {
                    "subject_type": "semantic",
                    "subject_id": "投鼠忌器::课程义::001",
                    "decision": "not_needed",
                    "reason": "该词的独立误用边界已由同组语境训练覆盖，无需重复建卡。",
                },
                {
                    "subject_type": "comparison_group",
                    "subject_id": "g-risk",
                    "decision": "create",
                    "reason": "只有放进风险触发和关联对象不同的语境，才能训练二者的选择。",
                    "training_goal": "区分停止必要行动与顾忌关联对象。",
                    "card_title": title,
                },
            ],
        }

        errors = evaluate_application_gate(
            self.registry,
            self.groups,
            review,
            {"cards": [application_card(title)]},
            {"application_review_hash": "stale", "actions": []},
        )

        self.assertIn("action plan is not bound to current application review", errors)
        self.assertIn(f"application card is missing from action plan: {title}", errors)


if __name__ == "__main__":
    unittest.main()
