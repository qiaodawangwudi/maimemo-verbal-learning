import copy
import dataclasses
import importlib
import math
import os
import pickle
import sys
import traceback
import unittest
from unittest.mock import patch

from maimemo_learning_rebuild.release_environment import (
    ReleaseEnvironment,
    open_protected_client,
    validate_github_receipt,
    validate_release_environment,
)
from maimemo_learning_rebuild.release_writer import _create_protected_client
from tests.maimemo_learning_rebuild.test_release_manifest import release_at


SHA = "b" * 40


def complete_environment(current_manifest=None):
    current_manifest = current_manifest or manifest()
    return {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": SHA,
        "GITHUB_RUN_ID": "12345",
        "GITHUB_ENVIRONMENT": "maimemo-final-release",
        "GITHUB_DEPLOYMENT_STATUS": "success",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "RELEASE_HASH": current_manifest["release_hash"],
        "MAIMEMO_API_TOKEN": "top-secret-token",
    }


def manifest():
    return release_at("authorized")[0]


def receipt(current_manifest=None):
    current_manifest = current_manifest or manifest()
    return {
        "schema_version": 2,
        "receipt_type": "github_protected_release",
        "release_id": current_manifest["release_id"],
        "release_hash": current_manifest["release_hash"],
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


class ExplodingTokenEnvironment(TrackingEnvironment):
    def get(self, key, default=None):
        self.reads.append(key)
        if key == "MAIMEMO_API_TOKEN":
            raise RuntimeError("lookup leaked top-secret-token")
        return dict.get(self, key, default)


class ForgedValidation(dict):
    pass


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
                    RuntimeError, "workflow_dispatch release context required"
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
            ("github_environment", "staging", "strict GitHub receipt required"),
            ("deployment_status", "failure", "strict GitHub receipt required"),
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
            ), self.assertRaisesRegex(
                RuntimeError, "validated authorized schema-v2 release manifest required"
            ):
                validate_github_receipt(receipt(), changed)

    def test_non_secret_validation_and_module_import_do_not_read_token(self):
        env = TrackingEnvironment(complete_environment())
        with patch.object(os, "environ", env):
            imported = importlib.reload(sys.modules["maimemo_learning_rebuild.release_environment"])
            protected = imported.validate_github_receipt(receipt(), manifest())

        self.assertEqual("_ReleaseCapability", type(protected).__name__)
        self.assertNotIn("MAIMEMO_API_TOKEN", env.reads)

    def test_open_protected_client_reads_token_only_after_validation(self):
        env = TrackingEnvironment(complete_environment())
        with patch.object(os, "environ", env):
            protected = validate_github_receipt(receipt(), manifest())
            self.assertNotIn("MAIMEMO_API_TOKEN", env.reads)
            client = open_protected_client(protected)

        self.assertEqual("MAIMEMO_API_TOKEN", env.reads[-1])
        self.assertEqual(1, env.reads.count("MAIMEMO_API_TOKEN"))
        self.assertEqual("top-secret-token", client._token)
        self.assertEqual(manifest()["deck"]["id"], client.deck_id)

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
        self.assertEqual(manifest()["release_id"], result["release_id"])
        self.assertEqual(manifest()["release_hash"], result["release_hash"])
        self.assertEqual("12345", result["github_run_id"])

    def test_task7_opens_client_from_the_validated_environment_only(self):
        env = TrackingEnvironment(complete_environment())
        with patch.object(os, "environ", env), patch(
            "maimemo_learning_rebuild.release_quality_gate."
            "_revalidate_protected_quality_capability",
            return_value=None,
        ):
            validation = validate_release_environment(manifest(), receipt())
            client = _create_protected_client(manifest(), validation, object())

        self.assertEqual("MAIMEMO_API_TOKEN", env.reads[-1])
        self.assertEqual(manifest()["deck"]["id"], client.deck_id)

    def test_invalid_quality_capability_blocks_before_token_lookup(self):
        env = TrackingEnvironment(complete_environment())
        with patch.object(os, "environ", env):
            validation = validate_release_environment(manifest(), receipt())
            try:
                _create_protected_client(manifest(), validation, object())
            except Exception as error:
                caught = error
            else:
                self.fail("unprotected quality input opened the client")

        self.assertIsInstance(caught, RuntimeError)
        self.assertIn("protected current-environment review", str(caught))
        self.assertNotIn("MAIMEMO_API_TOKEN", env.reads)

    def test_inputs_are_copied_before_client_is_opened(self):
        approved = receipt()
        expected = copy.deepcopy(approved)
        env = complete_environment()
        with patch.object(os, "environ", env):
            result = validate_release_environment(manifest(), approved)
        approved["approved_sha"] = "c" * 40

        self.assertEqual(expected, result["receipt"])

    def test_capability_is_opaque_noncopyable_and_registry_bound(self):
        current = manifest()
        env = TrackingEnvironment(complete_environment(current))
        with patch.object(os, "environ", env):
            capability = validate_github_receipt(receipt(current), current)

        self.assertFalse(hasattr(capability, "deck_id"))
        self.assertFalse(hasattr(capability, "receipt"))
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

    def test_validation_result_and_nested_receipt_are_immutable(self):
        current = manifest()
        env = TrackingEnvironment(complete_environment(current))
        with patch.object(os, "environ", env):
            result = validate_release_environment(current, receipt(current))

        with self.assertRaises(TypeError):
            result["release_hash"] = "c" * 64
        with self.assertRaises(TypeError):
            result["receipt"]["approved_sha"] = "c" * 40
        with self.assertRaises((AttributeError, TypeError)):
            result.environment = object()
        with self.assertRaises(TypeError):
            copy.copy(result)

    def test_task7_rejects_exact_shape_with_substituted_capability_attribute(self):
        current = manifest()
        env = TrackingEnvironment(complete_environment(current))
        with patch.object(os, "environ", env):
            capability = validate_github_receipt(receipt(current), current)
            valid_result = validate_release_environment(current, receipt(current))
            forged = ForgedValidation(valid_result)
            forged.environment = capability
            with self.assertRaisesRegex(
                RuntimeError, "GitHub release environment receipt is not approved"
            ):
                _create_protected_client(current, forged)

        self.assertNotIn("MAIMEMO_API_TOKEN", env.reads)

    def test_open_revalidates_fresh_environment_before_single_token_read(self):
        current = manifest()
        mutations = (
            ("GITHUB_ACTIONS", "false"),
            ("GITHUB_REF", "refs/pull/9/merge"),
            ("GITHUB_SHA", "c" * 40),
            ("GITHUB_RUN_ID", "999"),
            ("GITHUB_ENVIRONMENT", "staging"),
            ("GITHUB_DEPLOYMENT_STATUS", "failure"),
            ("RELEASE_HASH", "c" * 64),
            ("GITHUB_EVENT_NAME", "push"),
            ("GITHUB_HEAD_REF", "fork-branch"),
            ("GITHUB_BASE_REF", "main"),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                env = TrackingEnvironment(complete_environment(current))
                with patch.object(os, "environ", env):
                    capability = validate_github_receipt(receipt(current), current)
                    env[field] = value
                    with self.assertRaises(RuntimeError):
                        open_protected_client(capability)
                self.assertNotIn("MAIMEMO_API_TOKEN", env.reads)

    def test_replacing_entire_process_environment_invalidates_capability(self):
        current = manifest()
        original = TrackingEnvironment(complete_environment(current))
        replacement = TrackingEnvironment(complete_environment(current))
        replacement["GITHUB_ACTIONS"] = "false"
        with patch.object(os, "environ", original):
            capability = validate_github_receipt(receipt(current), current)

        with patch.object(os, "environ", replacement), self.assertRaisesRegex(
            RuntimeError, "protected release environment mapping changed"
        ):
            open_protected_client(capability)

        self.assertNotIn("MAIMEMO_API_TOKEN", original.reads)
        self.assertNotIn("MAIMEMO_API_TOKEN", replacement.reads)

    def test_same_content_environment_mapping_replacement_is_not_authority(self):
        current = manifest()
        original = TrackingEnvironment(complete_environment(current))
        replacement = TrackingEnvironment(complete_environment(current))
        with patch.object(os, "environ", original):
            capability = validate_github_receipt(receipt(current), current)

        with patch.object(os, "environ", replacement), self.assertRaisesRegex(
            RuntimeError, "protected release environment mapping changed"
        ):
            open_protected_client(capability)

        self.assertNotIn("MAIMEMO_API_TOKEN", original.reads)
        self.assertNotIn("MAIMEMO_API_TOKEN", replacement.reads)

    def test_secret_failures_have_no_cause_or_traceback_leak(self):
        current = manifest()
        for env, constructor_error in (
            (ExplodingTokenEnvironment(complete_environment(current)), None),
            (
                TrackingEnvironment(complete_environment(current)),
                RuntimeError("Bearer top-secret-token"),
            ),
        ):
            with self.subTest(constructor_error=constructor_error):
                with patch.object(os, "environ", env):
                    capability = validate_github_receipt(receipt(current), current)
                    try:
                        if constructor_error is None:
                            open_protected_client(capability)
                        else:
                            with patch(
                                "maimemo_learning_rebuild.api.MaimemoClient",
                                side_effect=constructor_error,
                            ):
                                open_protected_client(capability)
                    except RuntimeError as error:
                        caught = error
                    else:
                        self.fail("secret failure was not raised")

                self.assertIsNone(caught.__cause__)
                self.assertIsNone(caught.__context__)
                self.assertFalse(caught.__suppress_context__)
                rendered = "".join(traceback.format_exception(caught))
                self.assertNotIn("top-secret-token", rendered)
                self.assertIn("[REDACTED]", rendered)

    def test_public_validator_rejects_plain_partial_and_tampered_manifests(self):
        current = manifest()
        partial = {
            "schema_version": 2,
            "release_id": current["release_id"],
            "release_hash": current["release_hash"],
            "deck": copy.deepcopy(current["deck"]),
        }
        plain_copy = copy.deepcopy(dict(current))
        tampered = copy.deepcopy(current)
        tampered["deck"]["name"] = "attacker deck"
        for candidate in (partial, plain_copy, tampered):
            with self.subTest(candidate_type=type(candidate).__name__), patch.object(
                os, "environ", complete_environment(current)
            ), self.assertRaisesRegex(
                RuntimeError, "validated authorized schema-v2 release manifest required"
            ):
                validate_github_receipt(receipt(current), candidate)

    def test_only_workflow_dispatch_without_pr_refs_is_allowed(self):
        current = manifest()
        cases = (
            ("GITHUB_EVENT_NAME", "push"),
            ("GITHUB_EVENT_NAME", "pull_request_review"),
            ("GITHUB_HEAD_REF", "feature"),
            ("GITHUB_BASE_REF", "main"),
        )
        for field, value in cases:
            env = complete_environment(current)
            env[field] = value
            with self.subTest(field=field, value=value), patch.object(
                os, "environ", env
            ), self.assertRaisesRegex(
                RuntimeError, "workflow_dispatch release context required"
            ):
                validate_github_receipt(receipt(current), current)


if __name__ == "__main__":
    unittest.main()
