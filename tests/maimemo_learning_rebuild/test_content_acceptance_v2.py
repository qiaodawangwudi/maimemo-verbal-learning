import copy
import unittest

from maimemo_learning_rebuild.content_acceptance_v2 import (
    validate_application_authoring,
    validate_comparison_review,
    validate_dimension_novelty,
    validate_preview_bundle,
    validate_semantic_review,
)


def semantic(term="甲词", slots=None):
    return {
        "term": term,
        "sense_id": f"sense::{term}",
        "status": "approved",
        "meaning": f"{term}表示在具体条件下完成相应行为。",
        "core_slots": slots or ["特定条件成立", "完成相应行为"],
        "question_cues": ["可观察对象", "明确动作"],
        "misuse_boundary": "缺少特定条件时不能使用。",
        "evidence": [{"source_group_id": "S1", "location": "P1", "quote": "可核原文"}],
    }


class SemanticAcceptanceV2Tests(unittest.TestCase):
    def test_rejects_mechanical_fragments_and_unreviewed_auto_records(self):
        records = [
            semantic("好高骛远", ["目标", "不切实际、追求、高"]),
            semantic("妙趣横生", ["洋溢美妙意趣（多指语言", "文章或美术作品）"]),
            semantic("待审词"),
        ]
        records[2]["status"] = "ready"

        errors = validate_semantic_review(records)

        self.assertTrue(any("punctuation fragment" in error for error in errors))
        self.assertTrue(any("broken bracket" in error for error in errors))
        self.assertTrue(any("status must be approved or pending" in error for error in errors))

    def test_accepts_keyword_slots_and_explicit_pending(self):
        pending = semantic("待审词")
        pending["status"] = "pending"
        pending["pending_reason"] = "教师证据只说明大意，尚不足以确认选择边界。"
        self.assertEqual([], validate_semantic_review([semantic(), pending]))


class ComparisonAcceptanceV2Tests(unittest.TestCase):
    def valid_group(self):
        return {
            "group_id": "g1",
            "status": "approved",
            "group_basis": "reciprocal_reviewed_boundary",
            "members": ["甲词", "乙词"],
            "member_profiles": {
                "甲词": {"meaning": "甲词表示主动进入并参与。", "core_slots": ["外部主体进入", "主动参与过程"]},
                "乙词": {"meaning": "乙词表示成为整体的一部分。", "core_slots": ["进入既有整体", "成为内部部分"]},
            },
            "one_glance_edges": [{"left": "甲词", "right": "乙词", "difference": "主动干预 vs 融入整体"}],
            "selection_rules": [
                {"condition": "题干强调外部力量干预进程", "choose": "甲词"},
                {"condition": "题干强调成为整体内部组成", "choose": "乙词"},
            ],
            "evidence_observations": {
                "甲词": {"observation": "外部主体进入并干预", "source_group_id": "S1", "location": "P1", "quote": "甲词原文"},
                "乙词": {"observation": "成为整体内部部分", "source_group_id": "S1", "location": "P2", "quote": "乙词原文"},
            },
        }

    def test_rejects_old_comparison_shape_without_teaching_layers(self):
        old = {"group_id": "g1", "terms": ["甲词", "乙词"], "one_glance": ["甲词：A", "乙词：B"], "dimensions": []}
        errors = validate_comparison_review([old])
        self.assertTrue(any("member profiles" in error for error in errors))
        self.assertTrue(any("pairwise one-glance" in error for error in errors))
        self.assertTrue(any("selection rules" in error for error in errors))

    def test_accepts_complete_named_comparison_group(self):
        self.assertEqual([], validate_comparison_review([self.valid_group()]))

    def test_rejects_course_proximity_as_formal_group_basis(self):
        group = self.valid_group()
        group["group_basis"] = "same_course_group_key"
        group["members"] = ["争雄", "共鸣", "关照"]
        errors = validate_comparison_review([group])
        self.assertTrue(any("group basis" in error for error in errors))

    def test_rejects_unlocatable_comparison_observations(self):
        group = self.valid_group()
        group["evidence_observations"]["甲词"] = "作者自己概括的一句话"
        errors = validate_comparison_review([group])
        self.assertTrue(any("comparison observation is not locatable" in error for error in errors))


class DimensionNoveltyV2Tests(unittest.TestCase):
    def test_rejects_dimension_that_splits_or_paraphrases_core(self):
        semantics = {
            "彳亍": semantic("彳亍", ["缓慢小步行走", "走走停停"]),
            "踌躇": semantic("踌躇", ["面对选择", "犹豫不决"]),
        }
        review = [{
            "group_id": "g1",
            "disposition": "approved_dimensions",
            "members": ["彳亍", "踌躇"],
            "dimensions": [
                {"axis": "行走表现", "judgments": {"彳亍": "彳亍强调缓慢小步行走、走走停停。", "踌躇": "踌躇可以没有行走动作。"}},
                {"axis": "心理状态", "judgments": {"彳亍": "彳亍不要求犹豫。", "踌躇": "踌躇表示面对选择时犹豫不决。"}},
            ],
        }]
        errors = validate_dimension_novelty(review, semantics)
        self.assertTrue(any("repeats core slot" in error for error in errors))


