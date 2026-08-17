import copy
import io
import json
import os
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from maimemo_learning_rebuild.api import (
    AmbiguousMutationError,
    PermanentApiError,
    RateLimitError,
    UrllibTransport,
)
from maimemo_learning_rebuild.release_writer import (
    _validate_release_environment,
    execute_release,
    main,
)
from tests.maimemo_learning_rebuild.test_release_writer import (
    ROUTES,
    FakeClient,
    MemoryJournal,
    WaitPolicy,
    card,
    live_card,
    live_deck,
    manifest,
    no_wait,
)


COMPARISON_A = "近义辨析｜甲、乙"
COMPARISON_B = "近义辨析｜丙、丁"
COMPARISON_A_CONTENT = f"[P#H1#{COMPARISON_A}]\n---\n辨析甲乙"
COMPARISON_B_CONTENT = f"[P#H1#{COMPARISON_B}]\n---\n辨析丙丁"


class ReadMutationClient(FakeClient):
    def __init__(self, live, mutate_at, mutation):
        super().__init__(live)
        self.read_count = 0
        self.mutate_at = mutate_at
        self.mutation = mutation

    def read_deck(self):
        self.read_count += 1
        if self.read_count == self.mutate_at:
            self.mutation(self.live)
        return super().read_deck()


class BoundedRateLimitClient(FakeClient):
    def create_card(self, chapter_id, content, guard):
        self.create_attempts += 1
        self.post_calls.append(("create", chapter_id, content))
        raise RateLimitError(3600)


class CancelAfterWaitPolicy(WaitPolicy):
    def wait(self, seconds):
        super().wait(seconds)
        self.cancelled_value = True


def validation_manifest():
    return {
        "release_id": "release-1",
        "release_hash": "a" * 64,
        "deck": {"id": "deck", "name": "deck"},
    }


def receipt(run_id="123"):
    return {
        "release_id": "release-1",
        "release_hash": "a" * 64,
        "github_run_id": run_id,
        "approved": True,
    }


def successful_validation(receipt_value):
    return {
        "ok": True,
        "receipt": copy.deepcopy(receipt_value),
        "release_id": "release-1",
        "release_hash": "a" * 64,
        "github_run_id": receipt_value["github_run_id"],
    }


