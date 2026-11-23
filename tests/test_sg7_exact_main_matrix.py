"""Negative and positive tests for exact-main SG7 receipt aggregation."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("sg7_exact_main_matrix", SCRIPTS / "sg7_exact_main_matrix.py")
sg7 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sg7)
SHA = "a" * 40
REPO = "CopyPasteUser/Ricebowl"


class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.runs = []
        self.jobs = {}
        for i, (path, name) in enumerate(sg7.REQUIRED.items(), 1):
            self.runs.append({"id": i, "name": name, "path": path,
                              "head_sha": SHA, "head_branch": "main", "event": "push",
                              "status": "completed", "conclusion": "success"})
            self.jobs[path] = []
            for job_name in sg7.REQUIRED_JOBS[path]:
                steps = [{"name": step, "status": "completed", "conclusion": "success"}
                         for _, p, j, step in sg7.CHECKS if p == path and j == job_name]
                self.jobs[path].append({"run_id": i, "name": job_name,
                                         "status": "completed", "conclusion": "success",
                                         "steps": steps})

    def matrix(self, **kwargs):
        return sg7.evaluate({"workflow_runs": self.runs}, self.jobs,
                            sha=kwargs.get("sha", SHA),
                            main_sha=kwargs.get("main_sha", SHA),
                            repository=REPO, open_prs=kwargs.get("open_prs", 0))

    def test_complete_execution_does_not_claim_gate_or_hardware_signoff(self):
        report = self.matrix()
        self.assertEqual(report["exact_main_execution"], "passed")
        self.assertEqual(len(report["checks"]), len(sg7.CHECKS))
        self.assertTrue(all(c["status"] == "passed" for c in report["checks"]))
        self.assertTrue(report["ready_for_formal_review"])
        self.assertFalse(report["formal_sg6_closed"])
        self.assertFalse(report["formal_sg7_closed"])
        self.assertFalse(report["physical_hardware_accepted"])
        self.assertTrue(report["unverified_requirements"])

    def test_stale_main_and_open_prs_block(self):
        self.assertFalse(self.matrix(main_sha="b" * 40)["ready_for_formal_review"])
        self.assertFalse(self.matrix(open_prs=2)["ready_for_formal_review"])

    def test_no_old_green_run_can_hide_latest_failed_or_pending(self):
        old = self.runs[1]
        for outcome in (("completed", "failure"), ("in_progress", None), ("completed", "cancelled")):
            with self.subTest(outcome=outcome):
                newer = dict(old, id=100, status=outcome[0], conclusion=outcome[1])
                self.runs.append(newer)
                self.assertFalse(self.matrix()["ready_for_formal_review"])
                self.runs.pop()

    def test_failed_skipped_missing_or_duplicate_critical_step_blocks(self):
        path = ".github/workflows/riceplate-native.yml"
        steps = self.jobs[path][0]["steps"]
        original = [dict(s) for s in steps]
        for mutated in ([], [dict(original[0], conclusion="skipped")],
                        original + [dict(original[0])]):
            with self.subTest(mutation=mutated):
                self.jobs[path][0]["steps"] = mutated
                self.assertFalse(self.matrix()["ready_for_formal_review"])
        self.jobs[path][0]["steps"] = original

    def test_wrong_job_run_id_fails_even_if_steps_pass(self):
        job = self.jobs[".github/workflows/ci.yml"][0]
        job["run_id"] = 999
        self.assertFalse(self.matrix()["ready_for_formal_review"])

    def test_pr_head_untrusted_and_missing_path_filtered_run(self):
        removed = self.runs.pop()
        self.assertFalse(self.matrix()["ready_for_formal_review"])
        self.runs.append(dict(removed, event="pull_request", head_branch="feature"))
        self.assertFalse(self.matrix()["ready_for_formal_review"])

    def test_collector_rechecks_live_main_and_open_prs_before_publication(self):
        old_pr = (590, 'c' * 40, True)
        changed_head = (590, 'd' * 40, True)
        replacement_pr = (597, 'c' * 40, True)
        for initial_prs, final_context, expected in (
            ((), (SHA, ()), 0),
            ((), ('b' * 40, ()), 2),
            ((), (SHA, (old_pr,)), 2),
            ((old_pr,), (SHA, (changed_head,)), 2),
            ((old_pr,), (SHA, (replacement_pr,)), 2),
            ((old_pr,), (SHA, ((590, 'c' * 40, False),)), 2),
        ):
            with self.subTest(initial=initial_prs, final=final_context), tempfile.TemporaryDirectory() as folder:
                output = Path(folder) / 'software-matrix.json'
                env = {'GITHUB_SHA': SHA, 'GITHUB_REPOSITORY': REPO, 'GH_TOKEN': 'test-only-token'}
                with (patch.dict(sg7.os.environ, env),
                      patch.object(sg7, '_live_context',
                                   side_effect=[(SHA, initial_prs), final_context]) as live,
                      patch.object(sg7, 'fetch_evidence',
                                   return_value={'workflow_runs': self.runs}),
                      patch.object(sg7, 'fetch_job_evidence',
                                   return_value=self.jobs),
                      patch('sys.stderr', new_callable=io.StringIO)):
                    self.assertEqual(sg7.main(['--output', str(output)]), expected)
                self.assertEqual(live.call_count, 2)
                self.assertEqual(output.exists(), expected == 0)
                if expected == 0:
                    self.assertTrue(json.loads(output.read_text())['ready_for_formal_review'])

    def test_live_context_pins_pr_identity_head_and_draft(self):
        def pr(number, digest='b' * 40, draft=True):
            return {'number': number, 'head': {'sha': digest}, 'draft': draft}

        main = {'object': {'sha': SHA}}
        with patch.object(sg7, '_get_json', side_effect=[main,
                            [pr(10), pr(4, 'c' * 40, False)]]):
            sha, snapshot = sg7._live_context(REPO, 'fixture-token')
        self.assertEqual(sha, SHA)
        self.assertEqual(snapshot, ((4, 'c' * 40, False), (10, 'b' * 40, True)))

        for invalid in (
            [pr(4), pr(4)],
            [pr(True)],
            [pr(4, 'bad')],
            [pr(4, draft=None)],
            [None],
        ):
            with self.subTest(invalid=invalid), patch.object(
                    sg7, '_get_json', side_effect=[main, invalid]):
                with self.assertRaises(ValueError):
                    sg7._live_context(REPO, 'fixture-token')

    def test_invalid_sources_cannot_be_laundered(self):
        for sha in ("b" * 39, "B" * 40, "", "../main"):
            with self.subTest(sha=sha), self.assertRaises(ValueError):
                self.matrix(sha=sha)
        with self.assertRaises(ValueError):
            sg7.evaluate({"workflow_runs": self.runs}, self.jobs,
                         sha=SHA, main_sha=SHA, repository="bad/repo/extra", open_prs=0)


if __name__ == "__main__":
    unittest.main()
