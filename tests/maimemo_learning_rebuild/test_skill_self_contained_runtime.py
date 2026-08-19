import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "verbal-maimemo-cards"
RUNTIME_PACKAGE = (
    SKILL_ROOT / "scripts" / "runtime" / "maimemo_learning_rebuild"
)


class SelfContainedSkillTests(unittest.TestCase):
    def test_skill_routes_execution_to_bundled_runtime(self):
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        guide = SKILL_ROOT / "references" / "execution-guide.md"
        self.assertIn("references/execution-guide.md", skill_text)
        self.assertTrue(guide.is_file())
        guide_text = guide.read_text(encoding="utf-8")
        for required in (
            "run_pipeline.py self-check",
            "reconcile-library",
            "library_reconciliation",
            "只审查",
            "生成预览",
            "受保护发布",
            "install-github-templates",
        ):
            self.assertIn(required, guide_text)

    def test_skill_carries_every_protected_release_component(self):
        required_modules = {
            "source_inventory.py",
            "review.py",
            "learning_quality.py",
            "application_quality_gate.py",
            "release_manifest.py",
            "release_environment.py",
            "release_writer.py",
            "readback.py",
            "guard.py",
            "reconciliation.py",
            "content_acceptance_v2.py",
        }
        present = {path.name for path in RUNTIME_PACKAGE.glob("*.py")}
        self.assertEqual(required_modules - present, set())

        assets = SKILL_ROOT / "assets" / "github"
        self.assertTrue((assets / "CODEOWNERS").is_file())
        self.assertTrue((assets / "workflows" / "learning-quality-gate.yml").is_file())
        self.assertTrue((assets / "workflows" / "maimemo-release.yml").is_file())
        owner_rows = {
            line.split()[0]
            for line in (assets / "CODEOWNERS").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertEqual(
            owner_rows,
            {
                "/.github/workflows/learning-quality-gate.yml",
                "/.github/workflows/maimemo-release.yml",
                "/maimemo_learning_rebuild/**",
                "/.github/CODEOWNERS",
            },
        )

    def test_repository_imports_the_skill_bundled_runtime_as_canonical(self):
        import maimemo_learning_rebuild.release_writer as release_writer

        module_path = Path(release_writer.__file__).resolve()
        self.assertTrue(module_path.is_relative_to(RUNTIME_PACKAGE.resolve()))

    def test_installed_skill_self_checks_from_outside_repository(self):
        installer = SKILL_ROOT / "scripts" / "install_or_verify.py"
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            target = temp / "installed-skill"
            subprocess.run(
                [
                    sys.executable,
                    str(installer),
                    "--install",
                    "--source",
                    str(SKILL_ROOT),
                    "--target",
                    str(target),
                ],
                cwd=temp,
                check=True,
                capture_output=True,
                text=True,
            )
            runner = target / "scripts" / "run_pipeline.py"
            self.assertTrue(runner.is_file())

            environment = os.environ.copy()
            environment.pop("PYTHONPATH", None)
            result = subprocess.run(
                [sys.executable, str(runner), "self-check"],
                cwd=temp,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["runtime_origin"], "installed_skill")
            self.assertTrue(report["github_templates_ready"])
            self.assertIn("content_acceptance_v2", report["runtime_modules"])

    def test_github_template_install_includes_the_runtime_it_executes(self):
        runner = SKILL_ROOT / "scripts" / "run_pipeline.py"
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "target-repository"
            (target / ".git").mkdir(parents=True)
            subprocess.run(
                [
                    sys.executable,
                    str(runner),
                    "install-github-templates",
                    "--target",
                    str(target),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            installed_runtime = target / "maimemo_learning_rebuild"
            self.assertTrue((installed_runtime / "release_writer.py").is_file())
            probe = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import maimemo_learning_rebuild.release_writer; print('runtime-ok')",
                ],
                cwd=target,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(probe.stdout.strip(), "runtime-ok")

    def test_stage_arguments_are_forwarded_to_the_bundled_cli(self):
        runner = SKILL_ROOT / "scripts" / "run_pipeline.py"
        result = subprocess.run(
            [
                sys.executable,
                str(runner),
                "review-applications",
                "--help",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--artifact-dir", result.stdout)


if __name__ == "__main__":
    unittest.main()