class ApplicationAcceptanceV2Tests(unittest.TestCase):
    def valid_application(self):
        return {
            "term": "投鼠忌器",
            "prompt": "监管部门准备查处违规平台，却发现直接关停会使大量已付款用户无法取回资金，因此暂缓行动。横线处最恰当的是（　）。",
            "options": ["投鼠忌器", "噤若寒蝉", "畏首畏尾", "隔岸观火"],
            "answer": "投鼠忌器",
            "scenario_elements": {
                "subject": "监管部门",
                "event": "查处违规平台",
                "constraint": "关停会伤及已付款用户",
                "outcome": "暂缓行动",
            },
            "distractor_rejections": {
                "噤若寒蝉": "题干不是因害怕而不敢说话。",
                "畏首畏尾": "题干给出了会伤及关联用户的具体顾虑，不是泛指胆小。",
                "隔岸观火": "监管部门并非旁观他人危难，而是在权衡处置后果。",
            },
        }

    def test_rejects_definition_prompt_even_when_labeled_authored(self):
        old = self.valid_application()
        old["prompt"] = "题干先写到“顾虑伤及关联对象”，又明确出现“不敢行动或放弃行动”这一落点。"
        old["construction"] = {"mode": "authored"}
        errors = validate_application_authoring([old], {"投鼠忌器": semantic("投鼠忌器", ["顾虑伤及关联对象", "不敢行动或放弃行动"])})
        self.assertTrue(any("meta definition prompt" in error for error in errors))
        self.assertTrue(any("quotes core slot" in error for error in errors))

    def test_rejects_exam_commentary_inside_the_scenario(self):
        item = self.valid_application()
        item["prompt"] = "陡峭山壁让游客害怕，但题干没有说他们已经退缩，只是心中发怵。横线处应填（　）。"
        errors = validate_application_authoring([item], {"投鼠忌器": semantic("投鼠忌器", ["顾虑伤及关联对象", "不敢行动或放弃行动"])})
        self.assertTrue(any("meta definition prompt" in error for error in errors))

    def test_rejects_batch_dominated_by_one_prompt_skeleton(self):
        values = []
        semantics = {}
        for index in range(12):
            term = f"词{index}"
            item = self.valid_application()
            item["term"] = item["answer"] = term
            item["options"] = [term, "噤若寒蝉", "畏首畏尾", "隔岸观火"]
            item["prompt"] = f"某部门处理第{index}项工作时，因为可能影响群众而暂缓行动。横线处应填（　）。"
            item["scenario_elements"] = {"subject": "某部门", "event": f"处理第{index}项工作", "constraint": "可能影响群众", "outcome": "暂缓行动"}
            semantics[term] = semantic(term, ["特定顾虑", "暂缓行动"])
            values.append(item)
        errors = validate_application_authoring(values, semantics)
        self.assertTrue(any("prompt skeleton dominates batch" in error for error in errors))

    def test_accepts_concrete_natural_scenario(self):
        self.assertEqual([], validate_application_authoring([self.valid_application()], {"投鼠忌器": semantic("投鼠忌器", ["顾虑伤及关联对象", "不敢行动或放弃行动"])}))

    def test_concise_event_is_allowed_but_vague_fragment_is_not(self):
        concise = self.valid_application()
        concise["prompt"] = "执法人员担心查封会伤及无辜商户，因此暂缓行动。横线处应填（　）。"
        vague = self.valid_application()
        vague["prompt"] = "某部门因此____。（　）"
        semantics = {"投鼠忌器": semantic("投鼠忌器", ["顾虑伤及关联对象", "不敢行动或放弃行动"])}
        self.assertEqual([], validate_application_authoring([concise], semantics))
        self.assertTrue(any("lacks a concrete event" in error for error in validate_application_authoring([vague], semantics)))

    def test_accepts_two_options_when_both_are_the_actual_confusable_pair(self):
        item = self.valid_application()
        item["options"] = ["投鼠忌器", "畏首畏尾"]
        item["distractor_rejections"] = {"畏首畏尾": "题干给出会伤及关联对象的具体顾虑，不是泛指做事胆小。"}
        semantics = {"投鼠忌器": semantic("投鼠忌器", ["顾虑伤及关联对象", "不敢行动或放弃行动"])}
        self.assertEqual([], validate_application_authoring([item], semantics))


class PreviewBundleAcceptanceV2Tests(unittest.TestCase):
    def test_self_declared_pass_cannot_replace_bound_source_reviews(self):
        bundle = {
            "schema_version": 2,
            "status": "passed_reviewed_subset",
            "basic_cards": [{"term": "甲词", "content": "内容"}],
            "comparison_cards": [],
            "application_cards": [],
            "source_review_hashes": {"semantic": "fake", "comparison": "fake", "dimension": "fake", "application": "fake"},
        }
        semantic_payload = {"semantic_review_hash": "semantic-real", "records": [semantic("甲词")]}
        comparison_payload = {"comparison_review_hash": "comparison-real", "groups": []}
        dimension_payload = {"dimension_review_hash": "dimension-real", "groups": []}
        application_payload = {"application_review_hash": "application-real", "applications": []}
        errors = validate_preview_bundle(bundle, semantic_payload, comparison_payload, dimension_payload, application_payload)
        self.assertTrue(any("source review hash mismatch" in error for error in errors))

    def test_exact_reviewed_subset_is_accepted(self):
        bundle = {
            "schema_version": 2,
            "status": "passed_reviewed_subset",
            "basic_cards": [{"term": "甲词", "content": "可学习内容"}],
            "comparison_cards": [],
            "application_cards": [],
            "source_review_hashes": {"semantic": "s", "comparison": "c", "dimension": "d", "application": "a"},
        }
        semantic_payload = {"semantic_review_hash": "s", "records": [semantic("甲词")]}
        comparison_payload = {"comparison_review_hash": "c", "groups": []}
        dimension_payload = {"dimension_review_hash": "d", "groups": []}
        application_payload = {"application_review_hash": "a", "applications": []}
        self.assertEqual([], validate_preview_bundle(bundle, semantic_payload, comparison_payload, dimension_payload, application_payload))


if __name__ == "__main__":
    unittest.main()
