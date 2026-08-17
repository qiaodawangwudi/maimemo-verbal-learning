import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path


from maimemo_learning_rebuild import release_manifest as release_manifest_module
from maimemo_learning_rebuild.release_manifest import (
    build_release_manifest,
    release_hash,
    transition_release_state,
    validate_release_manifest,
)


load_release_manifest_bytes = getattr(
    release_manifest_module,
    "load_release_manifest_bytes",
    lambda raw: {},
)
load_release_manifest_file = getattr(
    release_manifest_module,
    "load_release_manifest_file",
    lambda path: {},
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
COUNT_KEYS = ("before", "create", "update", "unchanged", "after")
PROTECTED_FIELDS = (
    "schema_version",
    "release_id",
    "deck",
    "chapter_routes",
    "card_counts",
    "action_counts",
    "artifact_hashes",
)
STATE_SEQUENCE = (
    "draft",
    "plan_frozen",
    "ci_verified",
    "awaiting_user_authorization",
    "authorized",
    "applied",
    "verified",
)
RECEIPT_KEYS = {
    "ci_verified": "ci_receipt",
    "awaiting_user_authorization": "awaiting_user_authorization_receipt",
    "authorized": "authorization_receipt",
    "applied": "applied_receipt",
    "verified": "verification_receipt",
}
RECEIPT_TYPES = {
    "ci_verified": "ci_verified",
    "awaiting_user_authorization": "awaiting_user_authorization",
    "authorized": "authorization",
    "applied": "applied",
    "verified": "verification",
}


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


def canonical_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def protected_payload_hash(manifest):
    payload = {key: manifest[key] for key in PROTECTED_FIELDS}
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def frozen_baseline(manifest):
    return {
        "receipt_type": "verified_frozen_baseline",
        "verified": True,
        "release_id": manifest["release_id"],
        "protected_payload_hash": protected_payload_hash(manifest),
        "subject_state": "draft",
        "subject_release_hash": manifest["release_hash"],
    }


def state_receipt(manifest, target_state):
    return {
        "receipt_type": RECEIPT_TYPES[target_state],
        "verified": True,
        "release_id": manifest["release_id"],
        "protected_payload_hash": protected_payload_hash(manifest),
        "subject_state": manifest["state"],
        "subject_release_hash": manifest["release_hash"],
    }


def advance_release(manifest, target_state, baseline):
    evidence = {"frozen_baseline": baseline}
    if target_state != "plan_frozen":
        evidence[RECEIPT_KEYS[target_state]] = state_receipt(manifest, target_state)
    return transition_release_state(manifest, target_state, evidence)


def release_at(target_state):
    manifest = complete_manifest()
    baseline = frozen_baseline(manifest)
    for state in STATE_SEQUENCE[1 : STATE_SEQUENCE.index(target_state) + 1]:
        manifest = advance_release(manifest, state, baseline)
    return manifest, baseline


def replace_json_artifact(manifest, current_artifacts, key, payload):
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    current_artifacts[key] = raw
    manifest["artifact_hashes"][key] = hashlib.sha256(raw).hexdigest()
    refresh_self_hash(manifest)


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
                    "counts": {"before": 0, "create": 1, "update": 0, "unchanged": 0, "after": 1},
                },
                "base": {
                    "id": "chapter-base",
                    "name": "基础词义",
                    "type": "base",
                    "counts": {"before": 2, "create": 0, "update": 1, "unchanged": 1, "after": 2},
                },
                "application": {
                    "id": "chapter-application",
                    "name": "语境应用",
                    "type": "application",
                    "counts": {"before": 0, "create": 1, "update": 0, "unchanged": 0, "after": 1},
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
                    counts = manifest["chapter_routes"][route_key]["counts"]
                    counts[count_key] = counts.get(count_key, 0) + 1
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

    def test_equal_count_card_type_swap_cannot_cross_frozen_routes(self):
        changed_artifacts = artifacts()
        cards = json.loads(changed_artifacts["final_cards"].decode("utf-8"))
        comparison = cards["cards"][0]
        application = cards["cards"][3]
        comparison["card_type"], application["card_type"] = (
            application["card_type"],
            comparison["card_type"],
        )
        manifest = complete_manifest()
        replace_json_artifact(manifest, changed_artifacts, "final_cards", cards)

        errors = validate_release_manifest(manifest, changed_artifacts)

        self.assertIn(
            "frozen card route binding mismatch: comparison:甲、乙",
            errors,
        )
        self.assertIn(
            "frozen card route binding mismatch: application:甲、乙:差别",
            errors,
        )

    def test_rejects_orphan_duplicate_unknown_and_unidentified_plan_actions(self):
        cases = []
        orphan = json.loads(fixture_bytes("action_plan").decode("utf-8"))
        orphan["actions"].append(
            {
                "stable_card_key": "base:孤立",
                "title": "基础词义｜孤立",
                "card_type": "base",
                "route_id": "chapter-base",
                "route_name": "基础词义",
                "action": "create",
                "card_id": "",
            }
        )
        cases.append((orphan, "orphan action plan card: base:孤立"))
        duplicate = json.loads(fixture_bytes("action_plan").decode("utf-8"))
        duplicate["actions"][1]["stable_card_key"] = "comparison:甲、乙"
        cases.append((duplicate, "duplicate action plan stable_card_key: comparison:甲、乙"))
        unknown = json.loads(fixture_bytes("action_plan").decode("utf-8"))
        unknown["actions"][0]["action"] = "manual-review"
        cases.append((unknown, "unknown release action: manual-review"))
        missing_id = json.loads(fixture_bytes("action_plan").decode("utf-8"))
        missing_id["actions"][1]["card_id"] = ""
        cases.append((missing_id, "action card_id is required: base:甲"))

        for plan, expected in cases:
            with self.subTest(expected=expected):
                changed_artifacts = artifacts()
                manifest = complete_manifest()
                replace_json_artifact(manifest, changed_artifacts, "action_plan", plan)
                self.assertIn(
                    expected,
                    validate_release_manifest(manifest, changed_artifacts),
                )

    def test_action_counts_are_recomputed_from_action_list(self):
        changed_artifacts = artifacts()
        plan = json.loads(changed_artifacts["action_plan"].decode("utf-8"))
        plan["actions"].append(
            {
                "stable_card_key": "application:孤立",
                "title": "语境应用｜孤立",
                "card_type": "application",
                "route_id": "chapter-application",
                "route_name": "语境应用",
                "action": "create",
                "card_id": "",
            }
        )
        manifest = complete_manifest()
        replace_json_artifact(manifest, changed_artifacts, "action_plan", plan)

        errors = validate_release_manifest(manifest, changed_artifacts)

        self.assertIn("action plan declared count mismatch: create", errors)

    def test_route_expectations_come_from_independent_frozen_plan(self):
        changed_artifacts = artifacts()
        plan = json.loads(changed_artifacts["action_plan"].decode("utf-8"))
        plan["route_counts"]["comparison"]["create"] = 0
        plan["route_counts"]["comparison"]["after"] = 0
        manifest = complete_manifest()
        replace_json_artifact(manifest, changed_artifacts, "action_plan", plan)

        errors = validate_release_manifest(manifest, changed_artifacts)

        self.assertIn("action plan route count mismatch: comparison.create", errors)
        self.assertIn("chapter route count mismatch: comparison.create", errors)

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

    def test_strict_manifest_bytes_and_file_loaders_feed_validation(self):
        manifest = complete_manifest()
        raw = json.dumps(manifest, ensure_ascii=False).encode("utf-8")

        loaded = load_release_manifest_bytes(raw)
        self.assertEqual(manifest, loaded)
        self.assertEqual([], validate_release_manifest(raw, artifacts()))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "release_manifest.json"
            path.write_bytes(raw)
            self.assertEqual(manifest, load_release_manifest_file(path))

    def test_strict_manifest_loader_rejects_duplicate_nan_and_invalid_utf8(self):
        malformed = {
            "duplicate-key": b'{"schema_version":2,"schema_version":2}',
            "non-finite": b'{"schema_version":2,"score":NaN}',
            "invalid-utf8": b'{"schema_version":2,"note":"\xff"}',
        }

        for label, raw in malformed.items():
            with self.subTest(label=label):
                with self.assertRaisesRegex(ValueError, "strict release manifest JSON"):
                    load_release_manifest_bytes(raw)
                self.assertIn(
                    "release manifest is not strict JSON",
                    validate_release_manifest(raw, artifacts()),
                )

    def test_manifest_exact_schema_rejects_unknown_and_git_receipt_fields(self):
        cases = []
        unknown = complete_manifest()
        unknown["note"] = "extra"
        cases.append((unknown, "release manifest fields mismatch"))
        nested_commit = complete_manifest()
        nested_commit["deployment"] = {"commit_sha": "a" * 40}
        cases.append((nested_commit, "prohibited Git receipt field: commit_sha"))
        merged_sha = complete_manifest()
        merged_sha["merged_sha"] = "b" * 40
        cases.append((merged_sha, "prohibited Git receipt field: merged_sha"))
        nested_unknown = complete_manifest()
        nested_unknown["chapter_routes"]["base"]["unexpected"] = True
        cases.append((nested_unknown, "chapter route fields mismatch: base"))

        for manifest, expected in cases:
            with self.subTest(expected=expected):
                refresh_self_hash(manifest)
                self.assertIn(
                    expected,
                    validate_release_manifest(manifest, artifacts()),
                )

    def test_malformed_protected_manifest_fails_closed_without_exception(self):
        authorized, _ = release_at("authorized")
        authorized.pop("deck")
        refresh_self_hash(authorized)

        try:
            errors = validate_release_manifest(authorized, artifacts())
        except (TypeError, ValueError, KeyError) as exc:
            errors = [f"unexpected exception: {type(exc).__name__}"]

        self.assertIn("release manifest fields mismatch", errors)
        self.assertIn("release state evidence lineage incomplete: authorized", errors)

    def test_release_hash_rejects_non_json_values(self):
        with self.assertRaisesRegex(ValueError, "strict JSON"):
            release_hash({"value": float("nan")})
        with self.assertRaisesRegex(ValueError, "strict JSON"):
            release_hash({"value": b"bytes"})

    def test_every_target_state_requires_its_own_verified_receipt(self):
        current = complete_manifest()
        baseline = frozen_baseline(current)

        for target in STATE_SEQUENCE[1:]:
            with self.subTest(target=target):
                incomplete = {} if target == "plan_frozen" else {
                    "frozen_baseline": baseline
                }
                with self.assertRaisesRegex(
                    ValueError,
                    "missing required transition evidence",
                ):
                    transition_release_state(current, target, incomplete)
                current = advance_release(current, target, baseline)
                self.assertEqual([], validate_release_manifest(current, artifacts()))

    def test_validator_rejects_forged_authorized_state_and_incomplete_lineage(self):
        forged = complete_manifest()
        forged["state"] = "authorized"
        refresh_self_hash(forged)

        errors = validate_release_manifest(forged, artifacts())

        self.assertIn("release state evidence lineage incomplete: authorized", errors)
        baseline = frozen_baseline(complete_manifest())
        with self.assertRaisesRegex(ValueError, "current release state lineage is invalid"):
            transition_release_state(
                forged,
                "applied",
                {
                    "frozen_baseline": baseline,
                    "applied_receipt": state_receipt(forged, "applied"),
                },
            )

        authorized, _ = release_at("authorized")
        authorized["state_evidence"].pop("ci_receipt")
        refresh_self_hash(authorized)
        self.assertIn(
            "release state evidence lineage incomplete: authorized",
            validate_release_manifest(authorized, artifacts()),
        )

    def test_receipts_bind_verified_flag_release_payload_hash_and_prior_state(self):
        draft = complete_manifest()
        bad_baselines = []
        for field, value in (
            ("verified", False),
            ("release_id", "other-release"),
            ("protected_payload_hash", "0" * 64),
            ("subject_state", "authorized"),
            ("subject_release_hash", "1" * 64),
        ):
            receipt = frozen_baseline(draft)
            receipt[field] = value
            bad_baselines.append(receipt)

        for receipt in bad_baselines:
            with self.subTest(receipt=receipt):
                with self.assertRaisesRegex(ValueError, "invalid verified frozen baseline"):
                    transition_release_state(
                        draft,
                        "plan_frozen",
                        {"frozen_baseline": receipt},
                    )

        baseline = frozen_baseline(draft)
        frozen = advance_release(draft, "plan_frozen", baseline)
        for field, value in (
            ("verified", False),
            ("release_id", "other-release"),
            ("protected_payload_hash", "2" * 64),
            ("subject_state", "draft"),
            ("subject_release_hash", "3" * 64),
        ):
            receipt = state_receipt(frozen, "ci_verified")
            receipt[field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "invalid ci receipt"):
                    transition_release_state(
                        frozen,
                        "ci_verified",
                        {
                            "frozen_baseline": baseline,
                            "ci_receipt": receipt,
                        },
                    )

    def test_protected_transition_requires_external_verified_baseline_each_time(self):
        draft = complete_manifest()
        baseline = frozen_baseline(draft)
        frozen = advance_release(draft, "plan_frozen", baseline)

        with self.assertRaisesRegex(ValueError, "missing verified frozen baseline"):
            transition_release_state(
                frozen,
                "ci_verified",
                {"ci_receipt": state_receipt(frozen, "ci_verified")},
            )

    def test_rehashed_protected_change_forks_against_external_baseline(self):
        draft = complete_manifest()
        baseline = frozen_baseline(draft)
        frozen = advance_release(draft, "plan_frozen", baseline)
        original = copy.deepcopy(frozen)
        frozen["artifact_hashes"]["final_cards"] = "d" * 64
        refresh_self_hash(frozen)

        fork = transition_release_state(
            frozen,
            "ci_verified",
            {
                "frozen_baseline": baseline,
                "ci_receipt": state_receipt(frozen, "ci_verified"),
                "new_release_id": "release-2026-08-17-002",
            },
        )

        self.assertEqual("draft", fork["state"])
        self.assertEqual("release-2026-08-17-002", fork["release_id"])
        self.assertEqual("d" * 64, fork["artifact_hashes"]["final_cards"])
        self.assertEqual({}, fork["state_evidence"])
        self.assertEqual(release_hash(fork), fork["release_hash"])
        self.assertEqual("plan_frozen", original["state"])

    def test_state_machine_rejects_skip_backward_and_unknown_transitions(self):
        frozen, baseline = release_at("plan_frozen")
        for target in ("draft", "authorized", "not-a-state"):
            with self.subTest(target=target):
                with self.assertRaisesRegex(ValueError, "invalid release state transition"):
                    transition_release_state(
                        frozen,
                        target,
                        {"frozen_baseline": baseline},
                    )


if __name__ == "__main__":
    unittest.main()
