"""SG7: CI churn may cancel stale feature refs but not main or releases.

GitHub Actions is the authority for executing workflow expressions. This
dependency-free test protects the source-level release evidence contract.
"""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (".github/workflows/ci.yml", ".github/workflows/wayland-session.yml")
POLICY = (
    "concurrency:\n"
    "  group: ${{ github.workflow }}-${{ github.event_name }}-${{ "
    "(github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/tags/')) "
    "&& github.run_id || github.ref }}\n"
    "  cancel-in-progress: ${{ github.ref != 'refs/heads/main' "
    "&& !startsWith(github.ref, 'refs/tags/') }}\n"
)


class WorkflowConcurrencyPolicyTests(unittest.TestCase):
    def test_expensive_workflows_supersede_only_feature_refs(self):
        for filename in WORKFLOWS:
            with self.subTest(filename=filename):
                workflow = (ROOT / filename).read_text(encoding="utf-8")
                self.assertEqual(workflow.count("concurrency:\n"), 1)
                self.assertIn(POLICY, workflow)
                self.assertIn("permissions:\n  contents: read\n", workflow)
                self.assertIn("runs-on: ubuntu-24.04", workflow)
                self.assertIn("  pull_request:\n", workflow)
                self.assertIn("  push:\n", workflow)

    def test_main_and_tag_guards_remain_explicit(self):
        for filename in WORKFLOWS:
            with self.subTest(filename=filename):
                workflow = (ROOT / filename).read_text(encoding="utf-8")
                group = workflow.split("concurrency:\n", 1)[1].split("\n\n", 1)[0]
                self.assertIn("github.workflow", group)
                self.assertIn("github.event_name", group)
                self.assertIn("github.run_id || github.ref", group)
                self.assertIn("github.ref == 'refs/heads/main'", group)
                self.assertIn("startsWith(github.ref, 'refs/tags/')", group)
                self.assertIn("github.ref != 'refs/heads/main'", group)
                self.assertIn("!startsWith(github.ref, 'refs/tags/')", group)


    def test_main_and_tag_runs_have_distinct_pending_groups(self):
        # GitHub concurrency can replace an older *pending* run even when
        # cancel-in-progress is false. Model the exact guarded expression's
        # expected grouping behavior for the only two protected ref types.
        def group(workflow, event, ref, run_id):
            protected = ref == "refs/heads/main" or ref.startswith("refs/tags/")
            return f"{workflow}-{event}-{run_id if protected else ref}"

        for ref in ("refs/heads/main", "refs/tags/v1.0.0-rc.1"):
            self.assertNotEqual(group("Tests", "push", ref, 101),
                                group("Tests", "push", ref, 102))
        for ref in ("refs/heads/fix/thing", "refs/pull/12/merge"):
            self.assertEqual(group("Tests", "pull_request", ref, 101),
                             group("Tests", "pull_request", ref, 102))
        self.assertNotEqual(group("Tests", "push", "refs/heads/main", 101),
                            group("Wayland session preview", "push",
                                  "refs/heads/main", 101))


if __name__ == "__main__":
    unittest.main()
