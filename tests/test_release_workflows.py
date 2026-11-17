"""Fail-closed exact-source CI acceptance for eventual 1.0 artifacts."""
import io
import json
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest.mock import patch

from scripts.check_release_workflows import (
    REQUIRED, WorkflowGateError, fetch_evidence, source_for_tag, validate_runs,
)

SHA = "a" * 40
OTHER = "b" * 40


def fake_run(path, name, run_id, conclusion="success", **overrides):
    item = {
        "id": run_id, "path": path, "name": name, "head_sha": SHA,
        "head_branch": "main", "event": "push", "status": "completed",
        "conclusion": conclusion,
    }
    item.update(overrides)
    return item


class ReleaseWorkflowGateTests(unittest.TestCase):
    def good_runs(self):
        # Strict portals is explicitly dispatch-only; do not fabricate a
        # nonexistent push event as valid release evidence.
        return [fake_run(path, name, i + 100,
                         event=("workflow_dispatch"
                                if path == ".github/workflows/wayland-portal-strict.yml"
                                else "push"))
                for i, (path, name) in enumerate(REQUIRED.items())]

    def test_exact_main_workflows_are_required_and_proven_by_run_id(self):
        proof = validate_runs({"workflow_runs": self.good_runs()}, SHA)
        self.assertEqual(len(proof), 4)
        self.assertEqual(set(proof), set(REQUIRED))

    def test_latest_failure_or_pending_run_cannot_hide_behind_old_success(self):
        for conclusion, status in (("failure", "completed"), (None, "in_progress"),
                                   ("cancelled", "completed")):
            runs = self.good_runs()
            runs.append(fake_run(".github/workflows/ci.yml", "Tests", 200,
                                 conclusion, status=status))
            with self.subTest(conclusion=conclusion), self.assertRaisesRegex(
                    WorkflowGateError, "not green"):
                validate_runs({"workflow_runs": runs}, SHA)

    def test_reject_missing_wrong_sha_branch_event_and_spoofed_name(self):
        first = self.good_runs()[0]
        for overrides in (
            {"head_sha": OTHER}, {"head_branch": "feature"},
            {"event": "pull_request"}, {"name": "Fake Tests"},
            {"path": ".github/workflows/fake.yml"},
        ):
            runs = self.good_runs()
            runs[0] = {**first, **overrides}
            with self.subTest(overrides=overrides), self.assertRaisesRegex(
                    WorkflowGateError, "Missing"):
                validate_runs({"workflow_runs": runs}, SHA)

    def test_path_filtered_wayland_ci_accepts_exact_main_dispatch_only(self):
        for path in (".github/workflows/riceplate-native.yml",
                     ".github/workflows/wayland-session.yml"):
            runs = self.good_runs()
            index = next(i for i, run in enumerate(runs) if run["path"] == path)
            runs[index]["event"] = "workflow_dispatch"
            self.assertIn(path, validate_runs({"workflow_runs": runs}, SHA))
            runs[index]["head_branch"] = "feature"
            with self.assertRaisesRegex(WorkflowGateError, "Missing"):
                validate_runs({"workflow_runs": runs}, SHA)

        tests = self.good_runs()
        tests[0]["event"] = "workflow_dispatch"
        with self.assertRaisesRegex(WorkflowGateError, "Missing"):
            validate_runs({"workflow_runs": tests}, SHA)

    def test_strict_portal_gate_requires_exact_main_dispatch_not_pr_or_push(self):
        portal = ".github/workflows/wayland-portal-strict.yml"
        baseline = self.good_runs()
        self.assertIn(portal, validate_runs({"workflow_runs": baseline}, SHA))
        idx = next(i for i, run in enumerate(baseline) if run["path"] == portal)
        for overrides in (
            {"event": "pull_request"}, {"event": "push"},
            {"head_branch": "integration"}, {"head_sha": OTHER},
            {"status": "in_progress", "conclusion": None},
            {"status": "completed", "conclusion": "failure"},
            {"name": "Fake strict portal"},
        ):
            runs = self.good_runs()
            runs[idx].update(overrides)
            with self.subTest(overrides=overrides), self.assertRaises(WorkflowGateError):
                validate_runs({"workflow_runs": runs}, SHA)

    def test_strict_portal_latest_failure_cannot_hide_behind_previous_success(self):
        path = ".github/workflows/wayland-portal-strict.yml"
        runs = self.good_runs()
        runs.append(fake_run(path, REQUIRED[path], 400, "failure",
                             event="workflow_dispatch"))
        with self.assertRaisesRegex(WorkflowGateError, "not green"):
            validate_runs({"workflow_runs": runs}, SHA)

    def test_release_stays_blocked_without_strict_pipewire_evidence(self):
        runs = [run for run in self.good_runs()
                if run["path"] != ".github/workflows/wayland-portal-strict.yml"]
        with self.assertRaisesRegex(WorkflowGateError, "Missing"):
            validate_runs({"workflow_runs": runs}, SHA)

    def test_native_acceptance_triggers_for_creator_pack_and_asset_contracts(self):
        # Native Composer import/render/restore uses the *Python* RicePack
        # compiler and asset schema as well as the Rust layer-shell. Missing
        # path filters silently skip required acceptance on the exact source.
        workflow = (Path(__file__).resolve().parents[1]
                    / ".github/workflows/riceplate-native.yml").read_text()
        push, pr = workflow.split("  pull_request:\n", 1)
        push = push.split("  push:\n", 1)[1]
        pr = pr.split("\npermissions:", 1)[0]
        for source in (
            "macrice/de/pack.py", "macrice/de/style_assets.py",
            "macrice/de/creator_contract.py", "tests/test_de_ricepack.py",
            "tests/test_creator_style_assets.py",
            "scripts/verify_wayland_payload.py",
            "tests/test_wayland_payload_safety.py",
        ):
            with self.subTest(source=source):
                trigger = f"      - '{source}'"
                self.assertIn(trigger, push, "native main push must be tested")
                self.assertIn(trigger, pr, "native PR must be tested")

    def test_fetch_evidence_reads_all_exact_sha_pages(self):
        # The fourth release gate may be missing from the first hundred
        # source-matched runs. Never treat GitHub's first page as exhaustive.
        first = [{"id": i, "path": "unrelated.yml"} for i in range(1, 101)]
        second = self.good_runs()
        queried_pages = []

        def respond(request, timeout):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
            self.assertEqual(query["head_sha"], [SHA])
            self.assertEqual(query["per_page"], ["100"])
            self.assertEqual(timeout, 15)
            page = int(query["page"][0])
            queried_pages.append(page)
            payload = {"total_count": 104,
                       "workflow_runs": first if page == 1 else second}
            return io.BytesIO(json.dumps(payload).encode())

        with patch("scripts.check_release_workflows.urllib.request.urlopen",
                   side_effect=respond):
            payload = fetch_evidence("CopyPasteUser/Ricebowl", SHA, "test-token")
        self.assertEqual(queried_pages, [1, 2])
        self.assertEqual(len(payload["workflow_runs"]), 104)
        self.assertEqual(len(validate_runs(payload, SHA)), 4)

    def test_fetch_evidence_rejects_truncated_or_changed_page_count(self):
        first = {"total_count": 102, "workflow_runs": [{} for _ in range(100)]}
        for second in (
            {"total_count": 102, "workflow_runs": [{}]},
            {"total_count": 101, "workflow_runs": [{}, {}]},
            {"total_count": 102, "workflow_runs": "not a list"},
        ):
            with self.subTest(second=second):
                pages = iter([first, second])
                with patch("scripts.check_release_workflows.urllib.request.urlopen",
                           side_effect=lambda *_args, **_kwargs:
                           io.BytesIO(json.dumps(next(pages)).encode())):
                    with self.assertRaises(WorkflowGateError):
                        fetch_evidence("CopyPasteUser/Ricebowl", SHA, "test-token")

    def test_fetch_evidence_rejects_partial_network_failure(self):
        calls = 0

        def respond(_request, timeout):
            nonlocal calls
            calls += 1
            if calls == 1:
                return io.BytesIO(json.dumps({
                    "total_count": 101,
                    "workflow_runs": [{} for _ in range(100)],
                }).encode())
            raise urllib.error.URLError("second page unavailable")

        with patch("scripts.check_release_workflows.urllib.request.urlopen",
                   side_effect=respond):
            with self.assertRaisesRegex(WorkflowGateError, "Cannot obtain"):
                fetch_evidence("CopyPasteUser/Ricebowl", SHA, "test-token")
        self.assertEqual(calls, 2)

    def test_fetch_evidence_fails_closed_above_bounded_page_limit(self):
        calls = 0

        def respond(_request, timeout):
            nonlocal calls
            calls += 1
            return io.BytesIO(json.dumps({
                "total_count": 1001,
                "workflow_runs": [{} for _ in range(100)],
            }).encode())

        with patch("scripts.check_release_workflows.urllib.request.urlopen",
                   side_effect=respond):
            with self.assertRaisesRegex(WorkflowGateError, "Too many"):
                fetch_evidence("CopyPasteUser/Ricebowl", SHA, "test-token")
        self.assertEqual(calls, 10)

    def test_malformed_or_absent_evidence_fails_closed(self):
        for value in (None, [], {}, {"workflow_runs": "invalid"},
                      {"workflow_runs": []}):
            with self.subTest(value=value), self.assertRaises(WorkflowGateError):
                validate_runs(value, SHA)

    def test_stable_release_uses_hardware_tested_ancestor_not_signoff_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".github").mkdir()
            file = root / ".github/release-signoff-1.0.json"
            file.write_text(json.dumps({"tested_source_commit": SHA}), encoding="utf-8")
            self.assertEqual(source_for_tag("v1.0.0", OTHER, root), SHA)
            self.assertEqual(source_for_tag("v1.0.0-rc.1", OTHER, root), OTHER)
            file.write_text(json.dumps({"tested_source_commit": "invalid"}), encoding="utf-8")
            with self.assertRaisesRegex(WorkflowGateError, "Invalid"):
                source_for_tag("v1.0.0", OTHER, root)


if __name__ == "__main__":
    unittest.main()
