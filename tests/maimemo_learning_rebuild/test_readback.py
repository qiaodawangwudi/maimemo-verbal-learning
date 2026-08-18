import json
import os
import unittest
from unittest.mock import patch

from maimemo_learning_rebuild.readback import verify_readback, verify_release_readback
from maimemo_learning_rebuild.release_manifest import release_hash


def live_card(card_id, root_id, title, content):
    return {
        "id": card_id,
        "root_id": root_id,
        "grammar_version": 3,
        "content": content,
    }


def expected_cards():
    return [
        {
            "title": "近义辨析｜甲、乙",
            "card_type": "comparison",
            "content": "[P#H1#近义辨析｜甲、乙]\n---\n辨析",
        },
        {
            "title": "基础词义｜甲",
            "card_type": "base",
            "content": (
                "[P#H1#基础词义｜甲]\n---\n"
                "[Card#ID/{{root:近义辨析｜甲、乙}}#近义辨析｜甲、乙]"
            ),
        },
        {
            "title": "语境应用｜甲、乙｜差别",
            "card_type": "application",
            "content": "[P#H1#语境应用｜甲、乙｜差别]\n---\n练习",
        },
    ]


def manifest():
    route_counts = {
        "before": 0,
        "create": 1,
        "update": 0,
        "unchanged": 0,
        "after": 1,
    }
    value = {
        "schema_version": 2,
        "release_id": "release-readback",
        "state": "applied",
        "state_evidence": {},
        "deck": {"id": "deck-release", "name": "公考成语积累辨析"},
        "chapter_routes": {
            "comparison": {
                "id": "chapter-comparison",
                "name": "近义辨析",
                "type": "comparison",
                "counts": dict(route_counts),
            },
            "base": {
                "id": "chapter-base",
                "name": "基础词义",
                "type": "base",
                "counts": dict(route_counts),
            },
            "application": {
                "id": "chapter-application",
                "name": "语境应用",
                "type": "application",
                "counts": dict(route_counts),
            },
        },
        "card_counts": {"before": 0, "after": 3},
        "action_counts": {"create": 3, "update": 0, "unchanged": 0},
        "artifact_hashes": {},
    }
    value["release_hash"] = release_hash(value)
    return value


def complete_live_deck():
    group = live_card(
        "group-1",
        "mkjr_group",
        "近义辨析｜甲、乙",
        "[P#H1#近义辨析｜甲、乙]\n---\n辨析",
    )
    base = live_card(
        "base-1",
        "mkjr_base",
        "基础词义｜甲",
        (
            "[P#H1#基础词义｜甲]\n---\n"
            "[Card#ID/mkjr_group#近义辨析｜甲、乙]"
        ),
    )
    application = live_card(
        "application-1",
        "mkjr_application",
        "语境应用｜甲、乙｜差别",
        "[P#H1#语境应用｜甲、乙｜差别]\n---\n练习",
    )
    cards = [group, base, application]
    comparison_ids = ["group-1"]
    return {
        "id": "deck-release",
        "name": "公考成语积累辨析",
        "chapters": [
            {"id": "chapter-comparison", "name": "近义辨析", "card_ids": comparison_ids},
            {"id": "chapter-base", "name": "基础词义", "card_ids": ["base-1"]},
            {
                "id": "chapter-application",
                "name": "语境应用",
                "card_ids": ["application-1"],
            },
        ],
        "cards": cards,
    }


def swap_comparison_and_base_cards(live):
    comparison = live["chapters"][0]
    base = live["chapters"][1]
    comparison["card_ids"], base["card_ids"] = base["card_ids"], comparison["card_ids"]


