import importlib.util
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = (
    REPO_ROOT / "skills" / "verbal-maimemo-cards" / "scripts" / "install_or_verify.py"
)
SKILL_ROOT = REPO_ROOT / "skills" / "verbal-maimemo-cards"
RECEIPT_NAME = ".install-receipt.json"


def load_installer():
    if not SCRIPT_PATH.is_file():
        raise AssertionError(f"installer script absent: {SCRIPT_PATH}")
    spec = importlib.util.spec_from_file_location("verbal_maimemo_skill_installer", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def prepared_skill_dirs(root, *, existing_target=False):
    source = root / "canonical-skill"
    target = root / "installed-skill"
    (source / "agents").mkdir(parents=True)
    (source / "SKILL.md").write_text("canonical skill\n", encoding="utf-8")
    (source / "agents" / "openai.yaml").write_bytes(b"name: canonical\n")
    if existing_target:
        target.mkdir()
    return source, target


class SkillInstallerContractTests(unittest.TestCase):
    def test_module_exposes_install_hash_and_verify_contract(self):
        module = load_installer()

        for name in ("compute_skill_hash", "verify_install", "install", "main"):
            self.assertTrue(callable(getattr(module, name, None)), name)


class SkillHashTests(unittest.TestCase):
    def setUp(self):
        self.module = load_installer()

    def test_hash_frames_sorted_normalized_relative_paths_and_file_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "nested").mkdir()
            (root / "nested" / "b.bin").write_bytes(b"\x00\xff")
            (root / "a.txt").write_bytes(b"alpha")

            self.assertEqual(
                "451153603d50513a098569af465496fdb5b35ed670e64c3ba63d0042e1088776",
                self.module.compute_skill_hash(root),
            )

    def test_hash_excludes_only_known_cache_artifacts_and_install_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "content.txt").write_text("content", encoding="utf-8")
            original = self.module.compute_skill_hash(root)

            (root / RECEIPT_NAME).write_text("receipt one", encoding="utf-8")
            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "module.pyc").write_bytes(b"cache one")
            (root / ".pytest_cache").mkdir()
            (root / ".pytest_cache" / "state").write_bytes(b"cache two")
            self.assertEqual(original, self.module.compute_skill_hash(root))

            (root / ".ordinary-hidden-file").write_bytes(b"must be hashed")
            self.assertNotEqual(original, self.module.compute_skill_hash(root))

    def test_hash_refuses_symlinks_instead_of_following_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "outside.txt").write_text("outside", encoding="utf-8")
            skill = root / "skill"
            skill.mkdir()
            try:
                (skill / "linked.txt").symlink_to(root / "outside.txt")
            except OSError as error:
                outside = root / "outside-directory"
                outside.mkdir()
                junction = skill / "linked-directory"
                created = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                    capture_output=True,
                    text=True,
                )
                if created.returncode:
                    self.skipTest(f"symlinks and junctions unavailable: {error}")

            with self.assertRaisesRegex(RuntimeError, "symlink or reparse point"):
                self.module.compute_skill_hash(skill)

    def test_hash_rejects_casefold_portability_collisions(self):
        tested = False
        for first, second in (("A.txt", "a.txt"), ("straße.txt", "STRASSE.txt")):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / first).write_bytes(b"first")
                (root / second).write_bytes(b"second")
                if len(list(root.iterdir())) == 2:
                    with self.assertRaisesRegex(RuntimeError, "portable path collision"):
                        self.module.compute_skill_hash(root)
                    tested = True
                    break
        self.assertTrue(tested, "no casefold collision fixture was representable")

    def test_hash_rejects_nfc_portability_collision(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "é.txt").write_bytes(b"first")
            (root / "e\u0301.txt").write_bytes(b"second")
            if len(list(root.iterdir())) != 2:
                self.skipTest("filesystem collapsed the NFC collision fixture")
            with self.assertRaisesRegex(RuntimeError, "portable path collision"):
                self.module.compute_skill_hash(root)