class ReleaseWriterAdversarialTests(unittest.TestCase):
    def test_dependent_write_revalidates_exact_title_to_root_mapping(self):
        base_content = (
            "[P#H1#基础词义｜甲]\n---\n"
            f"[Card#ID/{{{{root:{COMPARISON_A}}}}}#{COMPARISON_A}]"
        )
        cards = [
            card(COMPARISON_A, "comparison", COMPARISON_A_CONTENT),
            card(COMPARISON_B, "comparison", COMPARISON_B_CONTENT),
            card("基础词义｜甲", "base", base_content),
        ]
        live = live_deck(
            [
                live_card("a", COMPARISON_A, "comparison", COMPARISON_A_CONTENT, "mkjr_a"),
                live_card("b", COMPARISON_B, "comparison", COMPARISON_B_CONTENT, "mkjr_b"),
            ]
        )

        def swap_roots(deck):
            by_id = {value["id"]: value for value in deck["cards"]}
            by_id["a"]["root_id"] = "mkjr_new"
            by_id["b"]["root_id"] = "mkjr_a"

        client = ReadMutationClient(live, mutate_at=5, mutation=swap_roots)
        with self.assertRaisesRegex(RuntimeError, "release-wide live drift"):
            execute_release(
                client,
                manifest(live_deck(), cards),
                cards,
                MemoryJournal(),
                no_wait,
            )
        self.assertFalse(any(call[1] == ROUTES["base"] for call in client.post_calls))

    def test_resolved_frozen_root_must_match_exact_comparison_title_before_post(self):
        comparison = card(
            COMPARISON_A,
            "comparison",
            COMPARISON_A_CONTENT,
            action="unchanged",
            card_id="comparison-1",
        )
        base_title = "基础词义｜甲"
        base = card(
            base_title,
            "base",
            f"[P#H1#{base_title}]\n---\n[Card#ID/mkjr_wrong#{COMPARISON_A}]",
        )
        snapshot = live_deck(
            [
                live_card(
                    "comparison-1",
                    COMPARISON_A,
                    "comparison",
                    COMPARISON_A_CONTENT,
                    "mkjr_actual",
                )
            ]
        )
        client = FakeClient(snapshot)

        with self.assertRaisesRegex(RuntimeError, "root reference mapping"):
            execute_release(
                client,
                manifest(snapshot, [comparison, base]),
                [comparison, base],
                MemoryJournal(),
                no_wait,
            )

        self.assertFalse(
            any(call[0] == "create" and call[1] == ROUTES["base"] for call in client.post_calls)
        )

    def test_duplicate_live_root_ids_fail_before_post(self):
        cards = [
            card(COMPARISON_A, "comparison", COMPARISON_A_CONTENT),
            card(COMPARISON_B, "comparison", COMPARISON_B_CONTENT),
        ]
        live = live_deck(
            [
                live_card("a", COMPARISON_A, "comparison", COMPARISON_A_CONTENT, "mkjr_shared"),
                live_card("b", COMPARISON_B, "comparison", COMPARISON_B_CONTENT, "mkjr_shared"),
            ]
        )
        client = FakeClient(live)
        with self.assertRaisesRegex(RuntimeError, "duplicate live root id"):
            execute_release(client, manifest(live_deck(), cards), cards, MemoryJournal(), no_wait)
        self.assertEqual([], client.post_calls)

    def test_exact_content_wrong_frozen_card_id_never_skips(self):
        title = "基础词义｜甲"
        desired = f"[P#H1#{title}]\n---\n新内容"
        frozen_live = live_deck([live_card("planned-id", title, "base", "[P#H1#基础词义｜甲]\n---\n旧内容")])
        replacement = live_deck([live_card("replacement-id", title, "base", desired)])
        expected = card(title, "base", desired, action="update", card_id="planned-id")
        client = FakeClient(replacement)
        with self.assertRaisesRegex(RuntimeError, "card id drift"):
            execute_release(
                client,
                manifest(frozen_live, [expected]),
                [expected],
                MemoryJournal(),
                no_wait,
            )
        self.assertEqual([], client.post_calls)

    def test_receipt_validator_accepts_only_exact_strict_bound_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            receipt_path = Path(temporary) / "receipt.json"
            receipt_value = receipt()
            receipt_path.write_text(json.dumps(receipt_value), encoding="utf-8")
            invalid = [None, False, 0, "", [], {"ok": True}, {"ok": True, "value": float("nan")}]
            cyclic = {"ok": True}
            cyclic["cycle"] = cyclic
            invalid.append(cyclic)
            for value in invalid:
                with self.subTest(value_type=type(value).__name__):
                    module = SimpleNamespace(
                        validate_release_environment=lambda manifest_value, receipt_value, value=value: value
                    )
                    with patch(
                        "maimemo_learning_rebuild.release_writer._release_environment_module",
                        return_value=module,
                    ):
                        with self.assertRaisesRegex(RuntimeError, "not approved"):
                            _validate_release_environment(validation_manifest(), receipt_path)

            module = SimpleNamespace(
                validate_release_environment=lambda manifest_value, receipt_value: successful_validation(receipt_value)
            )
            with (
                patch.dict(os.environ, {"GITHUB_RUN_ID": "123"}, clear=False),
                patch(
                    "maimemo_learning_rebuild.release_writer._release_environment_module",
                    return_value=module,
                ),
            ):
                result = _validate_release_environment(validation_manifest(), receipt_path)
            self.assertTrue(result["ok"])

    def test_malformed_validator_result_never_constructs_client(self):
        with tempfile.TemporaryDirectory() as temporary:
            receipt_path = Path(temporary) / "receipt.json"
            receipt_path.write_text(json.dumps(receipt()), encoding="utf-8")
            module = SimpleNamespace(
                validate_release_environment=lambda manifest_value, receipt_value: None
            )
            args = [
                "--release-dir", temporary,
                "--approval-receipt", str(receipt_path),
                "--journal", str(Path(temporary) / "journal.jsonl"),
            ]
            with (
                patch(
                    "maimemo_learning_rebuild.release_writer._load_frozen_release",
                    return_value=(validation_manifest(), []),
                ),
                patch(
                    "maimemo_learning_rebuild.release_writer._release_environment_module",
                    return_value=module,
                ),
                patch(
                    "maimemo_learning_rebuild.release_writer._create_protected_client"
                ) as construct,
                patch("sys.stderr", new=io.StringIO()),
            ):
                self.assertEqual(1, main(args))
            construct.assert_not_called()

    def test_frozen_structure_is_fully_validated_before_post(self):
        title = "语境应用｜甲、乙｜差别"
        valid = f"[P#H1#{title}]\n---\n练习"
        malformed = (
            (card(title, "application", valid.replace(title, "语境应用｜错误")), "content title"),
            ({**card(title, "application", valid), "stable_card_key": "application:wrong"}, "stable card key"),
            (card(title, "application", valid + " {{root:不存在}}"), "root placeholder"),
            (card(title, "application", valid + " {{root:不存在"), "root placeholder"),
            (card(title, "application", valid + " [Card#ID/mkjr_#坏引用]"), "root reference"),
        )
        for expected, error in malformed:
            with self.subTest(error=error):
                client = FakeClient(live_deck())
                with self.assertRaisesRegex(RuntimeError, error):
                    execute_release(
                        client,
                        manifest(live_deck(), [expected]),
                        [expected],
                        MemoryJournal(),
                        no_wait,
                    )
                self.assertEqual([], client.post_calls)

    def test_every_post_has_release_wide_drift_gate(self):
        app_title = "语境应用｜甲、乙｜差别"
        app_content = f"[P#H1#{app_title}]\n---\n练习"
        base_title = "基础词义｜甲"
        old_base = f"[P#H1#{base_title}]\n---\n旧"
        new_base = f"[P#H1#{base_title}]\n---\n新"
        snapshot = live_deck([live_card("base-1", base_title, "base", old_base)])
        cards = [
            card(app_title, "application", app_content),
            card(base_title, "base", new_base, action="update", card_id="base-1"),
        ]

        def drift_base(deck):
            next(value for value in deck["cards"] if value["id"] == "base-1")["content"] += "外部漂移"

        client = ReadMutationClient(snapshot, mutate_at=3, mutation=drift_base)
        with self.assertRaisesRegex(RuntimeError, "release-wide live drift"):
            execute_release(client, manifest(snapshot, cards), cards, MemoryJournal(), no_wait)
        self.assertEqual([], client.post_calls)

    def test_snapshot_and_all_runtime_inputs_must_be_strict_json(self):
        title = "语境应用｜甲、乙｜差别"
        expected = card(title, "application", f"[P#H1#{title}]\n---\n练习")
        base_manifest = manifest(live_deck(), [expected])
        missing_snapshot = copy.deepcopy(base_manifest)
        missing_snapshot.pop("snapshot")
        cyclic_manifest = copy.deepcopy(base_manifest)
        cyclic_manifest["cycle"] = cyclic_manifest
        nan_manifest = copy.deepcopy(base_manifest)
        nan_manifest["nan"] = float("nan")
        cyclic_cards = [expected]
        cyclic_cards.append(cyclic_cards)
        nan_snapshot = copy.deepcopy(base_manifest)
        nan_snapshot["snapshot"]["nan"] = float("nan")
        cases = (
            (missing_snapshot, [expected], "snapshot is required"),
            (cyclic_manifest, [expected], "manifest is not strict JSON"),
            (nan_manifest, [expected], "manifest is not strict JSON"),
            (base_manifest, cyclic_cards, "cards are not strict JSON"),
            (nan_snapshot, [expected], "snapshot is not strict JSON"),
        )
        for manifest_value, cards_value, error in cases:
            with self.subTest(error=error):
                client = FakeClient(live_deck())
                with self.assertRaisesRegex(RuntimeError, error):
                    execute_release(
                        client,
                        manifest_value,
                        cards_value,
                        MemoryJournal(),
                        no_wait,
                    )
                self.assertEqual([], client.post_calls)

    def test_public_execute_rejects_malformed_manifest_cards_and_snapshot(self):
        title = "语境应用｜甲、乙｜差别"
        content = f"[P#H1#{title}]\n---\n练习"
        expected = card(title, "application", content)
        base_snapshot = live_deck()
        base_manifest = manifest(base_snapshot, [expected])

        missing_release_id = copy.deepcopy(base_manifest)
        missing_release_id.pop("release_id")
        malformed_deck = copy.deepcopy(base_manifest)
        malformed_deck["deck"].pop("name")
        malformed_counts = copy.deepcopy(base_manifest)
        malformed_counts["chapter_routes"]["application"]["counts"]["create"] = 0
        duplicate_card_ids = [
            card(title, "application", content, action="update", card_id="same"),
            card(
                "基础词义｜甲",
                "base",
                "[P#H1#基础词义｜甲]\n---\n定义",
                action="update",
                card_id="same",
            ),
        ]
        malformed_snapshot = copy.deepcopy(base_manifest)
        malformed_snapshot["snapshot"]["chapters"] = {"not": "a list"}
        cases = (
            (missing_release_id, [expected], "release id"),
            (malformed_deck, [expected], "manifest deck"),
            (malformed_counts, [expected], "manifest route counts"),
            (manifest(base_snapshot, duplicate_card_ids), duplicate_card_ids, "duplicate frozen card id"),
            (malformed_snapshot, [expected], "snapshot chapters"),
        )
        for manifest_value, cards_value, error in cases:
            with self.subTest(error=error):
                client = FakeClient(base_snapshot)
                with self.assertRaisesRegex(RuntimeError, error):
                    execute_release(
                        client,
                        manifest_value,
                        cards_value,
                        MemoryJournal(),
                        no_wait,
                    )
                self.assertEqual([], client.post_calls)

    def test_duplicate_ids_and_missing_live_identity_fail_closed(self):
        title = "语境应用｜甲、乙｜差别"
        content = f"[P#H1#{title}]\n---\n练习"
        expected = card(title, "application", content)
        cases = []
        duplicate_cards = live_deck([live_card("same", title, "application", content)])
        duplicate_cards["cards"].append(copy.deepcopy(duplicate_cards["cards"][0]))
        cases.append((duplicate_cards, "duplicate live card id"))
        duplicate_chapters = live_deck()
        duplicate_chapters["chapters"].append(copy.deepcopy(duplicate_chapters["chapters"][0]))
        cases.append((duplicate_chapters, "duplicate live chapter id"))
        missing_id = live_deck()
        missing_id.pop("id")
        cases.append((missing_id, "live deck id"))
        missing_name = live_deck()
        missing_name.pop("name")
        cases.append((missing_name, "live deck name"))
        for live, error in cases:
            with self.subTest(error=error):
                client = FakeClient(live)
                with self.assertRaisesRegex(RuntimeError, error):
                    execute_release(
                        client,
                        manifest(live_deck(), [expected]),
                        [expected],
                        MemoryJournal(),
                        no_wait,
                    )
                self.assertEqual([], client.post_calls)

    def test_api_response_json_is_strict(self):
        for payload in (b'{"data":{},"data":{}}', b'{"data":NaN}'):
            for method, error_type in (
                ("GET", PermanentApiError),
                ("POST", AmbiguousMutationError),
            ):
                with self.subTest(payload=payload, method=method):
                    with patch("urllib.request.urlopen", return_value=io.BytesIO(payload)):
                        with self.assertRaises(error_type):
                            UrllibTransport().request(method, "https://example.invalid", {})

    def test_retry_after_must_be_finite_and_bounded(self):
        for value in ("Infinity", "NaN", "1e9999", "3601"):
            headers = Message()
            headers["Retry-After"] = value
            error = urllib.error.HTTPError(
                "https://example.invalid", 429, "limited", headers, None
            )
            with self.subTest(value=value):
                with patch("urllib.request.urlopen", side_effect=error):
                    with self.assertRaises(PermanentApiError):
                        UrllibTransport().request("POST", "https://example.invalid", {})

        headers = Message()
        headers["Retry-After"] = "3600"
        error = urllib.error.HTTPError(
            "https://example.invalid", 429, "limited", headers, None
        )
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(RateLimitError) as caught:
                UrllibTransport().request("POST", "https://example.invalid", {})
        self.assertEqual(3600, caught.exception.retry_after_seconds)

    def test_bounded_retry_after_still_checks_cancellation_before_retry(self):
        title = "语境应用｜甲、乙｜差别"
        content = f"[P#H1#{title}]\n---\n练习"
        expected = card(title, "application", content)
        snapshot = live_deck()
        client = BoundedRateLimitClient(snapshot)
        policy = CancelAfterWaitPolicy()

        with self.assertRaisesRegex(RuntimeError, "release cancelled"):
            execute_release(
                client,
                manifest(snapshot, [expected]),
                [expected],
                MemoryJournal(),
                policy,
            )

        self.assertEqual([3600], policy.waits)
        self.assertEqual(1, client.create_attempts)


if __name__ == "__main__":
    unittest.main()
