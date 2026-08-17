import importlib.util
import json
import os
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
                },
                set(receipt),
            )
            self.assertEqual(expected_hash, receipt["canonical_hash"])
            self.assertEqual(expected_hash, receipt["installed_hash"])
            self.assertEqual(str(source.resolve()), receipt["source_identity"])
            self.assertIsNone(receipt["merged_commit"])
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
            real_replace = os.replace
            calls = 0

            def fail_second_replace(src, dst):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated swap failure")
                return real_replace(src, dst)

            with mock.patch.object(self.module.os, "replace", side_effect=fail_second_replace):
                with self.assertRaisesRegex(RuntimeError, "installation failed; original restored"):
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
                    RuntimeError, "installed skill has unrecorded changes"
                ):
                    self.module.install(source, target)

            self.assertEqual(
                "concurrent local change", (target / "SKILL.md").read_text(encoding="utf-8")
            )

    def test_changed_backup_is_preserved_instead_of_deleted(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = prepared_skill_dirs(Path(temporary))
            self.module.install(source, target)
            (source / "SKILL.md").write_text("replacement\n", encoding="utf-8")
            real_replace = os.replace
            calls = 0

            def change_backup_after_new_target_arrives(src, dst):
                nonlocal calls
                calls += 1
                result = real_replace(src, dst)
                if calls == 2:
                    backup = next(
                        path
                        for path in target.parent.iterdir()
                        if path.name.startswith(target.name + ".backup-")
                    )
                    (backup / "SKILL.md").write_text(
                        "late local change", encoding="utf-8"
                    )
                return result

            with mock.patch.object(
                self.module.os,
                "replace",
                side_effect=change_backup_after_new_target_arrives,
            ):
                with self.assertRaisesRegex(RuntimeError, "changed backup preserved"):
                    self.module.install(source, target)

            self.assertEqual("replacement\n", (target / "SKILL.md").read_text())
            backups = [
                path
                for path in target.parent.iterdir()
                if path.name.startswith(target.name + ".backup-")
            ]
            self.assertEqual(1, len(backups))
            self.assertEqual(
                "late local change",
                (backups[0] / "SKILL.md").read_text(encoding="utf-8"),
            )

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


if __name__ == "__main__":
    unittest.main()
