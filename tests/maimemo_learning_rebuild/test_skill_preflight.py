import importlib.util
import unittest
from pathlib import Path


SKILL_ROOT = Path.home() / ".codex" / "skills" / "verbal-maimemo-cards"
SPEC = importlib.util.spec_from_file_location(
    "verbal_maimemo_preflight", SKILL_ROOT / "scripts" / "preflight.py"
)
PREFLIGHT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PREFLIGHT)


def complete_manifest():
    return {
        "records": [
            {
                "term": "甲",
                "sense_id": "甲::课程义::001",
                "status": "ready",
                "meaning": "甲的词义。",
                "distinctive_feature": "甲的独特落点。",
                "dimensions": [],
                "comparison_edges": [],
                "misuse_boundary": "缺少必要条件时不使用。",
            }
        ],
        "groups": [],
        "cards": [
            {
                "title": "基础词义｜甲",
                "content": "【词义】甲的词义。【特别之处】甲的独特落点。【做题识别点】线索。【一眼辨析】暂无。",
                "references": [],
            }
        ],
        "target_chapter": {"id": "chapter", "name": "默认积累"},
        "full_library_audit": {"complete": True, "snapshot_total": 730},
        "plan": {
            "plan_hash": "hash",
            "snapshot_hash": "snapshot",
            "action_counts": {"update": 1},
            "manual_review": 0,
        },
        "approval": {
            "chapter_id": "chapter",
            "plan_hash": "hash",
            "action_counts": {"update": 1},
        },
    }


class ReusableSkillPreflightTests(unittest.TestCase):
    def test_rejects_repeated_learning_fields(self):
        manifest = complete_manifest()
        manifest["records"][0]["distinctive_feature"] = manifest["records"][0]["meaning"]

        self.assertIn(
            "meaning equals distinctive_feature: 甲", PREFLIGHT.validate(manifest)
        )

    def test_rejects_missing_hash_bound_approval(self):
        manifest = complete_manifest()
        manifest.pop("approval")

        self.assertIn("write approval missing", PREFLIGHT.validate(manifest))

    def test_skill_declares_learning_first_layered_contract(self):
        text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        for phrase in ("学习效果", "特别之处", "做题识别点", "冻结计划哈希", "全库"):
            self.assertIn(phrase, text)
        self.assertNotIn("不设机械的“特别之处”栏目", text)


if __name__ == "__main__":
    unittest.main()
