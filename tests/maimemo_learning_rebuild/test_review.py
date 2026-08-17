import unittest
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from maimemo_learning_rebuild.review import review_registry, review_registry_precheck
from maimemo_learning_rebuild.sources import load_source_catalog


REPO_ROOT = Path(__file__).parents[2]
REVIEW_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "review" / "teacher-evidence.txt"


def fixture_catalog():
    return {
        "sources": [
            {
                "source_id": "review-teacher-fixture",
                "path": str(REVIEW_FIXTURE),
                "name": "review-teacher-fixture",
                "trust_role": "teacher_evidence",
            }
        ]
    }


def ready(term="因噎废食"):
    return {
        "term": term,
        "sense_id": f"{term}::课程义::001",
        "status": "ready",
        "source_kind": "user_directed_supplement",
        "meaning": "因害怕出问题而停止本应继续的行动。",
        "distinctive_feature": "风险恐惧触发，结果是必要行动被整体停止。",
        "dimensions": [{"axis": "动作结果", "judgment": "必要行动被停止。"}],
        "comparison_edges": [],
        "misuse_boundary": "没有停止必要行动时，不宜使用。",
        "evidence": [],
    }


class RegistryReviewTests(unittest.TestCase):
    def test_missing_independent_review_is_a_learning_quality_hard_error(self):
        report = review_registry([ready()], {"sources": []}, [])

        self.assertGreater(report["hard_errors"], 0)
        self.assertIn(
            "missing independent learning review",
            report["learning_quality_errors"],
        )

    def test_ready_group_without_reviewed_edge_contract_is_a_hard_error(self):
        group = {
            "group_id": "g-risk",
            "status": "ready",
            "minimum_differences": [
                {
                    "left": "因噎废食",
                    "right": "投鼠忌器",
                    "text": "二者含义不同。",
                }
            ],
        }
        review = {
            "complete": True,
            "reviewer_context_isolated": True,
            "resolutions": [],
            "edge_reviews": [],
            "comparison_reviews": [],
        }

        report = review_registry([], {"sources": []}, [group], review)

        self.assertGreater(report["hard_errors"], 0)
        self.assertIn(
            "comparison edge lacks reviewed contrast contract",
            report["learning_quality_errors"],
        )

    def test_review_cli_without_independent_review_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture_root = Path(temporary)
            registry_path = fixture_root / "registry.json"
            source_path = fixture_root / "sources.json"
            groups_path = fixture_root / "groups.json"
            registry_path.write_text(
                json.dumps({"records": [ready()]}, ensure_ascii=False),
                encoding="utf-8",
            )
            source_path.write_text(
                json.dumps({"sources": []}, ensure_ascii=False),
                encoding="utf-8",
            )
            groups_path.write_text(
                json.dumps({"groups": []}, ensure_ascii=False),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "maimemo_learning_rebuild.review",
                    "--registry",
                    str(registry_path),
                    "--sources",
                    str(source_path),
                    "--groups",
                    str(groups_path),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("missing independent learning review", result.stdout)

    def test_teacher_evidence_uses_independent_fixture_and_rejects_wrong_quote(self):
        item = ready("证据测试词")
        item["source_kind"] = "teacher_transcript"
        item["evidence"] = [
            {
                "source": "review-teacher-fixture",
                "location": "P0001",
                "quote": "因害怕出问题而停止本应继续的行动。",
            }
        ]

        accepted = review_registry_precheck([item], fixture_catalog(), [])
        self.assertEqual(0, accepted["missing_evidence"])
        self.assertEqual(0, accepted["hard_errors"])

        item["evidence"][0]["quote"] = "被改写的错误引文。"
        rejected = review_registry_precheck([item], fixture_catalog(), [])
        self.assertEqual(1, rejected["missing_evidence"])
        self.assertGreater(rejected["hard_errors"], 0)

    def test_quarantined_derived_content_can_never_count_as_ready(self):
        artifact_root = Path(__file__).parents[2] / "maimemo_learning_rebuild" / "artifacts"
        catalog = load_source_catalog(artifact_root / "source_catalog.json")
        item = ready("甲")
        item["provenance"] = {"derived_content_quarantined": True}

        report = review_registry_precheck([item], catalog, [])

        self.assertEqual(0, report["ready"])
        self.assertGreater(report["hard_errors"], 0)

    def test_real_registry_covers_all_current_and_missing_terms_as_reviewed(self):
        if os.environ.get("MAIMEMO_RUN_LOCAL_SOURCE_INTEGRATION") != "1":
            self.skipTest(
                "set MAIMEMO_RUN_LOCAL_SOURCE_INTEGRATION=1 to audit private source files"
            )
        artifact_root = REPO_ROOT / "maimemo_learning_rebuild" / "artifacts"
        registry = json.loads(
            (artifact_root / "master_semantic_registry.json").read_text(encoding="utf-8")
        )
        catalog = load_source_catalog(artifact_root / "source_catalog.json")
        missing_sources = [
            source["path"]
            for source in catalog.get("sources", [])
            if not Path(source["path"]).is_file()
        ]
        if missing_sources:
            self.skipTest(
                "private source files are unavailable for local integration audit: "
                + ", ".join(missing_sources[:3])
            )
        groups = json.loads(
            (artifact_root / "group_registry.json").read_text(encoding="utf-8")
        )["groups"]
        report = review_registry_precheck(registry["records"], catalog, groups)

        self.assertEqual(621, report["records"])
        self.assertEqual(621, report["ready"])
        self.assertEqual(0, report["pending"])
        self.assertEqual(0, report["hard_errors"])
        self.assertEqual(621, len({record["term"] for record in registry["records"]}))

        by_term = {record["term"]: record for record in registry["records"]}
        self.assertEqual("ready", by_term["如火如荼"]["status"])
        self.assertNotEqual("一些军队", by_term["如火如荼"]["meaning"])
        self.assertEqual("ready", by_term["述而不作"]["status"])
        self.assertIn("只阐述", by_term["述而不作"]["meaning"])
        self.assertIn("不提出", by_term["述而不作"]["meaning"])
        self.assertEqual("ready", by_term["事倍功半"]["status"])
        self.assertEqual("ready", by_term["大而化之"]["status"])
        self.assertEqual("secondary_reference", by_term["大而化之"]["source_kind"])
        self.assertEqual("ready", by_term["游刃有余"]["status"])
        self.assertEqual("ready", by_term["举足轻重"]["status"])
        lesson_five = [
            record
            for record in registry["records"]
            if record.get("provenance", {}).get("batch") == "20260108"
        ]
        self.assertEqual(146, sum(record["status"] == "ready" for record in lesson_five))
        self.assertEqual(set(), {record["term"] for record in lesson_five if record["status"] != "ready"})
        self.assertTrue(
            all(
                not record.get("provenance", {}).get("derived_content_quarantined")
                for record in lesson_five
                if record["status"] == "ready"
            )
        )
        self.assertEqual("ready", by_term["薪火相传"]["status"])
        self.assertIn("一脉相承", by_term["薪火相传"]["misuse_boundary"])
        self.assertEqual("ready", by_term["举棋不定"]["status"])
        self.assertIn("决策", by_term["举棋不定"]["distinctive_feature"])

        review_lines = (
            artifact_root / "semantic_review_log.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        self.assertEqual(621, len(review_lines))

    def test_review_reports_duplicate_keys_repeated_fields_and_generic_warning(self):
        first = ready()
        second = ready()
        second["meaning"] = second["distinctive_feature"]
        second["misuse_boundary"] = "需结合题干逻辑对应点使用，不把课堂高频用法当作固定语境。"

        report = review_registry_precheck([first, second], {"sources": []}, [])

        self.assertEqual(1, report["duplicate_keys"])
        self.assertEqual(1, report["repeated_fields"])
        self.assertEqual(1, report["generic_warnings"])
        self.assertGreater(report["hard_errors"], 0)

    def test_review_rejects_suspicious_spoken_fragments(self):
        fragments = []
        for term, meaning in (
            ("如火如荼", "一些军队"),
            ("述而不作", "是什么意思啊"),
        ):
            item = ready(term)
            item["meaning"] = meaning
            fragments.append(item)

        report = review_registry_precheck(fragments, {"sources": []}, [])

        self.assertEqual(2, report["suspicious_fragments"])
        self.assertEqual(0, report["ready"])

    def test_review_reports_unknown_comparison_members(self):
        item = ready()
        item["comparison_edges"] = [
            {"other_term": "不存在词", "minimum_difference": "两词不同。"}
        ]

        report = review_registry_precheck([item], {"sources": []}, [])

        self.assertEqual(1, report["broken_edges"])

    def test_pending_and_conflict_are_reported_not_hidden(self):
        pending = {
            "term": "待核词",
            "sense_id": "待核词::待核::001",
            "status": "pending",
            "source_kind": "historical_only",
        }
        conflict = dict(pending, term="冲突词", sense_id="冲突词::待核::001", status="conflict")

        report = review_registry_precheck([pending, conflict], {"sources": []}, [])

        self.assertEqual(1, report["pending"])
        self.assertEqual(1, report["conflict"])
        self.assertEqual(0, report["hard_errors"])


if __name__ == "__main__":
    unittest.main()