class ReadbackTests(unittest.TestCase):
    def test_complete_release_readback_binds_release_and_ci_run(self):
        expected_manifest = manifest()

        with patch.dict(os.environ, {"GITHUB_RUN_ID": "123456"}, clear=False):
            report = verify_release_readback(
                complete_live_deck(), expected_cards(), expected_manifest
            )

        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(expected_manifest["release_hash"], report["release_hash"])
        self.assertEqual("123456", report["github_run_id"])

    def test_correct_total_in_wrong_chapter_fails(self):
        live = complete_live_deck()
        swap_comparison_and_base_cards(live)

        with patch.dict(os.environ, {"GITHUB_RUN_ID": "123456"}, clear=False):
            report = verify_release_readback(live, expected_cards(), manifest())

        self.assertIn("wrong card type in comparison chapter", report["errors"])

    def test_unparseable_target_card_fails(self):
        live = complete_live_deck()
        live["cards"][0]["content"] = "plain text without heading"

        with patch.dict(os.environ, {"GITHUB_RUN_ID": "123456"}, clear=False):
            report = verify_release_readback(live, expected_cards(), manifest())

        self.assertFalse(report["ok"])
        self.assertIn("unparseable live card: group-1", report["errors"])

    def test_exact_chapter_id_and_name_are_required(self):
        cases = (
            ("id", "wrong-comparison", "chapter id mismatch: comparison"),
            ("name", "错误辨析章", "chapter name mismatch: comparison"),
        )
        for field, value, expected_error in cases:
            with self.subTest(field=field):
                live = complete_live_deck()
                live["chapters"][0][field] = value
                with patch.dict(os.environ, {"GITHUB_RUN_ID": "123456"}, clear=False):
                    report = verify_release_readback(live, expected_cards(), manifest())
                self.assertIn(expected_error, report["errors"])

    def test_duplicate_and_unplanned_live_titles_fail(self):
        live = complete_live_deck()
        extra = live_card(
            "base-extra",
            "mkjr_base_extra",
            "基础词义｜多余",
            "[P#H1#基础词义｜多余]\n---\n内容",
        )
        duplicate = live_card(
            "base-duplicate",
            "mkjr_base_duplicate",
            "基础词义｜甲",
            "[P#H1#基础词义｜甲]\n---\n重复",
        )
        live["cards"].extend((extra, duplicate))
        live["chapters"][1]["card_ids"].extend(("base-extra", "base-duplicate"))

        with patch.dict(os.environ, {"GITHUB_RUN_ID": "123456"}, clear=False):
            report = verify_release_readback(live, expected_cards(), manifest())

        self.assertIn("unplanned live title: 基础词义｜多余", report["errors"])
        self.assertIn("duplicate live title: 基础词义｜甲", report["errors"])

    def test_content_grammar_and_root_reference_mismatches_fail(self):
        cases = []
        wrong_content = complete_live_deck()
        wrong_content["cards"][2]["content"] += "错误"
        cases.append((wrong_content, "content mismatch: 语境应用｜甲、乙｜差别"))
        wrong_grammar = complete_live_deck()
        wrong_grammar["cards"][0]["grammar_version"] = 2
        cases.append((wrong_grammar, "grammar version mismatch: 近义辨析｜甲、乙"))
        missing_reference = complete_live_deck()
        missing_reference["cards"][1]["content"] = missing_reference["cards"][1][
            "content"
        ].replace("mkjr_group", "mkjr_missing")
        cases.append(
            (
                missing_reference,
                "missing root reference target: 基础词义｜甲 mkjr_missing",
            )
        )
        for live, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                with patch.dict(os.environ, {"GITHUB_RUN_ID": "123456"}, clear=False):
                    report = verify_release_readback(live, expected_cards(), manifest())
                self.assertIn(expected_error, report["errors"])

    def test_malformed_card_identity_and_routing_fail(self):
        cases = []
        missing_id = complete_live_deck()
        missing_id["cards"][0]["id"] = ""
        cases.append((missing_id, "malformed live card at index 0"))
        bad_root = complete_live_deck()
        bad_root["cards"][0]["root_id"] = "card-root"
        cases.append((bad_root, "malformed root_id: 近义辨析｜甲、乙"))
        bool_grammar = complete_live_deck()
        bool_grammar["cards"][0]["grammar_version"] = True
        cases.append((bool_grammar, "grammar version mismatch: 近义辨析｜甲、乙"))
        duplicate_route = complete_live_deck()
        duplicate_route["chapters"][1]["card_ids"].append("group-1")
        cases.append((duplicate_route, "card assigned to multiple release chapters: group-1"))
        orphan = complete_live_deck()
        orphan["chapters"][0]["card_ids"].clear()
        cases.append((orphan, "unrouted live card: group-1"))
        for live, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                with patch.dict(os.environ, {"GITHUB_RUN_ID": "123456"}, clear=False):
                    report = verify_release_readback(live, expected_cards(), manifest())
                self.assertIn(expected_error, report["errors"])

    def test_empty_route_title_heading_only_payload_and_bare_root_fail(self):
        cases = []
        empty_title_live = complete_live_deck()
        empty_title_expected = expected_cards()
        empty_title_live["cards"][1]["content"] = "[P#H1#基础词义｜]\n---\n内容"
        empty_title_expected[1]["title"] = "基础词义｜"
        empty_title_expected[1]["content"] = "[P#H1#基础词义｜]\n---\n内容"
        cases.append(
            (
                empty_title_live,
                empty_title_expected,
                "malformed card title: 基础词义｜",
            )
        )
        heading_only_live = complete_live_deck()
        heading_only_expected = expected_cards()
        heading_only_live["cards"][2]["content"] = "[P#H1#语境应用｜甲、乙｜差别]"
        heading_only_expected[2]["content"] = "[P#H1#语境应用｜甲、乙｜差别]"
        cases.append(
            (
                heading_only_live,
                heading_only_expected,
                "malformed card payload: 语境应用｜甲、乙｜差别",
            )
        )
        bare_root_live = complete_live_deck()
        bare_root_live["cards"][0]["root_id"] = "mkjr_"
        bare_root_live["cards"][1]["content"] = bare_root_live["cards"][1][
            "content"
        ].replace("mkjr_group", "mkjr_")
        cases.append(
            (
                bare_root_live,
                expected_cards(),
                "malformed root_id: 近义辨析｜甲、乙",
            )
        )
        for live, expected, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                with patch.dict(os.environ, {"GITHUB_RUN_ID": "123456"}, clear=False):
                    report = verify_release_readback(live, expected, manifest())
                self.assertIn(expected_error, report["errors"])

    def test_manifest_counts_and_expected_card_types_are_enforced(self):
        wrong_count = manifest()
        wrong_count["chapter_routes"]["base"]["counts"]["after"] = 2
        wrong_count["release_hash"] = release_hash(wrong_count)
        wrong_expected = expected_cards()
        wrong_expected[0]["card_type"] = "base"
        cases = (
            (complete_live_deck(), expected_cards(), wrong_count, "route count mismatch: base"),
            (
                complete_live_deck(),
                wrong_expected,
                manifest(),
                "expected card type/title mismatch: 近义辨析｜甲、乙",
            ),
        )
        for live, expected, release, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                with patch.dict(os.environ, {"GITHUB_RUN_ID": "123456"}, clear=False):
                    report = verify_release_readback(live, expected, release)
                self.assertIn(expected_error, report["errors"])

    def test_every_manifest_field_used_by_readback_has_a_strict_type(self):
        cases = (
            ("release_id", 7, "release_id must be a nonempty string"),
            ("state_evidence", [], "state_evidence must be an object"),
            ("action_counts", "bad", "manifest action counts are malformed"),
            ("artifact_hashes", False, "artifact_hashes must be an object"),
        )
        for field, value, expected_error in cases:
            with self.subTest(field=field):
                release = manifest()
                release[field] = value
                release["release_hash"] = release_hash(release)
                with patch.dict(os.environ, {"GITHUB_RUN_ID": "123456"}, clear=False):
                    report = verify_release_readback(
                        complete_live_deck(), expected_cards(), release
                    )
                self.assertIn(expected_error, report["errors"])

    def test_tampered_release_hash_and_missing_github_run_id_fail_closed(self):
        tampered = manifest()
        tampered["release_hash"] = "0" * 64
        with patch.dict(os.environ, {"GITHUB_RUN_ID": "123456"}, clear=False):
            tampered_report = verify_release_readback(
                complete_live_deck(), expected_cards(), tampered
            )
        with patch.dict(os.environ, {}, clear=True):
            missing_run_report = verify_release_readback(
                complete_live_deck(), expected_cards(), manifest()
            )

        self.assertIn("release self-hash mismatch", tampered_report["errors"])
        self.assertIn("GITHUB_RUN_ID is required", missing_run_report["errors"])

    def test_all_zero_github_run_ids_are_not_positive(self):
        with patch.dict(os.environ, {"GITHUB_RUN_ID": "000"}, clear=False):
            report = verify_release_readback(
                complete_live_deck(), expected_cards(), manifest()
            )

        self.assertIn(
            "GITHUB_RUN_ID must be a positive decimal string", report["errors"]
        )

    def test_non_json_and_wrong_input_types_return_strict_json_failure_reports(self):
        non_json_live = complete_live_deck()
        non_json_live["cards"][0]["content"] = b"bytes"
        non_json_manifest = manifest()
        non_json_manifest["unexpected"] = float("nan")
        cases = (
            (non_json_live, expected_cards(), manifest(), "live deck is not strict JSON"),
            (complete_live_deck(), {}, manifest(), "expected cards must be a list"),
            (
                complete_live_deck(),
                expected_cards(),
                non_json_manifest,
                "release manifest is not strict JSON",
            ),
        )
        for live, expected, release, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                with patch.dict(os.environ, {"GITHUB_RUN_ID": "123456"}, clear=False):
                    report = verify_release_readback(live, expected, release)
                self.assertFalse(report["ok"])
                self.assertIn(expected_error, report["errors"])
                json.dumps(report, allow_nan=False)

    def test_deeply_nested_json_fails_closed_without_recursion_escape(self):
        deeply_nested = []
        for _ in range(2000):
            deeply_nested = [deeply_nested]
        live = complete_live_deck()
        live["unexpected"] = deeply_nested

        with patch.dict(os.environ, {"GITHUB_RUN_ID": "123456"}, clear=False):
            report = verify_release_readback(live, expected_cards(), manifest())

        self.assertFalse(report["ok"])
        self.assertIn("live deck is not strict JSON", report["errors"])
        json.dumps(report, allow_nan=False)

    def test_readback_resolves_expected_runtime_root_placeholder(self):
        group_content = "[P#H1#近义辨析｜甲、乙]\n---\n辨析"
        live_base = (
            "[P#H1#基础词义｜甲]\n---\n"
            "[Card#ID/mkjr_new_group#近义辨析｜甲、乙]"
        )
        expected_base = live_base.replace(
            "mkjr_new_group", "{{root:近义辨析｜甲、乙}}"
        )
        cards = [
            live_card("g1", "mkjr_new_group", "近义辨析｜甲、乙", group_content),
            live_card("b1", "mkjr_base", "基础词义｜甲", live_base),
        ]
        expected = [
            {"title": "近义辨析｜甲、乙", "content": group_content},
            {"title": "基础词义｜甲", "content": expected_base},
        ]
        plan = {
            "expected_after": 2,
            "actions": [
                {"title": "近义辨析｜甲、乙"},
                {"title": "基础词义｜甲"},
            ],
        }

        report = verify_readback(cards, expected, plan)

        self.assertTrue(report["ok"], report["errors"])

    def test_complete_readback_matches_titles_content_versions_and_counts(self):
        cards = [
            live_card("c1", "r1", "基础词义｜甲", "[P#H1#基础词义｜甲]\n---\n新内容")
        ]
        expected = [
            {"title": "基础词义｜甲", "content": "[P#H1#基础词义｜甲]\n---\n新内容"}
        ]
        plan = {"expected_after": 1, "actions": [{"title": "基础词义｜甲"}]}

        report = verify_readback(cards, expected, plan)

        self.assertTrue(report["ok"], report["errors"])

    def test_readback_reports_unplanned_addition_content_and_reference_failures(self):
        cards = [
            live_card(
                "c1",
                "r1",
                "基础词义｜甲",
                "[P#H1#基础词义｜甲]\n[Card#ID/mkjr_missing#组]",
            ),
            live_card("c2", "r2", "基础词义｜多余", "[P#H1#基础词义｜多余]\n---\n内容"),
        ]
        expected = [{"title": "基础词义｜甲", "content": "[P#H1#基础词义｜甲]\n---\n应有内容"}]
        plan = {"expected_after": 1, "actions": [{"title": "基础词义｜甲"}]}

        report = verify_readback(cards, expected, plan)

        self.assertFalse(report["ok"])
        self.assertIn("live count mismatch: expected 1 got 2", report["errors"])
        self.assertIn("content mismatch: 基础词义｜甲", report["errors"])
        self.assertIn("unplanned live title: 基础词义｜多余", report["errors"])
        self.assertIn("missing root reference target: 基础词义｜甲 mkjr_missing", report["errors"])


if __name__ == "__main__":
    unittest.main()
