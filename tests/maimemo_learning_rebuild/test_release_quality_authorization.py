import copy
import dataclasses
import json
import os
import pickle
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from maimemo_learning_rebuild import release_quality_gate
from tests.maimemo_learning_rebuild.test_release_quality_gate import write_release


SHA = "b" * 40
WORKFLOW_REF = (
    "qiaodawangwudi/maimemo-verbal-learning/"
    ".github/workflows/maimemo-release.yml@refs/heads/main"
)


def protected_environment(release_dir):
    manifest = json.loads(
        (release_dir / "release_manifest.json").read_text(encoding="utf-8")
    )
    return {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": SHA,
        "GITHUB_RUN_ID": "12345",
        "GITHUB_ENVIRONMENT": "maimemo-final-release",
        "GITHUB_DEPLOYMENT_STATUS": "success",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_HEAD_REF": "",
        "GITHUB_BASE_REF": "",
        "GITHUB_WORKFLOW_REF": WORKFLOW_REF,
        "APPROVED_COMMIT_SHA": SHA,
        "RELEASE_HASH": manifest["release_hash"],
    }


class ProtectedQualityAuthorizationTests(unittest.TestCase):
    def test_forgeable_json_review_is_only_a_non_authorizing_precheck(self):
        with tempfile.TemporaryDirectory() as temporary:
            release_dir = Path(temporary) / "release"
            write_release(release_dir)
            self.assertEqual(
                [], release_quality_gate.evaluate_frozen_release_quality(release_dir)
            )
            runner = getattr(release_quality_gate, "run_release_quality_gate", None)
            self.assertTrue(callable(runner))

            with patch.object(os, "environ", {}):
                self.assertIn(
                    "protected current-environment review capability required",
                    runner(release_dir, None),
                )

    def test_capability_is_opaque_noncopyable_and_registry_bound(self):
        opener = getattr(
            release_quality_gate, "open_protected_quality_capability", None
        )
        runner = getattr(release_quality_gate, "run_release_quality_gate", None)
        self.assertTrue(callable(opener))
        self.assertTrue(callable(runner))
        with tempfile.TemporaryDirectory() as temporary:
            release_dir = Path(temporary) / "release"
            write_release(release_dir)
            env = protected_environment(release_dir)
            with patch.object(os, "environ", env):
                capability = opener(release_dir)
                self.assertEqual([], runner(release_dir, capability))

            self.assertFalse(hasattr(capability, "release_hash"))
            self.assertFalse(hasattr(capability, "environment"))
            for operation in (
                lambda: copy.copy(capability),
                lambda: copy.deepcopy(capability),
                lambda: pickle.dumps(capability),
                lambda: dataclasses.replace(capability),
            ):
                with self.subTest(operation=operation), self.assertRaises(
                    (TypeError, pickle.PicklingError)
                ):
                    operation()
            with self.assertRaises((TypeError, RuntimeError)):
                type(capability)()

    def test_exact_current_workflow_environment_is_required(self):
        opener = getattr(
            release_quality_gate, "open_protected_quality_capability", None
        )
        self.assertTrue(callable(opener))
        mutations = (
            ("GITHUB_ACTIONS", "false"),
            ("GITHUB_REF", "refs/pull/1/merge"),
            ("GITHUB_SHA", "c" * 40),
            ("GITHUB_RUN_ID", "0"),
            ("GITHUB_WORKFLOW_REF", "owner/repo/.github/workflows/other.yml@refs/heads/main"),
            ("GITHUB_ENVIRONMENT", "staging"),
            ("GITHUB_DEPLOYMENT_STATUS", "failure"),
            ("GITHUB_EVENT_NAME", "push"),
            ("GITHUB_HEAD_REF", "feature"),
            ("GITHUB_BASE_REF", "main"),
            ("APPROVED_COMMIT_SHA", "c" * 40),
            ("RELEASE_HASH", "c" * 64),
        )
        with tempfile.TemporaryDirectory() as temporary:
            release_dir = Path(temporary) / "release"
            write_release(release_dir)
            for field, value in mutations:
                env = protected_environment(release_dir)
                env[field] = value
                with self.subTest(field=field), patch.object(
                    os, "environ", env
                ), self.assertRaises(RuntimeError):
                    opener(release_dir)

    def test_revalidation_rejects_mapping_replacement_and_environment_drift(self):
        opener = getattr(
            release_quality_gate, "open_protected_quality_capability", None
        )
        runner = getattr(release_quality_gate, "run_release_quality_gate", None)
        self.assertTrue(callable(opener))
        self.assertTrue(callable(runner))
        with tempfile.TemporaryDirectory() as temporary:
            release_dir = Path(temporary) / "release"
            write_release(release_dir)
            original = protected_environment(release_dir)
            with patch.object(os, "environ", original):
                capability = opener(release_dir)

            replacement = dict(original)
            with patch.object(os, "environ", replacement):
                self.assertIn(
                    "protected review environment mapping changed",
                    runner(release_dir, capability),
                )

            for field, value in (
                ("GITHUB_SHA", "c" * 40),
                ("GITHUB_RUN_ID", "999"),
                ("GITHUB_DEPLOYMENT_STATUS", "failure"),
            ):
                with self.subTest(field=field):
                    original[field] = value
                    with patch.object(os, "environ", original):
                        self.assertNotEqual([], runner(release_dir, capability))
                    original = protected_environment(release_dir)
                    with patch.object(os, "environ", original):
                        capability = opener(release_dir)

    def test_environment_toctou_during_quality_recheck_fails_closed(self):
        opener = getattr(
            release_quality_gate, "open_protected_quality_capability", None
        )
        runner = getattr(release_quality_gate, "run_release_quality_gate", None)
        self.assertTrue(callable(opener))
        self.assertTrue(callable(runner))
        with tempfile.TemporaryDirectory() as temporary:
            release_dir = Path(temporary) / "release"
            write_release(release_dir)
            env = protected_environment(release_dir)
            with patch.object(os, "environ", env):
                capability = opener(release_dir)
                real_evaluate = release_quality_gate.evaluate_frozen_release_quality

                def mutate_during_recheck(path):
                    result = real_evaluate(path)
                    env["GITHUB_RUN_ID"] = "999"
                    return result

                with patch.object(
                    release_quality_gate,
                    "evaluate_frozen_release_quality",
                    side_effect=mutate_during_recheck,
                ):
                    self.assertNotEqual([], runner(release_dir, capability))


if __name__ == "__main__":
    unittest.main()
