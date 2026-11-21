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

    def test_pr_source_paths_cover_every_four_package_build_input(self):
        # A green SG6 check is misleading if a Rust, Core, Session or
        # packaging-source change silently skips the independent builders.
        # Use representative *actual inputs* from the four build scripts,
        # not just the workflow/verifier files.
        from fnmatch import fnmatchcase

        section = self.build_compare.split("  pull_request:\n", 1)[1]
        section = section.split("  workflow_dispatch:\n", 1)[0]
        patterns = {
            line.strip()[3:-1]
            for line in section.splitlines()
            if line.startswith("      - '") and line.endswith("'")
        }
        self.assertTrue(patterns)
        self.assertNotIn("**", patterns, "unbounded build trigger is not intentional")
        changed_files = (
            "components/riceplate-wayland/Cargo.lock",
            "components/riceplate-wayland/src/input_core.rs",
            "packaging/wayland/native-control.in",
            "packaging/wayland/ricebowl-native.desktop",
            "packaging/wayland/desktop-control",
            "launcher.py",
            "macrice/cli.py",
            "macrice/creator_gui.py",
            "macrice/de/session.py",
            "assets/wallpapers/luna.png",
            "assets/icons/RiceHub-Luna-Icons/folder.png",
            "assets/ricebowl-symbolic.svg",
            "assets/macrice-symbolic.svg",
            "assets/ricehub-symbolic.svg",
            "examples/wayland/heritage-modern-v10.json",
            "scripts/build_wayland_core_deb.sh",
            "scripts/build_wayland_session_deb.sh",
            "scripts/build_riceplate_native_deb.sh",
            "scripts/build_wayland_desktop_deb.sh",
            "scripts/verify_wayland_payload.py",
            "scripts/verify_wayland_control.py",
            "scripts/verify_wayland_session_entries.py",
            "tests/test_wayland_session_entries.py",
            "scripts/verify_wayland_package_set.sh",
        )
        for changed in changed_files:
            with self.subTest(changed=changed):
                self.assertTrue(
                    any(fnmatchcase(changed, pattern) for pattern in patterns),
                    f"SG6 PR source change is missing from path filters: {changed}",
                )

    def test_main_push_and_pull_request_build_all_the_same_inputs(self):
        # The signed main result must not be skipped for changed sources
        # which would trigger only the untrusted PR comparison workflow.
        self.assertIn("  push:\n    branches: [main]\n", self.build_compare)
        from fnmatch import fnmatchcase

        trigger_block = self.build_compare.split("  pull_request:\n", 1)[1]
        pr_paths, push_after = trigger_block.split("  push:\n", 1)
        push_paths = push_after.split("  workflow_dispatch:\n", 1)[0]
        def extract_paths(block):
            return {
                line.strip()[3:-1]
                for line in block.splitlines()
                if line.startswith("      - '") and line.endswith("'")
            }
        self.assertEqual(extract_paths(pr_paths), extract_paths(push_paths))
        self.assertTrue(any(
            fnmatchcase("scripts/verify_wayland_package_set.sh", pattern)
            for pattern in extract_paths(push_paths)
        ))
        self.assertIn('if [ "$GITHUB_EVENT_NAME" = workflow_dispatch ] || '
                      '[ "$GITHUB_EVENT_NAME" = push ]; then', self.build_compare)
        self.assertIn('test "$(gh api "repos/$GITHUB_REPOSITORY/git/ref/heads/main"',
                      self.build_compare)

    def test_attestation_policy_changes_recheck_native_and_mint_recovery(self):
        # Trusting a package-comparison workflow is a release-safety change:
        # the PR and resulting main commit must also run installed-session
        # and disposable Mint recovery rather than reusing earlier evidence.
        native = (WORKFLOW.parent / "riceplate-native.yml").read_text(encoding="utf-8")
        for watched in (
            ".github/workflows/sg6-cross-runner.yml",
            "scripts/verify_sg6_cross_runner.py",
            "tests/test_sg6_cross_runner.py",
            "tests/test_sg6_workflow_policy.py",
        ):
            # Both PR heads and trusted main pushes must invalidate
            # stale Native/Ubuntu/Mint evidence after verifier edits.
            self.assertEqual(native.count(f"      - '{watched}'"), 2,
                             f"Native/Mint trigger missing or asymmetric: {watched}")
        self.assertIn("sg6-mint221-compat:", native)
        self.assertIn("smoke_wayland_upgrade_rollback.sh", native)

    def test_signing_job_only_runs_on_trusted_main_push_or_dispatch(self):
        self.assertIn(
            "if: (github.event_name == 'workflow_dispatch' || "
            "github.event_name == 'push') && github.ref == 'refs/heads/main'",
            self.attest,
        )
        self.assertIn('test "$GITHUB_EVENT_NAME" = push || test "$GITHUB_EVENT_NAME" = workflow_dispatch',
                      self.attest)
        self.assertNotIn("github.event_name == 'pull_request'", self.attest)
        self.assertIn("needs: compare", self.attest)
        self.assertIn("id-token: write", self.attest)
        self.assertIn("attestations: write", self.attest)
        self.assertEqual(self.attest.count("uses: actions/attest@v4"), 2,
                         "Report and four direct package subjects both require signing")
        self.assertIn("subject-path: dist/sg6-comparison/report.json", self.attest)
        self.assertIn("subject-checksums: dist/sg6-comparison/packages.sha256", self.attest)
        self.assertIn("set(packages) == set(expected)", self.attest)
        self.assertIn("re.fullmatch(r'[0-9a-f]{64}', packages[name])", self.attest)
        self.assertIn("git/ref/heads/main", self.attest)
        self.assertIn("report['source_sha'] == sys.argv[1]", self.attest)
        self.assertIn("report['hardware_accepted'] is False", self.attest)


if __name__ == "__main__":
    unittest.main()
