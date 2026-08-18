import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]


class MethodPackageBoundaryTests(unittest.TestCase):
    def test_public_package_contains_no_project_card_artifacts(self):
        self.assertFalse((ROOT / "maimemo_learning_rebuild" / "artifacts").exists())
        self.assertFalse((ROOT / "maimemo_learning_rebuild" / "build_source_artifacts.py").exists())
        self.assertFalse((ROOT / "maimemo_learning_rebuild" / "build_semantic_registry.py").exists())

    def test_learning_example_is_explicitly_synthetic(self):
        path = (
            ROOT
            / "maimemo_learning_rebuild"
            / "examples"
            / "approved_learning_examples.json"
        )
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertIn("虚构小样本", payload["purpose"])
        self.assertEqual({"甲词", "乙词"}, {item["term"] for item in payload["records"]})

    def test_user_guide_describes_reusable_flow_without_fixed_card_count(self):
        guide = (ROOT / "docs" / "制卡方法与流程.md").read_text(encoding="utf-8")

        self.assertIn("来源清点", guide)
        self.assertIn("GitHub最终授权", guide)
        self.assertIn("全量回读", guide)
        self.assertNotIn("869", guide)


if __name__ == "__main__":
    unittest.main()
