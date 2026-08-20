import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "verbal-maimemo-cards"


class ReusableSkillPreflightTests(unittest.TestCase):
    def read_skill(self):
        skill_path = SKILL_ROOT / "SKILL.md"
        self.assertTrue(skill_path.is_file(), f"repository Skill absent: {skill_path}")
        return skill_path.read_text(encoding="utf-8")

    def test_skill_links_every_protected_release_reference_directly(self):
        text = self.read_skill()

        for filename in (
            "artifact-contracts.md",
            "learning-quality-rubric.md",
            "release-state-machine.md",
            "source-and-privacy-policy.md",
        ):
            self.assertIn(f"](references/{filename})", text)

    def test_skill_declares_protected_release_invariants(self):
        text = self.read_skill()

        for phrase in (
            "不得存在本地备用写入路径",
            "发布哈希变化后旧授权失效",
            "写入器不得生成内容",
        ):
            self.assertIn(phrase, text)

    def test_skill_declares_learning_first_layered_contract(self):
        text = self.read_skill()

        for phrase in (
            "学习效果",
            "核心辨析 -> 词义 -> 一眼辨析 -> 多维判断",
            "附加｜题干可圈出",
            "不得替代",
            "整批为零",
            "独立维度审查",
            "高度同质化",
            "全部删除",
            "一个判断只出现一次",
            "一眼辨析",
            "多维判断",
            "冻结卡片",
            "全量回读",
        ):
            self.assertIn(phrase, text)
        self.assertNotIn("词义 -> 特别之处 -> 做题识别点", text)


if __name__ == "__main__":
    unittest.main()
