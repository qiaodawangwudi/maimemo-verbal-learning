import copy
import importlib
import math
import os
import sys
import unittest
from unittest.mock import patch

from maimemo_learning_rebuild.release_environment import (
    ReleaseEnvironment,
    open_protected_client,
    validate_github_receipt,
    validate_release_environment,
)
from maimemo_learning_rebuild.release_writer import _create_protected_client


SHA = "b" * 40
RELEASE_HASH = "a" * 64


def complete_environment():
    return {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": SHA,
        "GITHUB_RUN_ID": "12345",
        "GITHUB_ENVIRONMENT": "maimemo-final-release",
        "GITHUB_DEPLOYMENT_STATUS": "success",
        "RELEASE_HASH": RELEASE_HASH,
        "MAIMEMO_API_TOKEN": "top-secret-token",
    }


def manifest():
    return {
        "schema_version": 2,
        "release_id": "release-1",
        "release_hash": RELEASE_HASH,
        "deck": {"id": "deck-1", "name": "默认积累"},
    }


def receipt():
    return {
        "schema_version": 2,
        "receipt_type": "github_protected_release",
        "release_id": "release-1",
        "release_hash": RELEASE_HASH,
        "approved_sha": SHA,
        "github_run_id": "12345",
        "github_environment": "maimemo-final-release",
        "deployment_status": "success",
    }


