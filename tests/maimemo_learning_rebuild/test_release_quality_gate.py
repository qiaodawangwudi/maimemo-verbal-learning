import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from maimemo_learning_rebuild.learning_quality import learning_review_hash
from maimemo_learning_rebuild.release_manifest import build_release_manifest, release_hash
from tests.maimemo_learning_rebuild.test_release_manifest import (
    artifacts as release_artifacts,
)
from tests.maimemo_learning_rebuild.test_review import ready


REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_FILENAMES = {
    "source_inventory": "source_inventory.json",
    "semantic_registry": "semantic_registry.json",
    "group_registry": "group_registry.json",
    "application_review": "application_review.json",
    "blind_review": "blind_review.json",
    "final_cards": "final_cards.json",
    "snapshot": "snapshot.json",
    "action_plan": "action_plan.json",
    "quality_reports": "quality_reports.json",
    "engine_tree": "engine_tree.bin",
    "skill_tree": "skill_tree.bin",
}


def canonical_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def independent_quality_report(semantic_raw, group_raw):
    group_payload = json.loads(group_raw.decode("utf-8"))
    edge_reviews = []
    for group in group_payload.get("groups", []):
        if group.get("status") != "ready":
            continue
        for edge in group.get("minimum_differences", []):
            required_fields = (
                "axis",
                "left_landing",
                "right_landing",
                "question_selection_condition",
            )
            if any(not isinstance(edge.get(field), str) for field in required_fields):
                continue
            edge_reviews.append(
                {
                    "subject_id": (
                        f"{group['group_id']}:{edge['left']}:{edge['right']}"
                    ),
                    "contrast_axis": edge["axis"],
                    "left_focus": edge["left_landing"],
                    "right_focus": edge["right_landing"],
                    "question_selection_condition": edge[
                        "question_selection_condition"
                    ],
                    "reviewer_context_isolated": True,
                }
            )
    independent_review = {
        "complete": True,
        "reviewer_context_isolated": True,
        "resolutions": [],
        "edge_reviews": edge_reviews,
        "semantic_registry_hash": hashlib.sha256(semantic_raw).hexdigest(),
        "group_registry_hash": hashlib.sha256(group_raw).hexdigest(),
    }
    independent_review["review_hash"] = learning_review_hash(independent_review)
    return {
        "schema_version": 2,
        "complete": True,
        "reports": [
            {"name": "public_quality_gate", "passed": True},
            {"name": "application_blind_review", "passed": True},
        ],
        "independent_review": independent_review,
    }


def write_release(release_dir, *, records=(), groups=()):
    current_artifacts = release_artifacts()
    semantic_raw = canonical_bytes({"schema_version": 1, "records": list(records)})
    group_raw = canonical_bytes({"schema_version": 1, "groups": list(groups)})
    current_artifacts["semantic_registry"] = semantic_raw
    current_artifacts["group_registry"] = group_raw
    current_artifacts["quality_reports"] = canonical_bytes(
        independent_quality_report(semantic_raw, group_raw)
    )
    manifest = build_release_manifest(
        {
            "release_id": "release-quality-test",
            "state": "draft",
            "artifacts": current_artifacts,
        }
    )
    release_dir.mkdir()
    (release_dir / "release_manifest.json").write_bytes(canonical_bytes(manifest))
    for key, raw in current_artifacts.items():
        (release_dir / ARTIFACT_FILENAMES[key]).write_bytes(raw)


def run_gate(release_dir):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "maimemo_learning_rebuild.release_quality_gate",
            "--release-dir",
            str(release_dir),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


class FrozenReleaseQualityGateTests(unittest.TestCase):
    def test_empty_but_consistent_independently_reviewed_release_passes(self):
        with tempfile.TemporaryDirectory() as temporary:
            release_dir = Path(temporary) / "release"
            write_release(release_dir)

            result = run_gate(release_dir)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_hash_consistent_near_duplicate_semantics_still_fail(self):
        record = ready("固本强基")
        record["meaning"] = "基础已经牢固，并进一步得到强化。"
        record["distinctive_feature"] = "巩固原有根基，同时强化既有基础。"
        with tempfile.TemporaryDirectory() as temporary:
            release_dir = Path(temporary) / "release"
            write_release(release_dir, records=[record])

            result = run_gate(release_dir)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("meaning and feature are near-duplicates", result.stdout)

    def test_hash_consistent_unreviewed_comparison_edge_still_fails(self):
        left = ready("因噎废食")
        right = ready("投鼠忌器")
        left["comparison_edges"] = [
            {"other_term": "投鼠忌器", "minimum_difference": "停止行动与顾忌对象不同。"}
        ]
        right["comparison_edges"] = [
            {"other_term": "因噎废食", "minimum_difference": "停止行动与顾忌对象不同。"}
        ]
        group = {
            "group_id": "g-risk",
            "status": "ready",
            "purpose": "区分风险语境",
            "members": ["因噎废食", "投鼠忌器"],
            "decision": "keep",
            "minimum_differences": [
                {
                    "left": "因噎废食",
                    "right": "投鼠忌器",
                    "text": "二词含义不同。",
                }
            ],
            "overlap_reasons": {},
        }
        with tempfile.TemporaryDirectory() as temporary:
            release_dir = Path(temporary) / "release"
            write_release(release_dir, records=[left, right], groups=[group])

            result = run_gate(release_dir)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("comparison edge lacks reviewed contrast contract", result.stdout)

    def test_changed_missing_or_nonisolated_independent_review_fails_closed(self):
        cases = (
            ("changed", False, "independent learning review hash mismatch"),
            ("nonisolated", True, "independent learning review is not context-isolated"),
            ("missing", False, "quality reports schema mismatch"),
        )
        for mutation, refresh_review_hash, expected in cases:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                release_dir = Path(temporary) / "release"
                write_release(release_dir)
                quality_path = release_dir / "quality_reports.json"
                manifest_path = release_dir / "release_manifest.json"
                quality = json.loads(quality_path.read_text(encoding="utf-8"))
                if mutation == "missing":
                    quality.pop("independent_review")
                else:
                    quality["independent_review"]["reviewer_context_isolated"] = False
                    if refresh_review_hash:
                        quality["independent_review"]["review_hash"] = (
                            learning_review_hash(quality["independent_review"])
                        )
                changed_raw = canonical_bytes(quality)
                quality_path.write_bytes(changed_raw)
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["artifact_hashes"]["quality_reports"] = hashlib.sha256(
                    changed_raw
                ).hexdigest()
                manifest["release_hash"] = release_hash(manifest)
                manifest_path.write_bytes(canonical_bytes(manifest))

                result = run_gate(release_dir)

            self.assertNotEqual(0, result.returncode)
            self.assertIn(expected, result.stdout)


if __name__ == "__main__":
    unittest.main()
