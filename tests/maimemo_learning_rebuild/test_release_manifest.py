import copy
import hashlib
import json
import unittest
from pathlib import Path


from maimemo_learning_rebuild.release_manifest import (
    build_release_manifest,
    release_hash,
    transition_release_state,
    validate_release_manifest,
)


ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "release"
ARTIFACT_KEYS = (
    "source_inventory",
    "semantic_registry",
    "group_registry",
    "application_review",
    "blind_review",
    "final_cards",
    "snapshot",
    "action_plan",
    "quality_reports",
    "engine_tree",
    "skill_tree",
)
ROUTE_KEYS = ("comparison", "base", "application")
COUNT_KEYS = ("create", "update", "unchanged", "after")


def fixture_bytes(name):
    return (FIXTURES / f"{name}.json").read_bytes()


def artifacts():
    return {
        "source_inventory": fixture_bytes("source_inventory"),
        "semantic_registry": b'{"schema_version":1,"records":[]}',
        "group_registry": b'{"schema_version":1,"groups":[]}',
        "application_review": b'{"complete":true,"applications":[]}',
        "blind_review": b'{"complete":true,"reviews":[]}',
        "final_cards": fixture_bytes("final_cards"),
        "snapshot": b'{"deck_id":"deck-release","cards":[]}',
        "action_plan": fixture_bytes("action_plan"),
        "quality_reports": fixture_bytes("quality_reports"),
        "engine_tree": b"engine.py\x00frozen-engine-sha256\n",
        "skill_tree": b"SKILL.md\x00frozen-skill-sha256\n",
    }


def complete_inputs():
    return {
        "release_id": "release-2026-08-17-001",
        "state": "draft",
        "artifacts": artifacts(),
    }


def complete_manifest():
    return build_release_manifest(complete_inputs())


def refresh_self_hash(manifest):
    manifest["release_hash"] = release_hash(manifest)
    return manifest