class SkillInstallTests(unittest.TestCase):
    def setUp(self):
        self.module = load_installer()

    def test_atomic_first_install_matches_canonical_hash_and_strict_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = prepared_skill_dirs(Path(temporary))

            receipt = self.module.install(source, target)

            expected_hash = self.module.compute_skill_hash(source)
            self.assertEqual(expected_hash, self.module.compute_skill_hash(target))
            self.assertEqual(
                {
                    "schema_version",
                    "canonical_hash",
                    "installed_hash",
                    "merged_commit",
                    "source_identity",
                    "backup_retained",
                    "backup_path",
                    "backup_installed_hash",
                    "backup_receipt_sha256",
                    "backup_directory_identity",
                    "directory_flush_mode",
                },
                set(receipt),
            )
            self.assertEqual(expected_hash, receipt["canonical_hash"])
            self.assertEqual(expected_hash, receipt["installed_hash"])
            self.assertEqual(str(source.resolve()), receipt["source_identity"])
            self.assertIsNone(receipt["merged_commit"])
            self.assertFalse(receipt["backup_retained"])
            self.assertIsNone(receipt["backup_path"])
            self.assertIsNone(receipt["backup_installed_hash"])
            self.assertIsNone(receipt["backup_receipt_sha256"])
            self.assertIsNone(receipt["backup_directory_identity"])
            self.assertIn(receipt["directory_flush_mode"], {"required", "best_effort"})
            self.assertEqual(
                receipt,
                json.loads((target / RECEIPT_NAME).read_text(encoding="utf-8")),
            )

    def test_install_records_repository_merged_commit_without_installing_personally(self):
        expected_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "installed-skill"

            receipt = self.module.install(SKILL_ROOT, target)

            self.assertEqual(expected_commit, receipt["merged_commit"])
            self.assertEqual(str(SKILL_ROOT.resolve()), receipt["source_identity"])

    def test_first_install_refuses_every_existing_unrecorded_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = prepared_skill_dirs(Path(temporary), existing_target=True)

            with self.assertRaisesRegex(RuntimeError, "existing target has no valid receipt"):
                self.module.install(source, target)

            self.assertEqual([], list(target.iterdir()))

    def test_refuses_unrecorded_target_change_and_preserves_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = prepared_skill_dirs(Path(temporary))
            self.module.install(source, target)
            changed = target / "SKILL.md"
            changed.write_text("locally changed", encoding="utf-8")

            with self.assertRaisesRegex(
                RuntimeError, "installed skill has unrecorded changes"
            ):
                self.module.install(source, target)

            self.assertEqual("locally changed", changed.read_text(encoding="utf-8"))

    def test_recorded_unchanged_target_can_be_replaced_by_new_canonical_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = prepared_skill_dirs(Path(temporary))
            first = self.module.install(source, target)
            (source / "SKILL.md").write_text("canonical skill v2\n", encoding="utf-8")

            second = self.module.install(source, target)

            self.assertNotEqual(first["installed_hash"], second["installed_hash"])
            self.assertEqual("canonical skill v2\n", (target / "SKILL.md").read_text())
            self.assertEqual(second, self.module.verify_install(source, target))

    def test_failed_directory_swap_rolls_back_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = prepared_skill_dirs(Path(temporary))
            first = self.module.install(source, target)
            old_skill = (target / "SKILL.md").read_bytes()
            old_receipt = (target / RECEIPT_NAME).read_bytes()
            (source / "SKILL.md").write_text("replacement\n", encoding="utf-8")
            def fail_publish(src, dst):
                raise OSError("simulated swap failure")

            with mock.patch.object(
                self.module, "_rename_directory_noreplace", side_effect=fail_publish
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "installation failed; original restored"
                ):
                    self.module.install(source, target)

            self.assertEqual(old_skill, (target / "SKILL.md").read_bytes())
            self.assertEqual(old_receipt, (target / RECEIPT_NAME).read_bytes())
            self.assertEqual(first["installed_hash"], self.module.compute_skill_hash(target))
            leftovers = [
                path.name
                for path in target.parent.iterdir()
                if path.name.startswith((target.name + ".staging-", target.name + ".backup-"))
            ]
            self.assertEqual([], leftovers)

    def test_first_install_collision_preserves_foreign_target_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = prepared_skill_dirs(Path(temporary))
            foreign_bytes = b"foreign user data\x00\xff"

            def collide_without_moving_stage(src, dst):
                Path(dst).mkdir()
                (Path(dst) / "user.bin").write_bytes(foreign_bytes)
                raise OSError("simulated Windows destination collision")

            with mock.patch.object(
                self.module,
                "_rename_directory_noreplace",
                side_effect=collide_without_moving_stage,
            ):
                with self.assertRaisesRegex(RuntimeError, "foreign target preserved"):
                    self.module.install(source, target)

            self.assertEqual(foreign_bytes, (target / "user.bin").read_bytes())
            self.assertEqual(
                [],
                [
                    path.name
                    for path in target.parent.iterdir()
                    if path.name.startswith(
                        (target.name + ".staging-", target.name + ".failed-")
                    )
                ],
            )

    def test_replacement_collision_preserves_foreign_target_and_recorded_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = prepared_skill_dirs(Path(temporary))
            self.module.install(source, target)
            old_skill = (target / "SKILL.md").read_bytes()
            (source / "SKILL.md").write_text("replacement\n", encoding="utf-8")
            def collide_after_backup(src, dst):
                Path(dst).mkdir()
                (Path(dst) / "user.bin").write_bytes(b"foreign replacement target")
                raise OSError("simulated Windows destination collision")

            with mock.patch.object(
                self.module,
                "_rename_directory_noreplace",
                side_effect=collide_after_backup,
            ):
                with self.assertRaisesRegex(RuntimeError, "foreign target preserved"):
                    self.module.install(source, target)

            self.assertEqual(
                b"foreign replacement target", (target / "user.bin").read_bytes()
            )
            backups = [
                path
                for path in target.parent.iterdir()
                if path.name.startswith(target.name + ".backup-")
            ]
            self.assertEqual(1, len(backups))
            self.assertEqual(old_skill, (backups[0] / "SKILL.md").read_bytes())

    def test_atomic_noreplace_preserves_first_install_foreign_empty_directory(self):
        rename_noreplace = getattr(self.module, "_rename_directory_noreplace", None)
        self.assertTrue(callable(rename_noreplace), "atomic no-replace rename is absent")
        with tempfile.TemporaryDirectory() as temporary:
            source, target = prepared_skill_dirs(Path(temporary))
            injected_identity = None
            injection_calls = 0

            def inject_empty_target(src, dst):
                nonlocal injected_identity, injection_calls
                injection_calls += 1
                Path(dst).mkdir()
                metadata = Path(dst).lstat()
                injected_identity = (metadata.st_dev, metadata.st_ino)
                return rename_noreplace(src, dst)

            with mock.patch.object(
                self.module,
                "_rename_directory_noreplace",
                side_effect=inject_empty_target,
            ):
                with self.assertRaisesRegex(RuntimeError, "foreign target preserved"):
                    self.module.install(source, target)

            self.assertGreater(injection_calls, 0)
            metadata = target.lstat()
            self.assertEqual(injected_identity, (metadata.st_dev, metadata.st_ino))
            self.assertEqual([], list(target.iterdir()))

    def test_atomic_noreplace_preserves_upgrade_foreign_empty_directory_and_backup(self):
        rename_noreplace = getattr(self.module, "_rename_directory_noreplace", None)
        self.assertTrue(callable(rename_noreplace), "atomic no-replace rename is absent")
        with tempfile.TemporaryDirectory() as temporary:
            source, target = prepared_skill_dirs(Path(temporary))
            self.module.install(source, target)
            old_skill = (target / "SKILL.md").read_bytes()
            (source / "SKILL.md").write_text("replacement\n", encoding="utf-8")
            injected_identity = None
            injection_calls = 0

            def inject_empty_target(src, dst):
                nonlocal injected_identity, injection_calls
                injection_calls += 1
                Path(dst).mkdir()
                metadata = Path(dst).lstat()
                injected_identity = (metadata.st_dev, metadata.st_ino)
                return rename_noreplace(src, dst)

            with mock.patch.object(
                self.module,
                "_rename_directory_noreplace",
                side_effect=inject_empty_target,
            ):
                with self.assertRaisesRegex(RuntimeError, "foreign target preserved"):
                    self.module.install(source, target)

            self.assertGreater(injection_calls, 0)
            metadata = target.lstat()
            self.assertEqual(injected_identity, (metadata.st_dev, metadata.st_ino))
            backups = [
                path
                for path in target.parent.iterdir()
                if path.name.startswith(target.name + ".backup-")
            ]
            self.assertEqual(1, len(backups))
            self.assertEqual(old_skill, (backups[0] / "SKILL.md").read_bytes())

    def test_rollback_rename_race_restores_foreign_target_to_exact_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = prepared_skill_dirs(Path(temporary))
            self.module.install(source, target)
            (source / "SKILL.md").write_text("replacement\n", encoding="utf-8")
            real_replace = os.replace
            replace_calls = 0
            captured_install = target.parent / "captured-installed-tree"

            def swap_foreign_target_at_rollback_rename(src, dst):
                nonlocal replace_calls
                replace_calls += 1
                if replace_calls == 2:
                    real_replace(target, captured_install)
                    target.mkdir()
                    (target / "user.bin").write_bytes(b"foreign at rollback boundary")
                return real_replace(src, dst)

            with mock.patch.object(
                self.module.os,
                "replace",
                side_effect=swap_foreign_target_at_rollback_rename,
            ), mock.patch.object(
                self.module,
                "verify_install",
                side_effect=RuntimeError("force rollback"),
            ):
                with self.assertRaisesRegex(RuntimeError, "foreign target preserved"):
                    self.module.install(source, target)

            self.assertEqual(
                b"foreign at rollback boundary", (target / "user.bin").read_bytes()
            )
            backups = [
                path
                for path in target.parent.iterdir()
                if path.name.startswith(target.name + ".backup-")
            ]
            self.assertEqual(1, len(backups))

    def test_target_change_during_swap_is_detected_and_restored(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = prepared_skill_dirs(Path(temporary))
            self.module.install(source, target)
            (source / "SKILL.md").write_text("replacement\n", encoding="utf-8")
            real_replace = os.replace
            calls = 0

            def change_old_target_after_rename(src, dst):
                nonlocal calls
                calls += 1
                result = real_replace(src, dst)
                if calls == 1:
                    (Path(dst) / "SKILL.md").write_text(
                        "concurrent local change", encoding="utf-8"
                    )
                return result

            with mock.patch.object(
                self.module.os, "replace", side_effect=change_old_target_after_rename
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "retained backup receipt mismatch"
                ):
                    self.module.install(source, target)

            self.assertEqual(
                "concurrent local change", (target / "SKILL.md").read_text(encoding="utf-8")
            )

    def test_successful_upgrade_retains_and_reports_verified_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = prepared_skill_dirs(Path(temporary))
            first = self.module.install(source, target)
            old_skill = (target / "SKILL.md").read_bytes()
            (source / "SKILL.md").write_text("replacement\n", encoding="utf-8")

            second = self.module.install(source, target)

            backup = Path(second["backup_path"])
            self.assertTrue(second["backup_retained"])
            self.assertEqual(first["installed_hash"], second["backup_installed_hash"])
            self.assertTrue(backup.is_dir())
            self.assertEqual(target.parent, backup.parent)
            self.assertEqual(old_skill, (backup / "SKILL.md").read_bytes())
            self.assertEqual(
                hashlib.sha256((backup / RECEIPT_NAME).read_bytes()).hexdigest(),
                second["backup_receipt_sha256"],
            )
            metadata = backup.lstat()
            self.assertEqual(
                f"{metadata.st_dev}:{metadata.st_ino}",
                second["backup_directory_identity"],
            )

    def test_verify_rejects_retained_backup_receipt_only_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = prepared_skill_dirs(Path(temporary))
            self.module.install(source, target)
            (source / "SKILL.md").write_text("canonical skill v2\n", encoding="utf-8")
            second = self.module.install(source, target)
            backup_receipt_path = Path(second["backup_path"]) / RECEIPT_NAME
            changed = json.loads(backup_receipt_path.read_text(encoding="utf-8"))
            changed["merged_commit"] = "a" * 40
            backup_receipt_path.write_bytes(
                (
                    json.dumps(
                        changed,
                        ensure_ascii=False,
                        allow_nan=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                ).encode("utf-8")
            )

            with self.assertRaisesRegex(RuntimeError, "retained backup receipt"):
                self.module.verify_install(source, target)

    def test_next_upgrade_refuses_invalid_retained_backup_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = prepared_skill_dirs(Path(temporary))
            self.module.install(source, target)
            (source / "SKILL.md").write_text("canonical skill v2\n", encoding="utf-8")
            second = self.module.install(source, target)
            target_receipt_bytes = (target / RECEIPT_NAME).read_bytes()
            target_skill_bytes = (target / "SKILL.md").read_bytes()
            backup_receipt_path = Path(second["backup_path"]) / RECEIPT_NAME
            changed = json.loads(backup_receipt_path.read_text(encoding="utf-8"))
            changed["merged_commit"] = "a" * 40
            backup_receipt_path.write_bytes(
                (
                    json.dumps(
                        changed,
                        ensure_ascii=False,
                        allow_nan=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                ).encode("utf-8")
            )
            before_siblings = {path.name for path in target.parent.iterdir()}
            (source / "SKILL.md").write_text("canonical skill v3\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "retained backup receipt"):
                self.module.install(source, target)

            self.assertEqual(target_receipt_bytes, (target / RECEIPT_NAME).read_bytes())
            self.assertEqual(target_skill_bytes, (target / "SKILL.md").read_bytes())
            self.assertEqual(before_siblings, {path.name for path in target.parent.iterdir()})

    def test_next_upgrade_refuses_missing_promised_retained_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = prepared_skill_dirs(root)
            self.module.install(source, target)
            (source / "SKILL.md").write_text("canonical skill v2\n", encoding="utf-8")
            second = self.module.install(source, target)
            target_receipt_bytes = (target / RECEIPT_NAME).read_bytes()
            displaced = root / "displaced-retained-backup"
            os.replace(Path(second["backup_path"]), displaced)
            (source / "SKILL.md").write_text("canonical skill v3\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "retained backup"):
                self.module.install(source, target)

            self.assertEqual(target_receipt_bytes, (target / RECEIPT_NAME).read_bytes())
            self.assertTrue(displaced.is_dir())

    def test_verify_rejects_byte_identical_backup_directory_identity_swap(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = prepared_skill_dirs(root)
            self.module.install(source, target)
            (source / "SKILL.md").write_text("canonical skill v2\n", encoding="utf-8")
            second = self.module.install(source, target)
            backup = Path(second["backup_path"])
            displaced = root / "displaced-original-backup"
            os.replace(backup, displaced)
            shutil.copytree(displaced, backup)

            with self.assertRaisesRegex(RuntimeError, "retained backup identity"):
                self.module.verify_install(source, target)

    def test_verify_rechecks_backup_identity_after_read_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = prepared_skill_dirs(root)
            self.module.install(source, target)
            (source / "SKILL.md").write_text("canonical skill v2\n", encoding="utf-8")
            second = self.module.install(source, target)
            backup = Path(second["backup_path"])
            displaced = root / "displaced-at-read-boundary"
            real_assert = self.module._assert_recorded_target
            injection_calls = 0

            def swap_before_receipt_read(path, *args, **kwargs):
                nonlocal injection_calls
                if Path(path) == backup and injection_calls == 0:
                    injection_calls += 1
                    os.replace(backup, displaced)
                    shutil.copytree(displaced, backup)
                return real_assert(path, *args, **kwargs)

            with mock.patch.object(
                self.module,
                "_assert_recorded_target",
                side_effect=swap_before_receipt_read,
            ):
                with self.assertRaisesRegex(RuntimeError, "retained backup identity"):
                    self.module.verify_install(source, target)

            self.assertGreater(injection_calls, 0)
            self.assertTrue(displaced.is_dir())

    def test_three_valid_upgrades_preserve_verified_backup_lineage(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = prepared_skill_dirs(Path(temporary))
            self.module.install(source, target)
            (source / "SKILL.md").write_text("canonical skill v2\n", encoding="utf-8")
            second = self.module.install(source, target)
            self.assertEqual(second, self.module.verify_install(source, target))
            (source / "SKILL.md").write_text("canonical skill v3\n", encoding="utf-8")

            third = self.module.install(source, target)

            self.assertEqual(third, self.module.verify_install(source, target))
            backups = [
                path
                for path in target.parent.iterdir()
                if path.name.startswith(target.name + ".backup-")
            ]
            self.assertEqual(2, len(backups))
            self.assertNotEqual(second["backup_path"], third["backup_path"])

    def test_change_after_final_backup_assertion_survives_successful_upgrade(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = prepared_skill_dirs(Path(temporary))
            self.module.install(source, target)
            (source / "SKILL.md").write_text("replacement\n", encoding="utf-8")
            real_assert = self.module._assert_recorded_target
            backup_assertions = 0
            injected = False

            def inject_after_assert(path, *args, **kwargs):
                nonlocal backup_assertions, injected
                result = real_assert(path, *args, **kwargs)
                if Path(path).name.startswith(target.name + ".backup-"):
                    backup_assertions += 1
                    if backup_assertions == 3:
                        (Path(path) / "late-user-data.txt").write_text(
                            "must survive", encoding="utf-8"
                        )
                        injected = True
                return result

            with mock.patch.object(
                self.module, "_assert_recorded_target", side_effect=inject_after_assert
            ):
                receipt = self.module.install(source, target)

            self.assertTrue(injected)
            backup = Path(receipt["backup_path"])
            self.assertEqual(
                "must survive",
                (backup / "late-user-data.txt").read_text(encoding="utf-8"),
            )

    def test_change_before_final_backup_assertion_is_preserved_and_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = prepared_skill_dirs(Path(temporary))
            self.module.install(source, target)
            (source / "SKILL.md").write_text("replacement\n", encoding="utf-8")
            real_assert = self.module._assert_recorded_target
            backup_assertions = 0
            changed_backup = None

            def inject_before_assert(path, *args, **kwargs):
                nonlocal backup_assertions, changed_backup
                if Path(path).name.startswith(target.name + ".backup-"):
                    backup_assertions += 1
                    if backup_assertions == 3:
                        changed_backup = Path(path)
                        (changed_backup / "late-user-data.txt").write_text(
                            "must survive failure", encoding="utf-8"
                        )
                return real_assert(path, *args, **kwargs)

            with mock.patch.object(
                self.module, "_assert_recorded_target", side_effect=inject_before_assert
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "changed backup preserved at"
                ):
                    self.module.install(source, target)

            self.assertIsNotNone(changed_backup)
            self.assertEqual(
                "must survive failure",
                (changed_backup / "late-user-data.txt").read_text(encoding="utf-8"),
            )
            self.assertEqual("replacement\n", (target / "SKILL.md").read_text())

    def test_refuses_fake_home_workspace_root_and_overlapping_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, _ = prepared_skill_dirs(root)
            fake_home = root / "fake-home"
            fake_home.mkdir()
            fake_workspace = root / "fake-workspace"
            fake_workspace.mkdir()
            (fake_workspace / ".git").write_text("gitdir: nowhere\n", encoding="utf-8")

            with mock.patch.object(self.module.Path, "home", return_value=fake_home):
                with self.assertRaisesRegex(RuntimeError, "unsafe target"):
                    self.module.install(source, fake_home)
            with self.assertRaisesRegex(RuntimeError, "workspace root"):
                self.module.install(source, fake_workspace)
            with self.assertRaisesRegex(RuntimeError, "source and target overlap"):
                self.module.install(source, source)


class SkillVerifyAndCliTests(unittest.TestCase):
    def setUp(self):
        self.module = load_installer()

    def test_verify_rejects_source_or_target_hash_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = prepared_skill_dirs(Path(temporary))
            self.module.install(source, target)
            (source / "SKILL.md").write_text("new source", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "canonical source hash mismatch"):
                self.module.verify_install(source, target)

            (source / "SKILL.md").write_text("canonical skill\n", encoding="utf-8")
            (target / "SKILL.md").write_text("target drift", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "installed skill has unrecorded changes"):
                self.module.verify_install(source, target)

    def test_verify_rejects_malformed_duplicate_and_nonfinite_receipts(self):
        malformed_receipts = (
            "not json",
            '{"schema_version":1,"schema_version":1}',
            '{"schema_version":NaN}',
            json.dumps(
                {
                    "schema_version": 1,
                    "canonical_hash": "0" * 64,
                    "installed_hash": "0" * 64,
                    "merged_commit": None,
                    "source_identity": "source",
                    "extra": True,
                }
            ),
        )
        for malformed in malformed_receipts:
            with self.subTest(malformed=malformed), tempfile.TemporaryDirectory() as temporary:
                source, target = prepared_skill_dirs(Path(temporary), existing_target=True)
                (target / RECEIPT_NAME).write_text(malformed, encoding="utf-8")

                with self.assertRaisesRegex(RuntimeError, "strict install receipt required"):
                    self.module.verify_install(source, target)

    def test_verify_rejects_receipt_only_changes_and_noncanonical_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = prepared_skill_dirs(Path(temporary))
            receipt = self.module.install(source, target)
            receipt_path = target / RECEIPT_NAME

            changed = dict(receipt)
            changed["merged_commit"] = "a" * 40
            receipt_path.write_bytes(
                (
                    json.dumps(changed, sort_keys=True, separators=(",", ":")) + "\n"
                ).encode("utf-8")
            )
            with self.assertRaisesRegex(RuntimeError, "merged commit mismatch"):
                self.module.verify_install(source, target)

            receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "canonical install receipt required"):
                self.module.verify_install(source, target)

    def test_receipt_path_swap_cannot_substitute_valid_bytes_for_malformed_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = prepared_skill_dirs(Path(temporary))
            self.module.install(source, target)
            receipt_path = target / RECEIPT_NAME
            valid_bytes = receipt_path.read_bytes()
            valid_receipt_path = Path(temporary) / "valid-receipt.json"
            valid_receipt_path.write_bytes(valid_bytes)
            malformed_bytes = b"not-json"
            receipt_path.write_bytes(malformed_bytes)
            real_open = self.module.os.open
            redirected_open_calls = 0

            def redirect_receipt_open(path, flags, *args, **kwargs):
                nonlocal redirected_open_calls
                if Path(path) == receipt_path:
                    redirected_open_calls += 1
                    return real_open(valid_receipt_path, flags, *args, **kwargs)
                return real_open(path, flags, *args, **kwargs)

            with mock.patch.object(
                self.module.os, "open", side_effect=redirect_receipt_open
            ):
                with self.assertRaisesRegex(RuntimeError, "strict install receipt required"):
                    self.module.verify_install(source, target)

            self.assertGreater(redirected_open_calls, 0)
            self.assertEqual(malformed_bytes, receipt_path.read_bytes())

    def test_verify_rereads_receipt_at_final_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = prepared_skill_dirs(Path(temporary))
            self.module.install(source, target)
            receipt_path = target / RECEIPT_NAME
            malformed_bytes = b"changed-after-first-read"
            real_read = self.module._read_receipt
            target_reads = 0

            def corrupt_after_first_target_read(path, *args, **kwargs):
                nonlocal target_reads
                if Path(path) == target:
                    target_reads += 1
                result = real_read(path, *args, **kwargs)
                if Path(path) == target:
                    if target_reads == 1:
                        receipt_path.write_bytes(malformed_bytes)
                return result

            with mock.patch.object(
                self.module, "_read_receipt", side_effect=corrupt_after_first_target_read
            ):
                with self.assertRaisesRegex(RuntimeError, "strict install receipt required"):
                    self.module.verify_install(source, target)

            self.assertGreaterEqual(target_reads, 2)
            self.assertEqual(malformed_bytes, receipt_path.read_bytes())

    def test_cli_modes_are_required_mutually_exclusive_and_fail_closed(self):
        cases = (
            [],
            ["--install", "--verify", "--source", "x", "--target", "y"],
            ["--verify", "--source", "missing", "--target", "missing"],
            ["--install", "--source", "x", "--target", "y", "--unknown"],
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [sys.executable, str(SCRIPT_PATH), *arguments],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(0, result.returncode)

    def test_cli_install_then_verify_emits_the_same_strict_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = prepared_skill_dirs(Path(temporary))
            base = ["--source", str(source), "--target", str(target)]
            installed = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), "--install", *base],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            verified = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), "--verify", *base],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(json.loads(installed.stdout), json.loads(verified.stdout))


class DirectoryFlushContractTests(unittest.TestCase):
    def setUp(self):
        self.module = load_installer()

    def test_windows_directory_flush_failure_is_reported_as_best_effort(self):
        flush = getattr(self.module, "_flush_directory", None)
        self.assertTrue(callable(flush), "stable directory flush contract is absent")
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            self.module, "_IS_WINDOWS", True
        ), mock.patch.object(
            self.module.os, "open", side_effect=PermissionError("directory open denied")
        ):
            self.assertFalse(flush(Path(temporary)))

    def test_posix_directory_flush_failure_fails_closed(self):
        flush = getattr(self.module, "_flush_directory", None)
        self.assertTrue(callable(flush), "stable directory flush contract is absent")
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            self.module, "_IS_WINDOWS", False
        ), mock.patch.object(
            self.module.os, "open", side_effect=OSError("directory open failed")
        ):
            with self.assertRaisesRegex(RuntimeError, "directory flush failed"):
                flush(Path(temporary))

    def test_posix_directory_fsync_failure_fails_closed(self):
        flush = self.module._flush_directory
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            self.module, "_IS_WINDOWS", False
        ), mock.patch.object(
            self.module.os, "open", return_value=17
        ), mock.patch.object(
            self.module.os, "fsync", side_effect=OSError("directory fsync failed")
        ), mock.patch.object(self.module.os, "close"):
            with self.assertRaisesRegex(RuntimeError, "directory flush failed"):
                flush(Path(temporary))


if __name__ == "__main__":
    unittest.main()
