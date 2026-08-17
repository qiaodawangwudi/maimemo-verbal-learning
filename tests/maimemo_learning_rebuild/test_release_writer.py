import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from maimemo_learning_rebuild.api import (
    AmbiguousMutationError,
    RateLimitError,
)
from maimemo_learning_rebuild.release_writer import (
    TYPE_PREFIXES,
    _is_link_or_reparse,
    _load_frozen_release,
    execute_release,
    main,
)
from maimemo_learning_rebuild.release_journal import ReleaseJournal
from tests.maimemo_learning_rebuild.test_release_manifest import (
    artifacts as release_artifacts,
    complete_manifest,
)


ROUTES = {
    "comparison": "chapter-comparison",
    "base": "chapter-base",
    "application": "chapter-application",
}

FROZEN_FILENAMES = {
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


def write_frozen_release(release_dir):
    release_dir.mkdir(parents=True)
    current_artifacts = release_artifacts()
    (release_dir / "release_manifest.json").write_text(
        json.dumps(complete_manifest(), ensure_ascii=False), encoding="utf-8"
    )
    for key, raw in current_artifacts.items():
        (release_dir / FROZEN_FILENAMES[key]).write_bytes(raw)


def card(title, card_type, content, *, action="create", card_id=""):
    suffix = title.removeprefix(TYPE_PREFIXES[card_type]).replace("｜", ":")
    return {
        "stable_card_key": f"{card_type}:{suffix}",
        "title": title,
        "card_type": card_type,
        "action": action,
        "card_id": card_id,
        "content": content,
    }


def live_deck(cards=()):
    values = [copy.deepcopy(value) for value in cards]
    chapters = []
    for card_type, chapter_id in ROUTES.items():
        chapters.append(
            {
                "id": chapter_id,
                "name": card_type,
                "card_ids": [
                    value["id"]
                    for value in values
                    if value.get("card_type") == card_type
                ],
            }
        )
    for value in values:
        value.pop("card_type", None)
    return {"id": "deck", "name": "deck", "chapters": chapters, "cards": values}


def live_card(card_id, title, card_type, content, root_id="mkjr_root"):
    return {
        "id": card_id,
        "root_id": root_id,
        "card_type": card_type,
        "grammar_version": 3,
        "content": content,
    }


def manifest(snapshot, cards):
    counts = {
        route: {
            "before": len(
                [
                    value
                    for value in snapshot["cards"]
                    if value["id"]
                    in next(
                        chapter["card_ids"]
                        for chapter in snapshot["chapters"]
                        if chapter["id"] == ROUTES[route]
                    )
                ]
            ),
            "create": len(
                [value for value in cards if value["card_type"] == route and value["action"] == "create"]
            ),
            "update": len(
                [value for value in cards if value["card_type"] == route and value["action"] == "update"]
            ),
            "unchanged": len(
                [value for value in cards if value["card_type"] == route and value["action"] == "unchanged"]
            ),
            "after": len([value for value in cards if value["card_type"] == route]),
        }
        for route in ROUTES
    }
    return {
        "release_id": "release-1",
        "release_hash": "a" * 64,
        "deck": {"id": "deck", "name": "deck"},
        "chapter_routes": {
            route: {
                "id": chapter_id,
                "name": route,
                "type": route,
                "counts": counts[route],
            }
            for route, chapter_id in ROUTES.items()
        },
        "snapshot": copy.deepcopy(snapshot),
    }


class FakeClient:
    def __init__(self, live, *, create_effects=(), before_reads=None):
        self.live = copy.deepcopy(live)
        self.create_effects = list(create_effects)
        self.before_reads = list(before_reads or [])
        self.create_attempts = 0
        self.post_calls = []

    def read_deck(self):
        if self.before_reads:
            self.live = copy.deepcopy(self.before_reads.pop(0))
        return copy.deepcopy(self.live)

    def create_card(self, chapter_id, content, guard):
        self.create_attempts += 1
        self.post_calls.append(("create", chapter_id, content))
        effect = self.create_effects.pop(0) if self.create_effects else None
        if effect == "rate_limit":
            raise RateLimitError(7)
        new_id = f"created-{self.create_attempts}"
        title = content.split("]", 1)[0].removeprefix("[P#H1#")
        card_type = next(route for route, prefix in (
            ("comparison", "近义辨析｜"),
            ("base", "基础词义｜"),
            ("application", "语境应用｜"),
        ) if title.startswith(prefix))
        root_id = "mkjr_created" if card_type == "comparison" else f"mkjr_{new_id}"
        self.live["cards"].append(
            {
                "id": new_id,
                "root_id": root_id,
                "grammar_version": 3,
                "content": content,
            }
        )
        chapter = next(item for item in self.live["chapters"] if item["id"] == chapter_id)
        chapter["card_ids"].append(new_id)
        if effect == "timeout_after_commit":
            raise AmbiguousMutationError("connection timed out")
        return {"id": new_id}

    def update_card(self, card_id, content, guard):
        self.post_calls.append(("update", card_id, content))
        target = next(value for value in self.live["cards"] if value["id"] == card_id)
        target["content"] = content
        return {"id": card_id}


class FinalRootDriftClient(FakeClient):
    def __init__(self, live):
        super().__init__(live)
        self.reads = 0

    def read_deck(self):
        self.reads += 1
        if self.reads == 7:
            comparison = next(
                value
                for value in self.live["cards"]
                if value["content"].startswith("[P#H1#近义辨析｜")
            )
            comparison["root_id"] = "mkjr_drifted"
        return super().read_deck()


class MemoryJournal:
    def __init__(self, *, available=True):
        self.available = available
        self.entries = []

    def acquire(self):
        return self.available

    def release(self):
        return None

    def record(self, entry):
        self.entries.append(copy.deepcopy(entry))


class WaitPolicy:
    def __init__(self, *, cancelled=False):
        self.cancelled_value = cancelled
        self.waits = []

    def cancelled(self):
        return self.cancelled_value

    def wait(self, seconds):
        self.waits.append(seconds)


def no_wait(seconds=0):
    return None


class ReleaseWriterTests(unittest.TestCase):
    def test_windows_reparse_metadata_is_treated_as_link(self):
        with (
            patch(
                "maimemo_learning_rebuild.release_writer.os.lstat",
                return_value=SimpleNamespace(st_file_attributes=0x400),
            ),
            patch.object(Path, "is_symlink", return_value=False),
        ):
            self.assertTrue(_is_link_or_reparse(Path("release-junction")))

    def test_loader_checks_release_root_and_artifact_for_reparse_points(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release_dir = root / "releases" / "release-1"
            write_frozen_release(release_dir)
            real_check = _is_link_or_reparse

            for blocked_name in ("releases", "final_cards.json"):
                with self.subTest(blocked_name=blocked_name), patch(
                    "maimemo_learning_rebuild.release_writer._is_link_or_reparse",
                    side_effect=lambda path, blocked_name=blocked_name: (
                        Path(path).name == blocked_name or real_check(path)
                    ),
                ), self.assertRaisesRegex(
                    RuntimeError, "symbolic link|reparse point"
                ):
                    _load_frozen_release(release_dir)

    def _symlink_or_skip(self, target, link, *, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"symbolic links unavailable: {error}")

    def test_frozen_loader_rejects_symlinked_releases_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside"
            write_frozen_release(outside / "release-1")
            repository = root / "repository"
            repository.mkdir()
            self._symlink_or_skip(outside, repository / "releases", directory=True)

            with self.assertRaisesRegex(RuntimeError, "symbolic link|reparse point"):
                _load_frozen_release(repository / "releases" / "release-1")

    def test_frozen_loader_rejects_artifact_symlink_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release_dir = root / "releases" / "release-1"
            write_frozen_release(release_dir)
            artifact = release_dir / "final_cards.json"
            outside = root / "outside-final-cards.json"
            artifact.replace(outside)
            self._symlink_or_skip(outside, artifact)

            with self.assertRaisesRegex(RuntimeError, "symbolic link|reparse point"):
                _load_frozen_release(release_dir)

    def test_frozen_loader_rejects_manifest_symlink_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release_dir = root / "releases" / "release-1"
            write_frozen_release(release_dir)
            manifest = release_dir / "release_manifest.json"
            outside = root / "outside-release-manifest.json"
            manifest.replace(outside)
            self._symlink_or_skip(outside, manifest)

            with self.assertRaisesRegex(RuntimeError, "symbolic link|reparse point"):
                _load_frozen_release(release_dir)

    def test_final_readback_rejects_root_drift_after_base_write(self):
        comparison_title = "近义辨析｜甲、乙"
        comparison_content = "[P#H1#近义辨析｜甲、乙]\n---\n辨析"
        base_content = (
            "[P#H1#基础词义｜甲]\n---\n"
            "[Card#ID/{{root:近义辨析｜甲、乙}}#近义辨析｜甲、乙]"
        )
        cards = [
            card(comparison_title, "comparison", comparison_content),
            card("基础词义｜甲", "base", base_content),
        ]
        snapshot = live_deck()

        result = execute_release(
            FinalRootDriftClient(snapshot),
            manifest(snapshot, cards),
            cards,
            MemoryJournal(),
            no_wait,
        )

        self.assertFalse(result["final_readback"]["ok"])
        self.assertIn(
            "missing root reference target: 基础词义｜甲 mkjr_created",
            result["final_readback"]["errors"],
        )

    def test_cli_rejects_token_and_local_approval_options(self):
        required = [
            "--release-dir",
            "release",
            "--approval-receipt",
            "receipt.json",
            "--journal",
            "journal.jsonl",
        ]
        for prohibited in ("--token", "--local-approval"):
            with self.subTest(prohibited=prohibited):
                with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                    main(required + [prohibited, "secret"])

    def test_cli_validates_github_receipt_before_protected_client_and_fails_readback(self):
        events = []
        fake_manifest = {"release_hash": "a" * 64, "deck": {"id": "deck"}}
        fake_result = {"final_readback": {"ok": False, "errors": ["mismatch"]}}
        arguments = [
            "--release-dir",
            "release",
            "--approval-receipt",
            "receipt.json",
            "--journal",
            "journal.jsonl",
        ]

        def validate(manifest_value, receipt_path):
            events.append("validated")
            return {"ok": True}

        def validate_quality(release_dir):
            events.append("quality")
            return object()

        def construct(manifest_value, validation, quality_capability):
            events.append("client")
            return object()

        with (
            patch(
                "maimemo_learning_rebuild.release_writer._load_frozen_release",
                return_value=(fake_manifest, []),
            ),
            patch(
                "maimemo_learning_rebuild.release_writer._validate_release_environment",
                side_effect=validate,
            ),
            patch(
                "maimemo_learning_rebuild.release_writer._validate_protected_release_quality",
                side_effect=validate_quality,
                create=True,
            ),
            patch(
                "maimemo_learning_rebuild.release_writer._create_protected_client",
                side_effect=construct,
            ),
            patch(
                "maimemo_learning_rebuild.release_writer.execute_release",
                return_value=fake_result,
            ),
            redirect_stdout(StringIO()),
        ):
            exit_code = main(arguments)

        self.assertEqual(["validated", "quality", "client"], events)
        self.assertEqual(1, exit_code)

    def test_cli_validation_failure_never_constructs_client_and_redacts_token(self):
        arguments = [
            "--release-dir",
            "release",
            "--approval-receipt",
            "receipt.json",
            "--journal",
            "journal.jsonl",
        ]
        error_output = StringIO()
        with (
            patch.dict(os.environ, {"MAIMEMO_API_TOKEN": "secret-token"}, clear=False),
            patch(
                "maimemo_learning_rebuild.release_writer._load_frozen_release",
                return_value=({"release_hash": "a" * 64}, []),
            ),
            patch(
                "maimemo_learning_rebuild.release_writer._validate_release_environment",
                side_effect=RuntimeError("invalid secret-token"),
            ),
            patch(
                "maimemo_learning_rebuild.release_writer._create_protected_client"
            ) as construct,
            redirect_stderr(error_output),
        ):
            exit_code = main(arguments)

        self.assertEqual(1, exit_code)
        construct.assert_not_called()
        self.assertNotIn("secret-token", error_output.getvalue())
        self.assertIn("[REDACTED]", error_output.getvalue())

    def test_quality_authorization_failure_never_constructs_client(self):
        arguments = [
            "--release-dir",
            "release",
            "--approval-receipt",
            "receipt.json",
            "--journal",
            "journal.jsonl",
        ]
        with (
            patch(
                "maimemo_learning_rebuild.release_writer._load_frozen_release",
                return_value=({"release_hash": "a" * 64}, []),
            ),
            patch(
                "maimemo_learning_rebuild.release_writer._validate_release_environment",
                return_value={"ok": True},
            ),
            patch(
                "maimemo_learning_rebuild.release_writer._validate_protected_release_quality",
                side_effect=RuntimeError("forged review authority"),
                create=True,
            ),
            patch(
                "maimemo_learning_rebuild.release_writer._create_protected_client"
            ) as construct,
            redirect_stderr(StringIO()),
        ):
            exit_code = main(arguments)

        self.assertEqual(1, exit_code)
        construct.assert_not_called()

    def test_frozen_loader_rejects_byte_drift(self):
        file_names = {
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
        with tempfile.TemporaryDirectory() as temporary:
            release_dir = Path(temporary)
            current_artifacts = release_artifacts()
            (release_dir / "release_manifest.json").write_text(
                json.dumps(complete_manifest(), ensure_ascii=False), encoding="utf-8"
            )
            for key, raw in current_artifacts.items():
                (release_dir / file_names[key]).write_bytes(raw)

            loaded_manifest, loaded_cards = _load_frozen_release(release_dir)
            self.assertEqual("release-2026-08-17-001", loaded_manifest["release_id"])
            self.assertNotIn("snapshot", loaded_manifest)
            self.assertIsInstance(loaded_cards.snapshot, dict)
            self.assertEqual(4, len(loaded_cards))

            (release_dir / "final_cards.json").write_bytes(
                current_artifacts["final_cards"] + b"\n"
            )
            with self.assertRaisesRegex(RuntimeError, "artifact byte hash mismatch"):
                _load_frozen_release(release_dir)

    def test_file_journal_excludes_unknown_fields_and_rejects_concurrent_owner(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "release.jsonl"
            first = ReleaseJournal(path)
            second = ReleaseJournal(path)

            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            with self.assertRaisesRegex(ValueError, "journal fields"):
                first.record({"title": "safe", "authorization": "secret"})
            first.record(
                {
                    "release_hash": "a" * 64,
                    "title": "precheck",
                    "action": "phase",
                    "outcome": "started",
                    "timestamp": "2026-08-18T00:00:00Z",
                    "github_run_id": "123",
                }
            )
            first.release()

            self.assertTrue(second.acquire())
            second.release()
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual("precheck", rows[0]["title"])
            self.assertNotIn("authorization", rows[0])

    def test_stale_lock_file_does_not_block_crash_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "release.jsonl"
            path.with_name(path.name + ".lock").write_text(
                "stale-owner", encoding="ascii"
            )
            journal = ReleaseJournal(path)

            self.assertTrue(journal.acquire())
            journal.release()

    def test_no_post_when_snapshot_drifted(self):
        title = "基础词义｜甲"
        frozen = "[P#H1#基础词义｜甲]\n---\n旧内容"
        changed = "[P#H1#基础词义｜甲]\n---\n外部改动"
        expected = card(title, "base", frozen, action="unchanged", card_id="base-1")
        snapshot = live_deck([live_card("base-1", title, "base", frozen)])
        client = FakeClient(live_deck([live_card("base-1", title, "base", changed)]))

        with self.assertRaisesRegex(RuntimeError, "release target snapshot is stale"):
            execute_release(client, manifest(snapshot, [expected]), [expected], MemoryJournal(), no_wait)

        self.assertEqual([], client.post_calls)

    def test_drift_immediately_before_mutation_blocks_post(self):
        title = "语境应用｜甲、乙｜差别"
        content = "[P#H1#语境应用｜甲、乙｜差别]\n---\n练习"
        expected = card(title, "application", content)
        snapshot = live_deck()
        drifted = live_deck(
            [live_card("other", title, "application", content + "外部改动")]
        )
        client = FakeClient(snapshot, before_reads=[snapshot, drifted])

        with self.assertRaisesRegex(RuntimeError, "live content drift before mutation"):
            execute_release(client, manifest(snapshot, [expected]), [expected], MemoryJournal(), no_wait)

        self.assertEqual([], client.post_calls)

    def test_timeout_after_success_reads_before_retry(self):
        title = "近义辨析｜甲、乙"
        content = "[P#H1#近义辨析｜甲、乙]\n---\n辨析"
        expected = card(title, "comparison", content)
        snapshot = live_deck()
        client = FakeClient(snapshot, create_effects=["timeout_after_commit"])

        result = execute_release(
            client, manifest(snapshot, [expected]), [expected], MemoryJournal(), no_wait
        )

        self.assertEqual(1, client.create_attempts)
        self.assertEqual(1, result["recovered_after_ambiguous_response"])

    def test_same_title_same_content_skips_and_different_content_blocks(self):
        title = "语境应用｜甲、乙｜差别"
        content = "[P#H1#语境应用｜甲、乙｜差别]\n---\n练习"
        expected = card(title, "application", content)
        snapshot = live_deck()
        exact_client = FakeClient(
            live_deck([live_card("existing", title, "application", content)])
        )

        result = execute_release(
            exact_client,
            manifest(snapshot, [expected]),
            [expected],
            MemoryJournal(),
            no_wait,
        )

        self.assertEqual(1, result["already_present"])
        self.assertEqual([], exact_client.post_calls)

        differing_client = FakeClient(
            live_deck([live_card("existing", title, "application", content + "不同")])
        )
        with self.assertRaisesRegex(RuntimeError, "same title has different content"):
            execute_release(
                differing_client,
                manifest(snapshot, [expected]),
                [expected],
                MemoryJournal(),
                no_wait,
            )
        self.assertEqual([], differing_client.post_calls)

    def test_invalid_comparison_root_id_blocks_base_phase(self):
        comparison_title = "近义辨析｜甲、乙"
        comparison_content = "[P#H1#近义辨析｜甲、乙]\n---\n辨析"
        base_content = (
            "[P#H1#基础词义｜甲]\n---\n"
            "[Card#ID/{{root:近义辨析｜甲、乙}}#近义辨析｜甲、乙]"
        )
        cards = [
            card(comparison_title, "comparison", comparison_content),
            card("基础词义｜甲", "base", base_content),
        ]
        snapshot = live_deck()
        live = live_deck(
            [
                live_card(
                    "comparison-1",
                    comparison_title,
                    "comparison",
                    comparison_content,
                    root_id="bad-root",
                )
            ]
        )
        client = FakeClient(snapshot, before_reads=[snapshot, snapshot, live])

        with self.assertRaisesRegex(RuntimeError, "invalid comparison root_id"):
            execute_release(client, manifest(snapshot, cards), cards, MemoryJournal(), no_wait)

        self.assertFalse(any(call[0] == "create" and call[1] == ROUTES["base"] for call in client.post_calls))

    def test_rate_limit_uses_retry_after_and_then_retries(self):
        title = "语境应用｜甲、乙｜差别"
        content = "[P#H1#语境应用｜甲、乙｜差别]\n---\n练习"
        expected = card(title, "application", content)
        snapshot = live_deck()
        client = FakeClient(snapshot, create_effects=["rate_limit", None])
        policy = WaitPolicy()

        execute_release(
            client, manifest(snapshot, [expected]), [expected], MemoryJournal(), policy
        )

        self.assertEqual([7], policy.waits)
        self.assertEqual(2, client.create_attempts)

    def test_cancellation_and_concurrent_writer_reject_before_mutation(self):
        title = "语境应用｜甲、乙｜差别"
        content = "[P#H1#语境应用｜甲、乙｜差别]\n---\n练习"
        expected = card(title, "application", content)
        snapshot = live_deck()
        cases = (
            (MemoryJournal(), WaitPolicy(cancelled=True), "release cancelled"),
            (MemoryJournal(available=False), WaitPolicy(), "release writer is already running"),
        )
        for journal, policy, error in cases:
            with self.subTest(error=error):
                client = FakeClient(snapshot)
                with self.assertRaisesRegex(RuntimeError, error):
                    execute_release(
                        client, manifest(snapshot, [expected]), [expected], journal, policy
                    )
                self.assertEqual([], client.post_calls)

    def test_records_exact_phase_order_and_only_non_secret_fields(self):
        journal = MemoryJournal()
        snapshot = live_deck()

        execute_release(client=FakeClient(snapshot), manifest=manifest(snapshot, []), cards=[], journal=journal, wait_policy=no_wait)

        phase_entries = [entry for entry in journal.entries if entry["action"] == "phase"]
        self.assertEqual(
            [
                "precheck",
                "comparisons",
                "root_readback",
                "bases",
                "applications",
                "final_readback",
            ],
            [entry["title"] for entry in phase_entries],
        )
        allowed = {
            "release_hash",
            "title",
            "action",
            "stable_card_key",
            "card_type",
            "chapter_id",
            "chapter_name",
            "card_id",
            "root_id",
            "content_hash",
            "outcome",
            "timestamp",
            "github_run_id",
        }
        self.assertTrue(all(set(entry) <= allowed for entry in journal.entries))


if __name__ == "__main__":
    unittest.main()