class ReleaseManifestTests(unittest.TestCase):
    def test_builds_v2_manifest_with_exact_routes_and_counts(self):
        manifest = complete_manifest()

        self.assertEqual(2, manifest["schema_version"])
        self.assertEqual(set(ROUTE_KEYS), set(manifest["chapter_routes"]))
        self.assertEqual(
            {
                "comparison": {
                    "id": "chapter-comparison",
                    "name": "近义辨析",
                    "type": "comparison",
                    "counts": {"create": 1, "update": 0, "unchanged": 0, "after": 1},
                },
                "base": {
                    "id": "chapter-base",
                    "name": "基础词义",
                    "type": "base",
                    "counts": {"create": 0, "update": 1, "unchanged": 1, "after": 2},
                },
                "application": {
                    "id": "chapter-application",
                    "name": "语境应用",
                    "type": "application",
                    "counts": {"create": 1, "update": 0, "unchanged": 0, "after": 1},
                },
            },
            manifest["chapter_routes"],
        )
        self.assertEqual({"before": 2, "after": 4}, manifest["card_counts"])
        self.assertEqual(
            {"create": 2, "update": 1, "unchanged": 1},
            manifest["action_counts"],
        )
        self.assertEqual(set(ARTIFACT_KEYS), set(manifest["artifact_hashes"]))
        self.assertEqual(release_hash(manifest), manifest["release_hash"])
        self.assertFalse(any("commit" in key.lower() for key in manifest))

    def test_new_manifest_cannot_start_in_an_authorized_state(self):
        inputs = complete_inputs()
        inputs["state"] = "authorized"

        with self.assertRaisesRegex(ValueError, "new release must start in draft"):
            build_release_manifest(inputs)

    def test_release_hash_uses_canonical_utf8_json_and_excludes_only_self_hash(self):
        manifest = complete_manifest()
        reordered = {key: manifest[key] for key in reversed(tuple(manifest))}
        expected_payload = {key: value for key, value in manifest.items() if key != "release_hash"}
        expected = hashlib.sha256(
            json.dumps(
                expected_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

        self.assertEqual(expected, release_hash(manifest))
        self.assertEqual(expected, release_hash(reordered))

    def test_every_manifest_field_is_hash_bound(self):
        manifest = complete_manifest()
        original = release_hash(manifest)
        mutations = []

        for key in ("schema_version", "release_id", "state"):
            mutations.append((key, lambda item, key=key: item.__setitem__(key, "changed")))
        for key in ("id", "name"):
            mutations.append((f"deck.{key}", lambda item, key=key: item["deck"].__setitem__(key, "changed")))
        for artifact_key in ARTIFACT_KEYS:
            mutations.append(
                (
                    f"artifact_hashes.{artifact_key}",
                    lambda item, artifact_key=artifact_key: item["artifact_hashes"].__setitem__(artifact_key, "0" * 64),
                )
            )
        for route_key in ROUTE_KEYS:
            for field in ("id", "name", "type"):
                mutations.append(
                    (
                        f"chapter_routes.{route_key}.{field}",
                        lambda item, route_key=route_key, field=field: item["chapter_routes"][route_key].__setitem__(field, "changed"),
                    )
                )
            for count_key in COUNT_KEYS:
                mutations.append(
                    (
                        f"chapter_routes.{route_key}.counts.{count_key}",
                        lambda item, route_key=route_key, count_key=count_key: item["chapter_routes"][route_key]["counts"].__setitem__(count_key, 99),
                    )
                )
        for key in ("before", "after"):
            mutations.append((f"card_counts.{key}", lambda item, key=key: item["card_counts"].__setitem__(key, 99)))
        for key in ("create", "update", "unchanged"):
            mutations.append((f"action_counts.{key}", lambda item, key=key: item["action_counts"].__setitem__(key, 99)))
        mutations.append(("state_evidence", lambda item: item["state_evidence"].__setitem__("proof", True)))

        for label, mutate in mutations:
            with self.subTest(field=label):
                changed = copy.deepcopy(manifest)
                mutate(changed)
                self.assertNotEqual(original, release_hash(changed))

    def test_route_or_count_change_invalidates_hash(self):
        manifest = complete_manifest()
        original = release_hash(manifest)
        manifest["chapter_routes"]["base"]["id"] = "other"
        self.assertNotEqual(original, release_hash(manifest))

    def test_swapped_routes_fail_even_when_total_matches(self):
        manifest = complete_manifest()
        manifest["chapter_routes"]["base"], manifest["chapter_routes"]["application"] = (
            manifest["chapter_routes"]["application"],
            manifest["chapter_routes"]["base"],
        )
        refresh_self_hash(manifest)

        self.assertIn(
            "chapter route type mismatch: base",
            validate_release_manifest(manifest, artifacts()),
        )

    def test_rejects_route_key_id_name_and_type_substitution(self):
        cases = []
        missing_key = complete_manifest()
        missing_key["chapter_routes"].pop("base")
        cases.append((missing_key, "chapter route keys mismatch"))
        duplicate_id = complete_manifest()
        duplicate_id["chapter_routes"]["base"]["id"] = "chapter-comparison"
        cases.append((duplicate_id, "duplicate chapter route id: chapter-comparison"))
        duplicate_name = complete_manifest()
        duplicate_name["chapter_routes"]["base"]["name"] = "近义辨析"
        cases.append((duplicate_name, "duplicate chapter route name: 近义辨析"))
        wrong_name = complete_manifest()
        wrong_name["chapter_routes"]["base"]["name"] = "错误章节"
        cases.append((wrong_name, "chapter route name mismatch: base"))
        wrong_type = complete_manifest()
        wrong_type["chapter_routes"]["base"]["type"] = "application"
        cases.append((wrong_type, "chapter route type mismatch: base"))

        for manifest, expected in cases:
            with self.subTest(expected=expected):
                refresh_self_hash(manifest)
                self.assertIn(expected, validate_release_manifest(manifest, artifacts()))

    def test_rejects_each_wrong_per_type_count(self):
        for route_key in ROUTE_KEYS:
            for count_key in COUNT_KEYS:
                with self.subTest(route=route_key, count=count_key):
                    manifest = complete_manifest()
                    manifest["chapter_routes"][route_key]["counts"][count_key] += 1
                    refresh_self_hash(manifest)
                    self.assertIn(
                        f"chapter route count mismatch: {route_key}.{count_key}",
                        validate_release_manifest(manifest, artifacts()),
                    )

    def test_recounts_frozen_card_types_after_attacker_rehashes_artifact(self):
        changed_artifacts = artifacts()
        cards = json.loads(changed_artifacts["final_cards"].decode("utf-8"))
        cards["cards"][2]["action"] = "create"
        changed_artifacts["final_cards"] = json.dumps(cards, ensure_ascii=False).encode("utf-8")
        manifest = complete_manifest()
        manifest["artifact_hashes"]["final_cards"] = hashlib.sha256(
            changed_artifacts["final_cards"]
        ).hexdigest()
        refresh_self_hash(manifest)

        errors = validate_release_manifest(manifest, changed_artifacts)

        self.assertIn("chapter route count mismatch: base.create", errors)
        self.assertIn("chapter route count mismatch: base.unchanged", errors)
        self.assertIn("action count mismatch: create", errors)

    def test_rejects_action_plan_card_action_mismatch_even_when_totals_match(self):
        changed_artifacts = artifacts()
        plan = json.loads(changed_artifacts["action_plan"].decode("utf-8"))
        plan["actions"][0]["action"], plan["actions"][1]["action"] = (
            plan["actions"][1]["action"],
            plan["actions"][0]["action"],
        )
        changed_artifacts["action_plan"] = json.dumps(
            plan, ensure_ascii=False
        ).encode("utf-8")
        manifest = complete_manifest()
        manifest["artifact_hashes"]["action_plan"] = hashlib.sha256(
            changed_artifacts["action_plan"]
        ).hexdigest()
        refresh_self_hash(manifest)

        errors = validate_release_manifest(manifest, changed_artifacts)

        self.assertIn(
            "action plan does not match frozen card: 近义辨析｜甲、乙",
            errors,
        )

    def test_rejects_changed_artifact_bytes_and_self_hash_mismatch(self):
        changed_artifacts = artifacts()
        changed_artifacts["source_inventory"] += b"\n"
        manifest = complete_manifest()

        self.assertIn(
            "artifact byte hash mismatch: source_inventory",
            validate_release_manifest(manifest, changed_artifacts),
        )
        manifest["release_hash"] = "0" * 64
        self.assertIn(
            "release self-hash mismatch",
            validate_release_manifest(manifest, artifacts()),
        )

    def test_rejects_non_strict_json_artifacts_and_duplicate_keys(self):
        cases = {
            "non-finite": b'{"records":[],"score":NaN}',
            "duplicate-key": b'{"records":[],"records":[]}',
        }
        for label, raw in cases.items():
            with self.subTest(label=label):
                changed = artifacts()
                changed["semantic_registry"] = raw
                self.assertIn(
                    f"artifact is not strict JSON: semantic_registry",
                    validate_release_manifest(complete_manifest(), changed),
                )

    def test_release_hash_rejects_non_json_values(self):
        with self.assertRaisesRegex(ValueError, "strict JSON"):
            release_hash({"value": float("nan")})
        with self.assertRaisesRegex(ValueError, "strict JSON"):
            release_hash({"value": b"bytes"})

    def test_plan_frozen_cannot_skip_authorization_gates_without_evidence(self):
        frozen = transition_release_state(
            complete_manifest(),
            "plan_frozen",
            {"plan_frozen": "frozen-plan-receipt"},
        )
        original = copy.deepcopy(frozen)

        with self.assertRaisesRegex(
            ValueError,
            "missing release state evidence: ci_verified, awaiting_user_authorization",
        ):
            transition_release_state(frozen, "authorized", {})

        authorized = transition_release_state(
            frozen,
            "authorized",
            {
                "ci_verified": "ci-receipt",
                "awaiting_user_authorization": "authorization-request-receipt",
            },
        )

        self.assertEqual("authorized", authorized["state"])
        self.assertEqual(release_hash(authorized), authorized["release_hash"])
        self.assertEqual(original, frozen)

    def test_protected_artifact_change_forks_new_draft_without_mutating_authorized(self):
        frozen = transition_release_state(complete_manifest(), "plan_frozen", {})
        authorized = transition_release_state(
            frozen,
            "authorized",
            {"ci_verified": True, "awaiting_user_authorization": True},
        )
        original = copy.deepcopy(authorized)
        changed_hashes = copy.deepcopy(authorized["artifact_hashes"])
        changed_hashes["final_cards"] = "f" * 64

        fork = transition_release_state(
            authorized,
            "authorized",
            {
                "protected_artifact_hashes": changed_hashes,
                "new_release_id": "release-2026-08-17-002",
            },
        )

        self.assertEqual("draft", fork["state"])
        self.assertEqual("release-2026-08-17-002", fork["release_id"])
        self.assertEqual("f" * 64, fork["artifact_hashes"]["final_cards"])
        self.assertEqual({}, fork["state_evidence"])
        self.assertEqual(release_hash(fork), fork["release_hash"])
        self.assertEqual(original, authorized)

    def test_direct_change_to_authorized_artifact_hash_also_forks_draft(self):
        frozen = transition_release_state(complete_manifest(), "plan_frozen", {})
        authorized = transition_release_state(
            frozen,
            "authorized",
            {"ci_verified": True, "awaiting_user_authorization": True},
        )
        changed = copy.deepcopy(authorized)
        changed["artifact_hashes"]["final_cards"] = "e" * 64

        fork = transition_release_state(changed, "applied", {})

        self.assertEqual("draft", fork["state"])
        self.assertNotEqual(authorized["release_id"], fork["release_id"])
        self.assertEqual("e" * 64, fork["artifact_hashes"]["final_cards"])
        self.assertEqual(release_hash(fork), fork["release_hash"])
        self.assertEqual("authorized", authorized["state"])

    def test_direct_change_after_plan_freeze_forks_draft(self):
        frozen = transition_release_state(complete_manifest(), "plan_frozen", {})
        frozen["artifact_hashes"]["final_cards"] = "d" * 64

        fork = transition_release_state(frozen, "ci_verified", {})

        self.assertEqual("draft", fork["state"])
        self.assertNotEqual(frozen["release_id"], fork["release_id"])
        self.assertEqual(release_hash(fork), fork["release_hash"])

    def test_state_machine_rejects_backward_and_unknown_transitions(self):
        frozen = transition_release_state(complete_manifest(), "plan_frozen", {})
        for target in ("draft", "not-a-state"):
            with self.subTest(target=target):
                with self.assertRaisesRegex(ValueError, "invalid release state transition"):
                    transition_release_state(frozen, target, {})


if __name__ == "__main__":
    unittest.main()