class TrackingEnvironment(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reads = []

    def get(self, key, default=None):
        self.reads.append(key)
        return super().get(key, default)


class ReleaseEnvironmentTests(unittest.TestCase):
    def test_local_process_cannot_open_protected_client(self):
        env = complete_environment()
        env["GITHUB_ACTIONS"] = "false"
        with self.assertRaisesRegex(
            RuntimeError, "protected GitHub Actions environment required"
        ):
            ReleaseEnvironment.from_mapping(env)

    def test_pr_ref_cannot_authorize(self):
        env = complete_environment()
        env["GITHUB_REF"] = "refs/pull/1/merge"
        with patch.object(os, "environ", env), self.assertRaisesRegex(
            RuntimeError, "exact main ref required"
        ):
            validate_github_receipt(receipt(), manifest())

    def test_fork_pull_request_context_cannot_authorize(self):
        for field, value in (
            ("GITHUB_HEAD_REF", "feature-from-fork"),
            ("GITHUB_EVENT_NAME", "pull_request_target"),
        ):
            with self.subTest(field=field):
                env = complete_environment()
                env[field] = value
                with patch.object(os, "environ", env), self.assertRaisesRegex(
                    RuntimeError, "fork or pull request context is forbidden"
                ):
                    validate_github_receipt(receipt(), manifest())

    def test_environment_requires_exact_protected_metadata(self):
        cases = (
            ("GITHUB_RUN_ID", "0", "valid GitHub run id required"),
            ("GITHUB_ENVIRONMENT", "staging", "exact protected environment required"),
            ("GITHUB_DEPLOYMENT_STATUS", "failure", "successful protected deployment required"),
            ("RELEASE_HASH", "c" * 64, "release hash environment mismatch"),
        )
        for field, value, error in cases:
            with self.subTest(field=field):
                env = complete_environment()
                env[field] = value
                with patch.object(os, "environ", env), self.assertRaisesRegex(
                    RuntimeError, error
                ):
                    validate_github_receipt(receipt(), manifest())

    def test_receipt_binds_exact_sha_release_hash_and_run_id(self):
        cases = (
            ("approved_sha", "c" * 40, "approved SHA mismatch"),
            ("release_hash", "c" * 64, "release hash mismatch"),
            ("github_run_id", "999", "GitHub run id mismatch"),
            ("github_environment", "staging", "GitHub environment mismatch"),
            ("deployment_status", "failure", "deployment status mismatch"),
        )
        for field, value, error in cases:
            with self.subTest(field=field):
                current = receipt()
                current[field] = value
                with patch.object(os, "environ", complete_environment()), self.assertRaisesRegex(
                    RuntimeError, error
                ):
                    validate_github_receipt(current, manifest())

    def test_receipt_is_strict_json_with_one_exact_schema(self):
        malformed = (
            None,
            [],
            {**receipt(), "extra": True},
            {key: value for key, value in receipt().items() if key != "approved_sha"},
            {**receipt(), "schema_version": True},
            {**receipt(), "github_run_id": 12345},
            {**receipt(), "score": math.nan},
        )
        cyclic = receipt()
        cyclic["cycle"] = cyclic
        malformed += (cyclic,)
        for value in malformed:
            with self.subTest(value_type=type(value).__name__), patch.object(
                os, "environ", complete_environment()
            ), self.assertRaisesRegex(RuntimeError, "strict GitHub receipt required"):
                validate_github_receipt(value, manifest())

    def test_receipt_only_binds_schema_v2_manifest(self):
        for changed in (
            {**manifest(), "schema_version": 1},
            {**manifest(), "release_id": ""},
            {**manifest(), "release_hash": "not-a-digest"},
            {**manifest(), "deck": {"name": "missing id"}},
        ):
            with self.subTest(manifest=changed), patch.object(
                os, "environ", complete_environment()
            ), self.assertRaisesRegex(RuntimeError, "valid schema-v2 release manifest required"):
                validate_github_receipt(receipt(), changed)

    def test_non_secret_validation_and_module_import_do_not_read_token(self):
        env = TrackingEnvironment(complete_environment())
        with patch.object(os, "environ", env):
            imported = importlib.reload(sys.modules["maimemo_learning_rebuild.release_environment"])
            protected = imported.validate_github_receipt(receipt(), manifest())

        self.assertIsInstance(protected, imported.ReleaseEnvironment)
        self.assertNotIn("MAIMEMO_API_TOKEN", env.reads)

    def test_open_protected_client_reads_token_only_after_validation(self):
        env = TrackingEnvironment(complete_environment())
        with patch.object(os, "environ", env):
            protected = validate_github_receipt(receipt(), manifest())
            self.assertNotIn("MAIMEMO_API_TOKEN", env.reads)
            client = open_protected_client(protected)

        self.assertEqual("MAIMEMO_API_TOKEN", env.reads[-1])
        self.assertEqual("top-secret-token", client._token)
        self.assertEqual("deck-1", client.deck_id)

    def test_unvalidated_environment_cannot_trigger_token_read(self):
        env = TrackingEnvironment(complete_environment())
        unvalidated = ReleaseEnvironment.from_mapping(env)

        with self.assertRaisesRegex(RuntimeError, "validated GitHub receipt required"):
            open_protected_client(unvalidated)

        self.assertNotIn("MAIMEMO_API_TOKEN", env.reads)

    def test_task7_adapter_has_exact_strict_success_shape(self):
        approved = receipt()
        with patch.object(os, "environ", complete_environment()):
            result = validate_release_environment(manifest(), approved)

        self.assertEqual(
            {"ok", "receipt", "release_id", "release_hash", "github_run_id"},
            set(result),
        )
        self.assertIs(True, result["ok"])
        self.assertEqual(approved, result["receipt"])
        self.assertEqual("release-1", result["release_id"])
        self.assertEqual(RELEASE_HASH, result["release_hash"])
        self.assertEqual("12345", result["github_run_id"])

    def test_task7_opens_client_from_the_validated_environment_only(self):
        env = TrackingEnvironment(complete_environment())
        with patch.object(os, "environ", env):
            validation = validate_release_environment(manifest(), receipt())
            client = _create_protected_client(manifest(), validation)

        self.assertEqual("MAIMEMO_API_TOKEN", env.reads[-1])
        self.assertEqual("deck-1", client.deck_id)

    def test_inputs_are_copied_before_client_is_opened(self):
        approved = receipt()
        expected = copy.deepcopy(approved)
        env = complete_environment()
        with patch.object(os, "environ", env):
            result = validate_release_environment(manifest(), approved)
        approved["approved_sha"] = "c" * 40

        self.assertEqual(expected, result["receipt"])


if __name__ == "__main__":
    unittest.main()
