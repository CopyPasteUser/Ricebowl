"""Offline deterministic SG7 run-provenance transition checks."""
from __future__ import annotations

import unittest

from scripts.sg7_evidence_snapshot import trusted_run_snapshot

SHA = "a" * 40
REQUIRED = {
    ".github/workflows/ci.yml": "Tests",
    ".github/workflows/riceplate-native.yml": "Native RicePlate prototype",
}


def run(id=1, *, path=".github/workflows/ci.yml", status="completed",
        conclusion="success", event="push", attempt=1):
    return {"id": id, "path": path, "name": REQUIRED[path],
            "head_branch": "main", "head_sha": SHA, "event": event,
            "run_attempt": attempt, "status": status, "conclusion": conclusion}


class EvidenceSnapshotTests(unittest.TestCase):
    def snap(self, rows):
        return trusted_run_snapshot({"workflow_runs": rows}, SHA, REQUIRED)

    def test_order_independent_and_pr_runs_not_trusted(self):
        first = run()
        second = run(2, path=".github/workflows/riceplate-native.yml",
                     event="workflow_dispatch")
        third = run(3, event="pull_request")
        self.assertEqual(self.snap([first, second, third]), self.snap([second, first]))
        self.assertEqual(len(self.snap([second, first])), 2)

    def test_new_pending_or_failed_run_changes_proof(self):
        baseline = self.snap([run()])
        self.assertNotEqual(baseline, self.snap([run(), run(2, status="in_progress", conclusion=None)]))
        self.assertNotEqual(baseline, self.snap([run(), run(2, conclusion="failure")]))

    def test_existing_run_change_or_rerun_changes_proof(self):
        baseline = self.snap([run()])
        self.assertNotEqual(baseline, self.snap([run(status="in_progress", conclusion=None)]))
        self.assertNotEqual(baseline, self.snap([run(attempt=2)]))
        self.assertNotEqual(baseline, self.snap([]))

    def test_invalid_or_duplicate_ids_are_not_accepted(self):
        for rows in ([run(True)], [run(0)], [run(-3)], [run(), run()],
                     [run(attempt=0)], [run(attempt=True)],
                     [run(status=None)], [run(conclusion=True)]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.snap(rows)

    def test_run_id_cannot_alias_two_different_required_workflows(self):
        native = run(1, path=".github/workflows/riceplate-native.yml")
        with self.assertRaisesRegex(ValueError, "Duplicate trusted workflow"):
            self.snap([run(1), native])

    def test_untrusted_branch_name_or_sha_cannot_poison_snapshot(self):
        wrong_branch = run(1)
        wrong_branch["head_branch"] = "feature"
        wrong_sha = run(2)
        wrong_sha["head_sha"] = "b" * 40
        self.assertEqual(self.snap([wrong_branch, wrong_sha]), ())
        self.assertEqual(self.snap([run(event="workflow_dispatch")]), ())

    def test_unhashable_or_empty_remote_metadata_cannot_crash_collector(self):
        malformed_path = run()
        malformed_path["path"] = ["not hashable"]
        self.assertEqual(self.snap([malformed_path]), ())
        for field, value in (("status", ""), ("conclusion", "")):
            row = run()
            row[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.snap([row])

    def test_missing_explicit_attempt_is_not_assumed_to_be_first_run(self):
        omitted = run()
        del omitted["run_attempt"]
        with self.assertRaisesRegex(ValueError, "run identity"):
            self.snap([omitted])

    def test_malformed_top_level_context_fails(self):
        for data in ({}, {"workflow_runs": "not a list"}, None):
            with self.subTest(data=data), self.assertRaises(ValueError):
                trusted_run_snapshot(data, SHA, REQUIRED)
        with self.assertRaises(ValueError):
            trusted_run_snapshot({"workflow_runs": []}, "wrong", REQUIRED)
        with self.assertRaises(ValueError):
            trusted_run_snapshot({"workflow_runs": []}, SHA, {})


if __name__ == "__main__":
    unittest.main()
