"""SG7 local dossier: built from a local CI receipt, never from the Actions API."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("sg7_local_dossier", SCRIPTS / "sg7_local_dossier.py")
dossier = importlib.util.module_from_spec(spec)
sys.modules["sg7_local_dossier"] = dossier
spec.loader.exec_module(dossier)
lci = dossier.lci

SHA = "1b10db548ba1e11345b1941c79d581f788be9aee"
REAL_RECEIPT = ROOT / "docs" / "evidence" / "local-ci" / SHA[:12] / "receipt.json"
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=GIT_ENV)


def comparison_for(receipt: dict, **overrides) -> dict:
    report = {
        "schema_version": 1, "source_sha": SHA, "software_ci_only": True, "hardware_accepted": False,
        "separate_runner_names_observed": True, "distinct_hostname_hashes_observed": True,
        "byte_identical_package_count": 4, "same_runner_os_and_build_tools": True,
        "runner_image_versions": {"host-a": "x", "host-b": "x"},
        "independent_external_provenance_certified": False,
        "packages": dict(receipt["artifacts"]["sg6_packages"]),
        "cargo_lock_sha256": "c" * 64, "limitations": ["two sessions are not independent builders"],
    }
    report.update(overrides)
    return report


class LocalCIMappingTests(unittest.TestCase):
    def test_dossier_collector_exclusion_points_at_the_local_dossier(self):
        reasons = [why for w, j, n, why in lci.NOT_TRANSLATED if w == "sg7-exact-main.yml"]
        self.assertEqual(len(reasons), 1)
        self.assertIn("scripts/sg7_local_dossier.py", reasons[0])
        self.assertTrue((SCRIPTS / "sg7_local_dossier.py").is_file())

    def test_unit_step_runs_every_sg7_evidence_test(self):
        body = lci.CATALOG_BY_ID["sg7-matrix-unit"].script.read_text()
        for module in ("test_sg7_safe_receipt_io", "test_sg7_dossier_io", "test_sg7_local_dossier",
                       "test_sg7_exact_main_matrix"):
            self.assertIn(f"tests.{module}", body)
        self.assertIn("scripts/sg7_local_dossier.py", body)


@unittest.skipUnless(REAL_RECEIPT.is_file(), "committed local CI receipt not in this checkout")
class LocalDossierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = json.loads(REAL_RECEIPT.read_text())

    def build(self, receipt="real", *, committed=True, comparison=None, error=None, sha=SHA):
        receipt = self.receipt if isinstance(receipt, str) and receipt == "real" else receipt
        return dossier.build_report(
            sha=sha, receipt=receipt, receipt_path="r.json", receipt_sha256="d" * 64,
            receipt_committed=committed, comparison=comparison, comparison_path="c.json",
            comparison_sha256=None if comparison is None else "e" * 64, comparison_read_error=error,
            release_signoff={"path": "s", "status": "pending", "file_sha256": None},
            checkout_catalog_sha256="f" * 64)

    def test_every_hosted_check_has_local_steps_in_the_catalog(self):
        self.assertEqual({c[0] for c in dossier.CHECKS}, set(dossier.LOCAL_AREAS))
        for code, ids in dossier.LOCAL_AREAS.items():
            self.assertTrue(ids, code)
            for sid in ids:
                self.assertIn(sid, lci.CATALOG_BY_ID, f"{code}: {sid}")

    def test_real_receipt_passes_locally_and_reports_sg6_comparison_missing(self):
        report = self.build()
        self.assertEqual(report["local_ci_execution"], "passed")
        self.assertTrue(all(c["status"] == "passed" for c in report["checks"]))
        self.assertEqual(len(report["checks"]), len(dossier.CHECKS))
        self.assertEqual(report["receipt"]["dispatch_only_steps"], {"portal-gpu-frame": "BLOCKED"})
        self.assertEqual(report["sg6_two_session_comparison"]["status"], "missing")
        self.assertFalse(report["ready_for_formal_review"])
        self.assertEqual(len(report["blockers"]), 1)
        self.assertIn("comparison is missing", report["blockers"][0])
        self.assertEqual(len(report["workflow_steps"]), len(self.receipt["steps"]))
        self.assertTrue(report["workflow_steps_not_translated"])
        for flag in ("physical_hardware_accepted", "formal_sg6_closed", "formal_sg7_closed"):
            self.assertIs(report[flag], False)
        self.assertTrue(report["software_ci_only"])
        self.assertTrue(any("Hardware" in u for u in report["unverified_requirements"]))
        self.assertTrue(any("two-session" in u for u in report["unverified_requirements"]))

    def test_verified_comparison_is_ready_but_never_closes_gates(self):
        report = self.build(comparison=comparison_for(self.receipt))
        self.assertEqual(report["sg6_two_session_comparison"]["status"], "verified")
        self.assertTrue(report["ready_for_formal_review"])
        self.assertEqual(report["blockers"], [])
        self.assertFalse(report["formal_sg6_closed"] or report["formal_sg7_closed"]
                         or report["physical_hardware_accepted"])
        self.assertTrue(report["unverified_requirements"])

    def test_forged_or_mismatched_comparison_is_invalid_not_certified(self):
        cases = {
            "other sha": comparison_for(self.receipt, source_sha="b" * 40),
            "hardware claim": comparison_for(self.receipt, hardware_accepted=True),
            "external provenance claim": comparison_for(self.receipt, independent_external_provenance_certified=True),
            "three packages": comparison_for(self.receipt, byte_identical_package_count=3),
            "same runner": comparison_for(self.receipt, separate_runner_names_observed=False),
            "package digests differ from the receipt": comparison_for(
                self.receipt, packages={k: "0" * 64 for k in self.receipt["artifacts"]["sg6_packages"]}),
            "not an object": ["x"],
        }
        for label, comparison in cases.items():
            with self.subTest(label):
                report = self.build(comparison=comparison)
                self.assertEqual(report["sg6_two_session_comparison"]["status"], "invalid")
                self.assertFalse(report["ready_for_formal_review"])
                self.assertEqual(report["local_ci_execution"], "passed")
        report = self.build(error="SG6 comparison report unreadable: boom")
        self.assertEqual(report["sg6_two_session_comparison"]["status"], "invalid")

    def test_receipt_for_another_sha_is_blocked(self):
        report = self.build(sha="a" * 40)
        self.assertEqual(report["local_ci_execution"], "blocked")
        self.assertTrue(any("not the requested main SHA" in b for b in report["blockers"]))
        self.assertFalse(report["ready_for_formal_review"])

    def test_incomplete_receipts_are_blocked(self):
        failed = copy.deepcopy(self.receipt)
        rec = next(r for r in failed["steps"] if r["id"] == "rust-test")
        rec["status"], rec["exit_code"] = "FAIL", 1
        failed["counts"]["PASS"] -= 1
        failed["counts"]["FAIL"] += 1
        failed["complete"] = False
        report = self.build(failed)
        self.assertEqual(report["local_ci_execution"], "blocked")
        self.assertEqual(next(c for c in report["checks"] if c["id"] == "rust-test-clippy-build")["status"], "blocked")

        forged = copy.deepcopy(failed)      # claims complete despite the FAIL
        forged["complete"] = True
        self.assertEqual(self.build(forged)["local_ci_execution"], "blocked")

        dirty = copy.deepcopy(self.receipt)
        dirty["tree_clean"] = False
        dirty["complete"] = False
        self.assertEqual(self.build(dirty)["local_ci_execution"], "blocked")

    def test_a_blocked_required_step_is_blocked_but_the_gpu_step_may_be(self):
        blocked = copy.deepcopy(self.receipt)
        rec = next(r for r in blocked["steps"] if r["id"] == "portal-strict-frame")
        rec["status"], rec["exit_code"], rec["detail"] = "BLOCKED", None, "no portal backend"
        blocked["counts"]["PASS"] -= 1
        blocked["counts"]["BLOCKED"] += 1
        blocked["complete"] = False
        report = self.build(blocked)
        self.assertEqual(report["local_ci_execution"], "blocked")
        self.assertEqual(next(c for c in report["checks"]
                              if c["id"] == "portal-strict-software-frame")["status"], "blocked")

    def test_receipt_missing_a_catalog_step_is_blocked(self):
        short = copy.deepcopy(self.receipt)
        short["steps"] = [r for r in short["steps"] if r["id"] != "pkg-tamper"]
        short["counts"]["PASS"] -= 1
        report = self.build(short)
        self.assertEqual(report["local_ci_execution"], "blocked")
        self.assertTrue(any("pkg-tamper" in b for b in report["blockers"]))

    def test_malformed_receipt_is_blocked_without_crashing(self):
        for bad in ({}, [], {"schema_version": 1}, "garbage", None):
            with self.subTest(bad=bad):
                report = self.build(bad)
                self.assertEqual(report["local_ci_execution"], "blocked")
                self.assertFalse(report["ready_for_formal_review"])
                self.assertTrue(all(c["status"] == "blocked" for c in report["checks"]))

    def test_uncommitted_or_unknowable_receipt_state_blocks(self):
        for committed in (False, None):
            with self.subTest(committed=committed):
                report = self.build(committed=committed)
                self.assertEqual(report["local_ci_execution"], "blocked")
                self.assertFalse(report["ready_for_formal_review"])

    def test_markdown_states_missing_comparison_and_no_signoff(self):
        text = dossier.render_markdown(self.build())
        self.assertIn("**missing**", text)
        self.assertIn("physical hardware accepted: false", text)
        self.assertIn("Not certified", text)
        self.assertIn("Receipt catalog", text)


@unittest.skipUnless(REAL_RECEIPT.is_file(), "committed local CI receipt not in this checkout")
class LocalDossierCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="sg7-local-")
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.dir = self.repo / "docs" / "evidence" / "local-ci" / SHA[:12]
        self.dir.mkdir(parents=True)
        (self.dir / "receipt.json").write_bytes(REAL_RECEIPT.read_bytes())
        git(self.repo, "init", "-q")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "receipt")
        self.out = Path(self.tmp.name) / "out" / "dossier.json"
        self.md = Path(self.tmp.name) / "out" / "dossier.md"

    def run_main(self, *extra, sha=SHA):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = dossier.main(["--sha", sha, "--repo", str(self.repo), "--output", str(self.out), *extra])
        return code, out.getvalue(), err.getvalue()

    def test_writes_private_write_once_dossier_and_exits_blocked_while_sg6_is_missing(self):
        code, stdout, stderr = self.run_main("--markdown", str(self.md))
        self.assertEqual(code, 1)
        self.assertIn("SG6 comparison missing", stdout)
        self.assertIn("BLOCKED: SG6 two-session", stderr)
        data = json.loads(self.out.read_text())
        self.assertEqual(data["source_sha"], SHA)
        self.assertEqual(data["local_ci_execution"], "passed")
        self.assertEqual(data["sg6_two_session_comparison"]["status"], "missing")
        self.assertIs(data["receipt"]["committed_and_unmodified"], True)
        self.assertEqual(data["receipt"]["file_sha256"], hashlib.sha256(REAL_RECEIPT.read_bytes()).hexdigest())
        self.assertEqual(self.out.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.md.stat().st_mode & 0o777, 0o600)
        before = self.out.read_bytes()
        code, _, stderr = self.run_main("--markdown", str(self.md))
        self.assertEqual(code, 2)
        self.assertIn("refusing to overwrite", stderr)
        self.assertEqual(self.out.read_bytes(), before)

    def test_present_valid_comparison_next_to_the_receipt_is_used(self):
        receipt = json.loads((self.dir / "receipt.json").read_text())
        (self.dir / "sg6-comparison.json").write_text(json.dumps(comparison_for(receipt)))
        code, stdout, _ = self.run_main()
        self.assertEqual(code, 0, stdout)
        self.assertEqual(json.loads(self.out.read_text())["sg6_two_session_comparison"]["status"], "verified")

    def test_unreadable_or_forged_comparison_is_invalid_not_missing(self):
        (self.dir / "sg6-comparison.json").write_text("{not json")
        code, _, _ = self.run_main()
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(self.out.read_text())["sg6_two_session_comparison"]["status"], "invalid")

    def test_uncommitted_receipt_is_blocked(self):
        (self.dir / "receipt.json").write_text((self.dir / "receipt.json").read_text() + "\n")
        code, _, stderr = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("not committed", stderr)
        self.assertEqual(json.loads(self.out.read_text())["local_ci_execution"], "blocked")

    def test_bad_inputs_write_nothing(self):
        self.assertEqual(self.run_main(sha="abc")[0], 2)
        self.assertEqual(self.run_main(sha="a" * 40)[0], 2)             # no receipt for that sha
        (self.dir / "receipt.json").unlink()
        os.mkfifo(self.dir / "receipt.json")
        self.assertEqual(self.run_main()[0], 2)                           # FIFO never blocks or reads
        (self.dir / "receipt.json").unlink()
        real = Path(self.tmp.name) / "real.json"
        real.write_bytes(REAL_RECEIPT.read_bytes())
        (self.dir / "receipt.json").symlink_to(real)
        self.assertEqual(self.run_main()[0], 2)                           # symlinks are not followed
        (self.dir / "receipt.json").unlink()
        (self.dir / "receipt.json").write_text('{"sha": "a", "sha": "b"}')
        self.assertEqual(self.run_main()[0], 2)                           # duplicate keys
        self.assertFalse(self.out.exists())

    def test_existing_output_symlink_is_never_followed(self):
        target = Path(self.tmp.name) / "keep.txt"
        target.write_text("keep")
        self.out.parent.mkdir(parents=True)
        self.out.symlink_to(target)
        self.assertEqual(self.run_main()[0], 2)
        self.assertEqual(target.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
