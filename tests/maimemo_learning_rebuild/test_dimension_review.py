import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from maimemo_learning_rebuild.dimension_review import (
    dimension_review_hash,
    validate_dimension_review,
)


def value_hash(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def records_for(number=4):
    records = {}
    left_cues = ["政策对象", "人物身份", "时间阶段", "空间地域"]
    right_cues = ["制度范围", "群体角色", "发展时期", "场所边界"]
    for index in range(number):
        left = f"甲{index}"
        right = f"乙{index}"
        for term, cue in ((left, left_cues[index]), (right, right_cues[index])):
            records[term] = {
                "term": term,
                "sense_id": f"sense-{term}",
                "meaning": f"{term}的完整词义，强调{cue}。",
                "core_discrimination": f"条件{term} + 结果{term}",
                "recognition_cues": [cue],
                "misuse_boundary": f"缺少{cue}时不能使用{term}。",
            }
    return records


def groups_for(number=4):
    return [
        {"group_id": f"g{index}", "members": [f"甲{index}", f"乙{index}"]}
        for index in range(number)
    ]


def approved_entry(group, records, *, axes=("适用对象", "程度范围"), varied=True):
    members = group["members"]
    dimensions = []
    for axis_index, axis in enumerate(axes):
        judgments = {}
        evidence = {}
        for member_index, term in enumerate(members):
            cue = records[term]["recognition_cues"][0]
            judgments[term] = (
                f"{term}在{axis}上对应{cue}，用于组{group['group_id']}的判断。"
                if varied
                else f"{term}在{axis}上对应固定模板。"
            )
            evidence[term] = [
                {
                    "field": "recognition_cues",
                    "value_hash": value_hash(records[term]["recognition_cues"]),
                    "excerpt": cue,
                }
            ]
        dimensions.append(
            {
                "axis": axis,
                "question": f"题干在{axis}上如何区分{'、'.join(members)}？",
                "judgments": judgments,
                "evidence": evidence,
                "selection_change_test": {
                    "condition": f"只改变{axis}条件",
                    "when_true": members[0],
                    "when_false": members[1],
                },
                "independence_reason": f"{axis}提供核心关键词之外的独立选择信息。",
            }
        )
    return {
        "group_id": group["group_id"],
        "members": members,
        "disposition": "approved_dimensions",
        "dimensions": dimensions,
        "checked_candidate_axes": list(axes),
        "insufficiency_reason": "",
    }


def artifact(entries):
    value = {
        "schema_version": 1,
        "status": "passed",
        "review_mode": "evidence_bound_group_review",
        "groups": entries,
    }
    value["review_hash"] = dimension_review_hash(value)
    return value


class DimensionReviewTests(unittest.TestCase):
    def test_accepts_group_dispositions_with_real_approved_dimensions(self):
        records = records_for(2)
        groups = groups_for(2)
        entries = [approved_entry(groups[0], records)]
        entries.append(
            {
                "group_id": groups[1]["group_id"],
                "members": groups[1]["members"],
                "disposition": "insufficient_dimensions",
                "dimensions": [],
                "checked_candidate_axes": ["适用对象", "程度范围"],
                "insufficiency_reason": "现有证据只能支持一个新增选择轴，第二轴会重复核心辨析。",
            }
        )
        review = artifact(entries)

        self.assertEqual([], validate_dimension_review(groups, records, review))

    def test_rejects_missing_dispositions_and_blanket_deletion(self):
        records = records_for(3)
        groups = groups_for(3)
        insufficient = [
            {
                "group_id": group["group_id"],
                "members": group["members"],
                "disposition": "insufficient_dimensions",
                "dimensions": [],
                "checked_candidate_axes": ["适用对象", "程度范围"],
                "insufficiency_reason": "逐组检查后只有一个新增选择轴。",
            }
            for group in groups
        ]

        errors = validate_dimension_review(groups, records, artifact(insufficient))
        self.assertTrue(any("blanket dimension deletion" in error for error in errors))

        missing = artifact(insufficient[:-1])
        errors = validate_dimension_review(groups, records, missing)
        self.assertTrue(any("missing group disposition" in error for error in errors))

    def test_rejects_fixed_axis_pair_with_repeated_judgment_skeleton(self):
        records = records_for(4)
        groups = groups_for(4)
        entries = [approved_entry(group, records, varied=False) for group in groups]

        errors = validate_dimension_review(groups, records, artifact(entries))

        self.assertTrue(any("homogeneous dimension template" in error for error in errors))

    def test_repeated_axis_names_are_allowed_when_group_judgments_are_distinct(self):
        records = records_for(4)
        groups = groups_for(4)
        entries = [approved_entry(group, records, varied=True) for group in groups]

        self.assertEqual([], validate_dimension_review(groups, records, artifact(entries)))

    def test_rejects_core_copy_bad_evidence_and_fake_axis_renaming(self):
        records = records_for(1)
        groups = groups_for(1)
        entry = approved_entry(groups[0], records)
        first = entry["dimensions"][0]
        first["judgments"]["甲0"] = f"甲0：{records['甲0']['core_discrimination']}"
        first["evidence"]["乙0"][0]["value_hash"] = "0" * 64
        entry["dimensions"][1]["axis"] = "适用对象（补充）"

        errors = validate_dimension_review(groups, records, artifact([entry]))

        self.assertTrue(any("copies core" in error for error in errors))
        self.assertTrue(any("evidence hash mismatch" in error for error in errors))
        self.assertTrue(any("duplicate semantic axis" in error for error in errors))

    def test_hash_binds_every_review_field(self):
        records = records_for(1)
        groups = groups_for(1)
        review = artifact([approved_entry(groups[0], records)])
        changed = copy.deepcopy(review)
        changed["groups"][0]["dimensions"][0]["question"] += "变化"

        self.assertNotEqual(review["review_hash"], dimension_review_hash(changed))

    def test_cli_blocks_invalid_review_and_passes_valid_review(self):
        records = records_for(1)
        groups = groups_for(1)
        review = artifact([approved_entry(groups[0], records)])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, value in (("groups.json", groups), ("records.json", records), ("review.json", review)):
                (root / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            command = [
                sys.executable,
                "-m",
                "maimemo_learning_rebuild.dimension_review",
                "--groups", str(root / "groups.json"),
                "--records", str(root / "records.json"),
                "--review", str(root / "review.json"),
            ]
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stderr)
            changed = copy.deepcopy(review)
            changed["groups"][0]["dimensions"][0]["axis"] = "选择落点"
            changed["review_hash"] = dimension_review_hash(changed)
            (root / "review.json").write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("non-dimension axis", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
