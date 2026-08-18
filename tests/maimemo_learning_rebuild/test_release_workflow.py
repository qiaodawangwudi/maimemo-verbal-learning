import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "maimemo-release.yml"
QUALITY_WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "learning-quality-gate.yml"
)
CODEOWNERS_PATH = REPO_ROOT / ".github" / "CODEOWNERS"


def load_workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def extract_job(workflow: str, job_name: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(job_name)}:\s*$\n(.*?)(?=^  [a-zA-Z0-9_-]+:\s*$|\Z)",
        workflow,
    )
    if match is None:
        raise AssertionError(f"workflow job is absent: {job_name}")
    return match.group(0)


def extract_dispatch_input_names(workflow: str) -> set[str]:
    match = re.search(
        r'(?ms)^"on":\s*$\n  workflow_dispatch:\s*$\n    inputs:\s*$\n(.*?)(?=^[^ ]|\Z)',
        workflow,
    )
    if match is None:
        raise AssertionError("workflow_dispatch inputs block is absent")
    return set(re.findall(r"(?m)^      ([a-z][a-z0-9_]*):\s*$", match.group(1)))


class ProtectedReleaseWorkflowTests(unittest.TestCase):
    def test_dispatch_is_the_only_trigger_and_inputs_are_exact(self):
        workflow = load_workflow_text()

        self.assertEqual({"release_path", "release_hash", "commit_sha"}, extract_dispatch_input_names(workflow))
        self.assertEqual(1, len(re.findall(r"(?m)^  workflow_dispatch:\s*$", workflow)))
        self.assertNotIn("pull_request_target", workflow)
        self.assertNotRegex(workflow, r"(?m)^\s*pull_request:\s*$")
        self.assertNotRegex(workflow, r"(?m)^\s*push:\s*$")
        for input_name in ("release_path", "release_hash", "commit_sha"):
            input_block = re.search(
                rf"(?ms)^      {input_name}:\s*$\n(.*?)(?=^      [a-z][a-z0-9_]*:\s*$|^[^ ]|\Z)",
                workflow,
            )
            self.assertIsNotNone(input_block)
            self.assertRegex(input_block.group(1), r"(?m)^        required: true\s*$")
            self.assertRegex(input_block.group(1), r'(?m)^        type: string\s*$')

    def test_prepare_is_tokenless_and_enforces_the_frozen_release_gates(self):
        workflow = load_workflow_text()
        prepare = extract_job(workflow, "prepare-release")

        self.assertNotIn("secrets.", prepare)
        self.assertIn("ref: ${{ inputs.commit_sha }}", prepare)
        self.assertIn("actions/setup-python@v5", prepare)
        self.assertIn("origin/main", prepare)
        self.assertIn("refs/heads/main", prepare)
        self.assertIn("validate_release_directory", prepare)
        self.assertIn("_load_frozen_release", prepare)
        self.assertIn("inputs.release_hash", prepare)
        self.assertIn("unittest discover", prepare)
        self.assertIn("public_quality_gate", prepare)
        self.assertIn("application_quality_gate", prepare)
        self.assertIn("validate_source_inventory", prepare)
        self.assertIn("release_quality_gate", prepare)
        self.assertIn("release_quality_gate --release-dir \"$RELEASE_DIR\" --precheck", prepare)
        self.assertIn("GATE_ARTIFACT_DIR", prepare)
        self.assertIn("master_semantic_registry.json", prepare)
        self.assertIn("application_blind_review.json", prepare)
        self.assertNotIn('public_quality_gate --artifact-dir "$RELEASE_DIR"', prepare)
        self.assertNotIn('application_quality_gate --artifact-dir "$RELEASE_DIR"', prepare)
        self.assertIn("GITHUB_STEP_SUMMARY", prepare)
        for summary_field in (
            "deck",
            "chapter_routes",
            "card_counts",
            "privacy_summary",
            "release_hash",
            "commit_sha",
        ):
            self.assertIn(summary_field, prepare)
        self.assertIn("actions/upload-artifact@v4", prepare)
        self.assertRegex(prepare, r"(?m)^\s+path: release-reports/\s*$")
        self.assertNotIn("path: ${{ inputs.release_path }}", prepare)

    def test_token_only_exists_in_protected_writer_step(self):
        workflow = load_workflow_text()
        prepare = extract_job(workflow, "prepare-release")
        writer = extract_job(workflow, "write-release")

        self.assertEqual(1, workflow.count("secrets.MAIMEMO_TOKEN"))
        self.assertEqual(1, workflow.count("environment: maimemo-final-release"))
        self.assertNotIn("maimemo-independent-comparison-review", workflow)
        self.assertNotIn("secrets.MAIMEMO_TOKEN", prepare)
        self.assertIn("environment: maimemo-final-release", writer)
        self.assertRegex(writer, r"(?m)^\s+needs: prepare-release\s*$")
        self.assertIn("group: maimemo-production", writer)
        self.assertIn("cancel-in-progress: false", writer)
        self.assertIn("ref: ${{ inputs.commit_sha }}", writer)
        self.assertIn("actions/setup-python@v5", writer)
        self.assertIn("origin/main", writer)
        self.assertIn("refs/heads/main", writer)
        self.assertIn("_load_frozen_release", writer)
        self.assertIn("python -m maimemo_learning_rebuild.release_writer", writer)
        self.assertIn("MAIMEMO_API_TOKEN: ${{ secrets.MAIMEMO_TOKEN }}", writer)
        quality_step = "Run protected current-environment learning quality gate"
        self.assertIn(quality_step, writer)
        protected_quality = writer.index(quality_step)
        secret_position = writer.index(
            "MAIMEMO_API_TOKEN: ${{ secrets.MAIMEMO_TOKEN }}"
        )
        self.assertLess(protected_quality, secret_position)
        quality_block = writer[
            protected_quality : writer.index("Execute protected writer")
        ]
        self.assertIn("python -m maimemo_learning_rebuild.release_quality_gate", quality_block)
        self.assertIn("GITHUB_ENVIRONMENT: maimemo-final-release", quality_block)
        self.assertIn("GITHUB_DEPLOYMENT_STATUS: success", quality_block)
        self.assertIn("APPROVED_COMMIT_SHA: ${{ inputs.commit_sha }}", quality_block)
        self.assertNotIn("secrets.", quality_block)
        secret_step = writer[writer.index("MAIMEMO_API_TOKEN: ${{ secrets.MAIMEMO_TOKEN }}") :]
        self.assertIn("python -m maimemo_learning_rebuild.release_writer", secret_step)
        self.assertIn("if: always()", writer)
        self.assertIn("journal.jsonl", writer)
        self.assertIn("readback-report.json", writer)

    def test_writer_initializes_and_synthesizes_reports_around_all_failure_points(self):
        writer = extract_job(load_workflow_text(), "write-release")

        initialize = writer.index("Initialize non-secret result files")
        checkout = writer.index("Check out the exact approved commit")
        recheck = writer.index("Recheck current main and the exact frozen release")
        synthesize = writer.index("Synthesize non-secret result files")
        upload = writer.index("Upload non-secret journal and readback report")
        self.assertRegex(
            writer,
            r"(?m)^    steps:\s*$\n      - name: Initialize non-secret result files$",
        )
        self.assertLess(initialize, checkout)
        self.assertLess(checkout, recheck)
        self.assertLess(recheck, synthesize)
        self.assertLess(synthesize, upload)
        self.assertIn("$RUNNER_TEMP/maimemo-release-results", writer)
        self.assertGreaterEqual(writer.count("if: always()"), 2)
        self.assertIn('"status":"not_started"', writer)
        self.assertIn('"status":"failed_before_readback"', writer)
        self.assertIn("if-no-files-found: error", writer)

    def test_workflow_permissions_are_read_only(self):
        workflow = load_workflow_text()

        self.assertRegex(
            workflow,
            r"(?ms)^permissions:\s*$\n  contents: read\s*$\n\s*jobs:",
        )
        self.assertNotRegex(workflow, r"(?m)^\s*(actions|checks|deployments|packages|pull-requests): write\s*$")

    def test_codeowners_protects_every_release_boundary_with_one_exact_owner(self):
        rows = {
            line.split()[0]: line.split()[1:]
            for line in CODEOWNERS_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        expected_paths = {
            "/.github/workflows/maimemo-release.yml",
            "/skills/verbal-maimemo-cards/**",
            "/maimemo_learning_rebuild/__init__.py",
            "/.github/CODEOWNERS",
        }

        self.assertEqual(expected_paths, set(rows))
        self.assertTrue(all(owners == ["@qiaodawangwudi"] for owners in rows.values()))

    def test_quality_ci_discovers_every_test_module(self):
        workflow = QUALITY_WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn("python -m unittest discover", workflow)
        self.assertIn("-s tests -t . -p 'test_*.py'", workflow)

    def test_pull_request_ci_does_not_authorize_or_gate_unfrozen_working_artifacts(self):
        workflow = QUALITY_WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertNotIn("environment: maimemo-final-release", workflow)
        self.assertNotIn(
            "--artifact-dir maimemo_learning_rebuild/artifacts",
            workflow,
        )
        self.assertIn(
            "tests.maimemo_learning_rebuild.test_public_quality_gate",
            workflow,
        )
        self.assertIn(
            "tests.maimemo_learning_rebuild.test_application_quality_gate",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
