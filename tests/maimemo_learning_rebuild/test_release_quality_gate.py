import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from maimemo_learning_rebuild.learning_quality import learning_review_hash
from maimemo_learning_rebuild.release_manifest import build_release_manifest, release_hash
from maimemo_learning_rebuild.render import render_comparison_card
from maimemo_learning_rebuild.release_quality_gate import (
    _frozen_comparison_review_errors,
)
from tests.maimemo_learning_rebuild.test_release_manifest import (
    artifacts as release_artifacts,
)
from tests.maimemo_learning_rebuild.test_review import ready
from tests.maimemo_learning_rebuild.test_learning_quality import empty_review


REPO_ROOT = Path(__file__).resolve().parents[2]
EXTERNAL_COMPARISON_REVIEW = REPO_ROOT / "tests" / "fixtures" / "release" / (
    "independent_comparison_review.json"
)
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


def independent_quality_report(semantic_raw, group_raw, external_review=None):
    independent_review = copy.deepcopy(external_review or empty_review())
    independent_review["semantic_registry_hash"] = hashlib.sha256(
        semantic_raw
    ).hexdigest()
    independent_review["group_registry_hash"] = hashlib.sha256(group_raw).hexdigest()
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


def write_release(
    release_dir,
    *,
    records=(),
    groups=(),
    external_review=None,
    final_comparison_content=None,
):
    current_artifacts = release_artifacts()
    if not (external_review or {}).get("comparison_reviews"):
        final_payload = json.loads(current_artifacts["final_cards"].decode("utf-8"))
        final_payload["cards"] = [
            card
            for card in final_payload["cards"]
            if card.get("card_type") != "comparison"
        ]
        final_payload["totals"]["rendered"] -= 1
        final_payload["totals"]["by_type"]["comparison"] = 0
        current_artifacts["final_cards"] = canonical_bytes(final_payload)

        action_plan = json.loads(current_artifacts["action_plan"].decode("utf-8"))
        action_plan["actions"] = [
            action
            for action in action_plan["actions"]
            if action.get("card_type") != "comparison"
        ]
        action_plan["route_counts"]["comparison"] = {
            "before": 0,
            "create": 0,
            "update": 0,
            "unchanged": 0,
            "after": 0,
        }
        action_plan["action_counts"]["create"] -= 1
        current_artifacts["action_plan"] = canonical_bytes(action_plan)
    elif final_comparison_content is not None:
        final_payload = json.loads(current_artifacts["final_cards"].decode("utf-8"))
        comparison = next(
            card
            for card in final_payload["cards"]
            if card.get("card_type") == "comparison"
        )
        comparison["content"] = final_comparison_content
        current_artifacts["final_cards"] = canonical_bytes(final_payload)
        action_plan = json.loads(current_artifacts["action_plan"].decode("utf-8"))
        comparison_action = next(
            action
            for action in action_plan["actions"]
            if action.get("card_type") == "comparison"
        )
        comparison_action["content_hash"] = hashlib.sha256(
            final_comparison_content.encode("utf-8")
        ).hexdigest()
        current_artifacts["action_plan"] = canonical_bytes(action_plan)
    semantic_raw = canonical_bytes({"schema_version": 1, "records": list(records)})
    group_raw = canonical_bytes({"schema_version": 1, "groups": list(groups)})
    current_artifacts["semantic_registry"] = semantic_raw
    current_artifacts["group_registry"] = group_raw
    current_artifacts["quality_reports"] = canonical_bytes(
        independent_quality_report(semantic_raw, group_raw, external_review)
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
    def test_reviewed_group_must_match_exact_frozen_comparison_card(self):
        left = ready("甲")
        left["meaning"] = "因小风险放弃必要行动。"
        left["distinctive_feature"] = "必要行动被整体停止。"
        left["registry_order"] = 1
        right = ready("乙")
        right["meaning"] = "因顾忌而避免牵连对象。"
        right["distinctive_feature"] = "顾忌点落在可能牵连的对象。"
        right["registry_order"] = 2
        group = {
            "group_id": "g-final-binding",
            "title": "近义辨析｜甲、乙",
            "status": "ready",
            "purpose": "区分行动结果与顾忌对象",
            "members": ["甲", "乙"],
            "decision": "keep",
            "minimum_differences": [
                {
                    "left": "甲",
                    "right": "乙",
                    "text": (
                        "甲看必要行动被整体停止；乙看顾忌点落在可能牵连的对象；"
                        "甲落点：必要行动被整体停止；"
                        "乙落点：顾忌点落在可能牵连的对象；"
                        "题干强调必要行动被整体停止选甲；"
                        "强调顾忌点落在可能牵连的对象选乙"
                    ),
                    "shared_basis": "面对风险时是否继续行动",
                    "axis": "甲看必要行动被整体停止；乙看顾忌点落在可能牵连的对象",
                    "left_landing": "甲落点：必要行动被整体停止",
                    "right_landing": "乙落点：顾忌点落在可能牵连的对象",
                    "question_selection_condition": (
                        "题干强调必要行动被整体停止选甲；"
                        "强调顾忌点落在可能牵连的对象选乙"
                    ),
                    "evidence_ids": ["ev-left", "ev-right"],
                    "review_status": "pass",
                }
            ],
            "overlap_reasons": {},
        }
        with tempfile.TemporaryDirectory() as temporary:
            release_dir = Path(temporary) / "release"
            external_review = json.loads(
                EXTERNAL_COMPARISON_REVIEW.read_text(encoding="utf-8")
            )
            reviewed_content = render_comparison_card(group, [left, right])
            write_release(
                release_dir,
                records=[left, right],
                groups=[group],
                external_review=external_review,
                final_comparison_content=reviewed_content,
            )

            valid_result = run_gate(release_dir)
            self.assertEqual(
                0, valid_result.returncode, valid_result.stdout + valid_result.stderr
            )

            valid_cards = json.loads(
                (release_dir / "final_cards.json").read_text(encoding="utf-8")
            )["cards"]
            valid_manifest = json.loads(
                (release_dir / "release_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                [],
                _frozen_comparison_review_errors(
                    valid_cards, valid_manifest, external_review
                ),
            )
            missing = {**external_review, "comparison_reviews": []}
            self.assertIn(
                "frozen comparison missing independent review: comparison:甲、乙",
                _frozen_comparison_review_errors(
                    valid_cards, valid_manifest, missing
                ),
            )
            duplicate = copy.deepcopy(external_review)
            duplicate["comparison_reviews"].append(
                copy.deepcopy(duplicate["comparison_reviews"][0])
            )
            self.assertIn(
                "frozen comparison missing independent review: comparison:甲、乙",
                _frozen_comparison_review_errors(
                    valid_cards, valid_manifest, duplicate
                ),
            )
            orphan = copy.deepcopy(external_review)
            orphan_review = copy.deepcopy(orphan["comparison_reviews"][0])
            orphan_review["stable_card_key"] = "comparison:孤立审查"
            orphan["comparison_reviews"].append(orphan_review)
            self.assertIn(
                "independent comparison review has no frozen card: comparison:孤立审查",
                _frozen_comparison_review_errors(valid_cards, valid_manifest, orphan),
            )

            final_path = release_dir / "final_cards.json"
            action_path = release_dir / "action_plan.json"
            manifest_path = release_dir / "release_manifest.json"
            final_payload = json.loads(final_path.read_text(encoding="utf-8"))
            comparison = next(
                card
                for card in final_payload["cards"]
                if card["card_type"] == "comparison"
            )
            comparison["content"] = "attacker replacement comparison"
            changed_final_raw = canonical_bytes(final_payload)
            final_path.write_bytes(changed_final_raw)

            action_plan = json.loads(action_path.read_text(encoding="utf-8"))
            comparison_action = next(
                action
                for action in action_plan["actions"]
                if action["card_type"] == "comparison"
            )
            comparison_action["content_hash"] = hashlib.sha256(
                comparison["content"].encode("utf-8")
            ).hexdigest()
            changed_action_raw = canonical_bytes(action_plan)
            action_path.write_bytes(changed_action_raw)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifact_hashes"]["final_cards"] = hashlib.sha256(
                changed_final_raw
            ).hexdigest()
            manifest["artifact_hashes"]["action_plan"] = hashlib.sha256(
                changed_action_raw
            ).hexdigest()
            manifest["release_hash"] = release_hash(manifest)
            manifest_path.write_bytes(canonical_bytes(manifest))

            result = run_gate(release_dir)

        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "reviewed comparison output mismatch: comparison:甲、乙",
            result.stdout,
        )

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
