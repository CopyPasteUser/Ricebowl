"""Source-level protection for SG6 PR builds vs trusted main attestation.

The two independent hosted builders may run untrusted pull-request source
with read-only credentials. No PR can receive provenance-signing privileges.
Actual jobs/package bytes remain the separate GitHub Actions acceptance.
"""
from pathlib import Path
import unittest


WORKFLOW = (Path(__file__).resolve().parents[1]
            / ".github/workflows/sg6-cross-runner.yml")


class CrossRunnerWorkflowPolicyTests(unittest.TestCase):
    def setUp(self):
        self.yaml = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("\n  attest:\n", self.yaml)
        self.build_compare, self.attest = self.yaml.split("\n  attest:\n", 1)

    def test_prs_execute_both_real_builds_and_compare_without_signing_scope(self):
        self.assertIn("  pull_request:\n", self.build_compare)
        for path in ("scripts/verify_sg6_cross_runner.py",
                     "tests/test_sg6_cross_runner.py",
                     ".github/workflows/sg6-cross-runner.yml"):
            self.assertIn(path, self.build_compare)
        self.assertIn("worker: [host-a, host-b]", self.build_compare)
        self.assertEqual(self.build_compare.count(
            "if: github.event_name == 'pull_request' || github.ref == 'refs/heads/main'"), 2)
        self.assertIn("cargo build --release --locked", self.build_compare)
        self.assertIn("scripts/verify_sg6_cross_runner.py compare", self.build_compare)
        self.assertIn("GITHUB_EVENT_NAME", self.build_compare)
        self.assertNotIn("id-token: write", self.build_compare)
        self.assertNotIn("attestations: write", self.build_compare)
        self.assertNotIn("artifact-metadata: write", self.build_compare)
        self.assertNotIn("uses: actions/attest@", self.build_compare)

    def test_signing_job_only_runs_on_explicit_trusted_main_dispatch(self):
        self.assertIn("if: github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main'",
                      self.attest)
        self.assertIn("needs: compare", self.attest)
        self.assertIn("id-token: write", self.attest)
        self.assertIn("attestations: write", self.attest)
        self.assertIn("actions/attest@v4", self.attest)
        self.assertIn("git/ref/heads/main", self.attest)
        self.assertIn("report['source_sha'] == sys.argv[1]", self.attest)
        self.assertIn("report['hardware_accepted'] is False", self.attest)


if __name__ == "__main__":
    unittest.main()
