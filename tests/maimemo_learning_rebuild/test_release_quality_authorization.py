import copy
import dataclasses
import json
import os
import pickle
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from maimemo_learning_rebuild import release_environment, release_quality_gate
from maimemo_learning_rebuild.guard import GuardResult
from maimemo_learning_rebuild.release_manifest import load_release_manifest_file
from maimemo_learning_rebuild.release_writer import _create_protected_client
from tests.maimemo_learning_rebuild.test_release_environment import TrackingEnvironment
from tests.maimemo_learning_rebuild.test_release_quality_gate import write_release
from tests.maimemo_learning_rebuild.test_release_manifest import (
    STATE_SEQUENCE,
    advance_release,
    canonical_bytes,
    frozen_baseline,
)


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
        "MAIMEMO_API_TOKEN": "tracking-only-test-token",
    }


def protected_receipt(manifest):
    return {
        "schema_version": 2,
        "receipt_type": "github_protected_release",
        "release_id": manifest["release_id"],
        "release_hash": manifest["release_hash"],
        "approved_sha": SHA,
        "github_run_id": "12345",
        "github_environment": "maimemo-final-release",
        "deployment_status": "success",
    }


def authorize_release(release_dir):
    manifest_path = release_dir / "release_manifest.json"
    manifest = load_release_manifest_file(manifest_path)
    baseline = frozen_baseline(manifest)
    for state in STATE_SEQUENCE[1 : STATE_SEQUENCE.index("authorized") + 1]:
        manifest = advance_release(manifest, state, baseline)
    manifest_path.write_bytes(canonical_bytes(manifest))
    return load_release_manifest_file(manifest_path)


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
                real_evaluate = release_quality_gate._evaluate_sealed_release_quality

                def mutate_during_recheck(path):
                    result = real_evaluate(path)
                    env["GITHUB_RUN_ID"] = "999"
                    return result

                with patch.object(
                    release_quality_gate,
                    "_evaluate_sealed_release_quality",
                    side_effect=mutate_during_recheck,
                ):
                    self.assertNotEqual([], runner(release_dir, capability))

    def test_final_quality_handoff_sha_drift_blocks_before_token_lookup(self):
        with tempfile.TemporaryDirectory() as temporary:
            release_dir = Path(temporary) / "release"
            write_release(release_dir)
            manifest = authorize_release(release_dir)
            env = TrackingEnvironment(protected_environment(release_dir))
            with patch.object(os, "environ", env):
                quality_capability = (
                    release_quality_gate.open_protected_quality_capability(release_dir)
                )
                validation = release_environment.validate_release_environment(
                    manifest, protected_receipt(manifest)
                )
                real_consume = release_quality_gate._consume_protected_quality_release
                handoff_reached = []

                def mutate_after_real_read(*args, **kwargs):
                    result = real_consume(*args, **kwargs)
                    handoff_reached.append(True)
                    env["APPROVED_COMMIT_SHA"] = "c" * 40
                    return result

                with patch.object(
                    release_quality_gate,
                    "_consume_protected_quality_release",
                    side_effect=mutate_after_real_read,
                ), self.assertRaises(RuntimeError):
                    _create_protected_client(
                        manifest, validation, quality_capability
                    )

            self.assertEqual(0, env.reads.count("MAIMEMO_API_TOKEN"))
            self.assertEqual([True], handoff_reached)

    def test_final_quality_handoff_artifact_drift_blocks_before_token_lookup(self):
        with tempfile.TemporaryDirectory() as temporary:
            release_dir = Path(temporary) / "release"
            write_release(release_dir)
            manifest = authorize_release(release_dir)
            env = TrackingEnvironment(protected_environment(release_dir))
            engine_path = release_dir / "engine_tree.bin"
            with patch.object(os, "environ", env):
                quality_capability = (
                    release_quality_gate.open_protected_quality_capability(release_dir)
                )
                validation = release_environment.validate_release_environment(
                    manifest, protected_receipt(manifest)
                )
                real_consume = release_quality_gate._consume_protected_quality_release
                handoff_reached = []

                def mutate_after_real_read(*args, **kwargs):
                    result = real_consume(*args, **kwargs)
                    handoff_reached.append(True)
                    engine_path.write_bytes(engine_path.read_bytes() + b"x")
                    return result

                with patch.object(
                    release_quality_gate,
                    "_consume_protected_quality_release",
                    side_effect=mutate_after_real_read,
                ), self.assertRaises(RuntimeError):
                    _create_protected_client(
                        manifest, validation, quality_capability
                    )

            self.assertEqual(0, env.reads.count("MAIMEMO_API_TOKEN"))
            self.assertEqual([True], handoff_reached)

    def test_same_byte_path_replacements_are_rejected_before_token_lookup(self):
        targets = ("release_manifest.json", "engine_tree.bin", "final_cards.json")
        for target_name in targets:
            with self.subTest(target=target_name), tempfile.TemporaryDirectory() as temporary:
                release_dir = Path(temporary) / "release"
                write_release(release_dir)
                manifest = authorize_release(release_dir)
                env = TrackingEnvironment(protected_environment(release_dir))
                with patch.object(os, "environ", env):
                    quality_capability = (
                        release_quality_gate.open_protected_quality_capability(
                            release_dir
                        )
                    )
                    validation = release_environment.validate_release_environment(
                        manifest, protected_receipt(manifest)
                    )
                    target = release_dir / target_name
                    replacement = release_dir / f"replacement-{target_name}"
                    replacement.write_bytes(target.read_bytes())
                    replacement.replace(target)
                    with self.assertRaisesRegex(RuntimeError, "path changed"):
                        _create_protected_client(
                            manifest,
                            validation,
                            quality_capability,
                            release_dir,
                        )

                self.assertEqual(0, env.reads.count("MAIMEMO_API_TOKEN"))

    def test_environment_mapping_handoff_replacement_blocks_before_token_lookup(self):
        with tempfile.TemporaryDirectory() as temporary:
            release_dir = Path(temporary) / "release"
            write_release(release_dir)
            manifest = authorize_release(release_dir)
            original = TrackingEnvironment(protected_environment(release_dir))
            replacement = TrackingEnvironment(protected_environment(release_dir))
            with patch.object(os, "environ", original):
                quality_capability = (
                    release_quality_gate.open_protected_quality_capability(release_dir)
                )
                validation = release_environment.validate_release_environment(
                    manifest, protected_receipt(manifest)
                )
                real_consume = release_quality_gate._consume_protected_quality_release

                def replace_mapping_after_consume(*args, **kwargs):
                    result = real_consume(*args, **kwargs)
                    os.environ = replacement
                    return result

                try:
                    with patch.object(
                        release_quality_gate,
                        "_consume_protected_quality_release",
                        side_effect=replace_mapping_after_consume,
                    ), self.assertRaises(RuntimeError):
                        _create_protected_client(
                            manifest,
                            validation,
                            quality_capability,
                            release_dir,
                        )
                finally:
                    os.environ = original

            self.assertEqual(0, original.reads.count("MAIMEMO_API_TOKEN"))
            self.assertEqual(0, replacement.reads.count("MAIMEMO_API_TOKEN"))

    def test_quality_environment_drift_during_token_lookup_discards_client(self):
        class DriftOnTokenEnvironment(TrackingEnvironment):
            def get(self, key, default=None):
                value = super().get(key, default)
                if key == "MAIMEMO_API_TOKEN":
                    self["APPROVED_COMMIT_SHA"] = "c" * 40
                return value

        with tempfile.TemporaryDirectory() as temporary:
            release_dir = Path(temporary) / "release"
            write_release(release_dir)
            manifest = authorize_release(release_dir)
            env = DriftOnTokenEnvironment(protected_environment(release_dir))
            with patch.object(os, "environ", env):
                quality_capability = (
                    release_quality_gate.open_protected_quality_capability(release_dir)
                )
                validation = release_environment.validate_release_environment(
                    manifest, protected_receipt(manifest)
                )
                with self.assertRaisesRegex(RuntimeError, "\[REDACTED\]"):
                    _create_protected_client(
                        manifest,
                        validation,
                        quality_capability,
                        release_dir,
                    )

            self.assertEqual(1, env.reads.count("MAIMEMO_API_TOKEN"))

    def test_sealed_snapshot_registry_tampering_is_detected(self):
        with tempfile.TemporaryDirectory() as temporary:
            release_dir = Path(temporary) / "release"
            write_release(release_dir)
            env = protected_environment(release_dir)
            with patch.object(os, "environ", env):
                capability = release_quality_gate.open_protected_quality_capability(
                    release_dir
                )
                binding = release_quality_gate._QUALITY_CAPABILITIES[capability]
                with self.assertRaises(AttributeError):
                    binding.sealed_snapshot.manifest_bytes = b"attacker"
                changed_snapshot = binding.sealed_snapshot._replace(
                    manifest_bytes=binding.sealed_snapshot.manifest_bytes + b" "
                )
                release_quality_gate._QUALITY_CAPABILITIES[capability] = binding._replace(
                    sealed_snapshot=changed_snapshot
                )
                self.assertIn(
                    "sealed protected review snapshot changed",
                    release_quality_gate.run_release_quality_gate(
                        release_dir, capability
                    ),
                )

    def test_sealed_execution_payload_mutation_during_token_lookup_is_redacted(self):
        class MutatingTokenEnvironment(TrackingEnvironment):
            mutation = None

            def get(self, key, default=None):
                value = super().get(key, default)
                if key == "MAIMEMO_API_TOKEN" and self.mutation is not None:
                    self.mutation()
                return value

        with tempfile.TemporaryDirectory() as temporary:
            release_dir = Path(temporary) / "release"
            write_release(release_dir)
            manifest = authorize_release(release_dir)
            env = MutatingTokenEnvironment(protected_environment(release_dir))
            with patch.object(os, "environ", env):
                quality_capability = (
                    release_quality_gate.open_protected_quality_capability(release_dir)
                )
                validation = release_environment.validate_release_environment(
                    manifest, protected_receipt(manifest)
                )
                real_consume = release_quality_gate._consume_protected_quality_release

                def expose_then_mutate(*args, **kwargs):
                    result = real_consume(*args, **kwargs)
                    cards = result[2]
                    env.mutation = lambda: cards[0].__setitem__("title", "tampered")
                    return result

                with patch.object(
                    release_quality_gate,
                    "_consume_protected_quality_release",
                    side_effect=expose_then_mutate,
                ), self.assertRaisesRegex(RuntimeError, "\[REDACTED\]"):
                    _create_protected_client(
                        manifest,
                        validation,
                        quality_capability,
                        release_dir,
                    )

            self.assertEqual(1, env.reads.count("MAIMEMO_API_TOKEN"))

    def test_client_revalidates_sealed_paths_before_every_post(self):
        with tempfile.TemporaryDirectory() as temporary:
            release_dir = Path(temporary) / "release"
            write_release(release_dir)
            manifest = authorize_release(release_dir)
            env = TrackingEnvironment(protected_environment(release_dir))
            with patch.object(os, "environ", env):
                quality_capability = (
                    release_quality_gate.open_protected_quality_capability(release_dir)
                )
                validation = release_environment.validate_release_environment(
                    manifest, protected_receipt(manifest)
                )
                client, sealed_manifest, sealed_cards = _create_protected_client(
                    manifest,
                    validation,
                    quality_capability,
                    release_dir,
                    include_sealed_release=True,
                )
                self.assertFalse(hasattr(client, "_client"))
                for operation in (
                    lambda: copy.copy(client),
                    lambda: copy.deepcopy(client),
                    lambda: pickle.dumps(client),
                ):
                    with self.assertRaises((TypeError, pickle.PicklingError)):
                        operation()
                original_title = sealed_cards[0]["title"]
                engine_path = release_dir / "engine_tree.bin"
                engine_path.write_bytes(engine_path.read_bytes() + b"drift")
                self.assertEqual(manifest["release_hash"], sealed_manifest["release_hash"])
                self.assertEqual(original_title, sealed_cards[0]["title"])
                with self.assertRaisesRegex(RuntimeError, "path changed"):
                    client.create_card(
                        "chapter-test",
                        "test content",
                        GuardResult(True, (), "plan", "review"),
                    )

            self.assertEqual(1, env.reads.count("MAIMEMO_API_TOKEN"))


if __name__ == "__main__":
    unittest.main()
