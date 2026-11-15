"""A public 1.0 tag cannot outrun version metadata or device acceptance."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.check_release_contract import (ReleaseGateError, check_release,
                                            read_version, verify_tested_source)


class ReleaseContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "macrice").mkdir()
        (self.root / ".github").mkdir()
        self.write_version("0.9.1", "0.9.1")

    def write_version(self, package: str, module: str):
        (self.root / "pyproject.toml").write_text(
            f'[project]\nname = "ricebowl-xfce"\nversion = "{package}"\n\n[tool.ruff]\n',
            encoding="utf-8")
        (self.root / "macrice/__init__.py").write_text(
            f'__version__ = "{module}"\n', encoding="utf-8")

    def test_repository_version_metadata_matches(self):
        from macrice import __version__
        self.assertEqual(read_version(Path(__file__).resolve().parents[1]), __version__)

    def test_mismatched_metadata_and_tags_are_blocked(self):
        self.write_version("0.9.1", "0.9.0")
        with self.assertRaisesRegex(ReleaseGateError, "versions differ"):
            check_release(self.root, None)
        self.write_version("0.9.1", "0.9.1")
        for tag in ("v1.0.0", "v0.9.1-rc.0", "0.9.1", "v0.9.1-garbage"):
            with self.subTest(tag=tag), self.assertRaises(ReleaseGateError):
                check_release(self.root, tag)
        self.assertEqual(check_release(self.root, "v0.9.1-rc.1"), "0.9.1")

    def test_stable_one_zero_requires_explicit_evidence_for_every_gate(self):
        self.write_version("1.0.0", "1.0.0")
        self.assertEqual(check_release(self.root, "v1.0.0-rc.1"), "1.0.0")
        with self.assertRaisesRegex(ReleaseGateError, "sign-off"):
            check_release(self.root, "v1.0.0")
        signoff = {"status": "pending", "device": "ThinkPad X1 Yoga 2nd",
                   "tested_source_commit": "a" * 40,
                   "date_utc": "2026-11-06", "evidence": {
                       name: "Tested: QA log" for name in (
                           "login_and_recovery", "xfce_rollback", "xwayland_and_portals",
                           "shell_and_hardware", "authoring_and_switch", "performance")}}
        location = self.root / ".github/release-signoff-1.0.json"
        location.write_text(json.dumps(signoff), encoding="utf-8")
        with self.assertRaisesRegex(ReleaseGateError, "real-device acceptance"):
            check_release(self.root, "v1.0.0")
        signoff["status"] = "approved"
        location.write_text(json.dumps(signoff), encoding="utf-8")
        with mock.patch("scripts.check_release_contract.verify_tested_source") as verify:
            self.assertEqual(check_release(self.root, "v1.0.0"), "1.0.0")
        verify.assert_called_once_with(self.root, "a" * 40)
        signoff["tested_source_commit"] = 42
        location.write_text(json.dumps(signoff), encoding="utf-8")
        with self.assertRaisesRegex(ReleaseGateError, "real-device acceptance"):
            check_release(self.root, "v1.0.0")


    @unittest.skipUnless(shutil.which("git"), "Git required for source ancestry verification")
    def test_hardware_signoff_only_allows_its_own_followup_commit(self):
        def git(*args):
            return subprocess.check_output(
                ["git", "-C", str(self.root), *args], text=True, timeout=10).strip()

        git("init", "-q")
        git("config", "user.name", "RiceBowl CI")
        git("config", "user.email", "ricebowl-ci@example.invalid")
        git("config", "commit.gpgsign", "false")
        runtime = self.root / "runtime.py"
        runtime.write_text("safe = True\n", encoding="utf-8")
        git("add", ".")
        git("commit", "-qm", "hardware-tested snapshot")
        tested = git("rev-parse", "HEAD")
        signoff = self.root / ".github/release-signoff-1.0.json"
        signoff.write_text(json.dumps({"tested_source_commit": tested}), encoding="utf-8")
        git("add", ".github/release-signoff-1.0.json")
        git("commit", "-qm", "record device results")
        verify_tested_source(self.root, tested)
        runtime.write_text("safe = False\n", encoding="utf-8")
        git("add", "runtime.py")
        git("commit", "-qm", "alter runtime after hardware test")
        with self.assertRaisesRegex(ReleaseGateError, "changed after"):
            verify_tested_source(self.root, tested)
        with self.assertRaisesRegex(ReleaseGateError, "ancestry"):
            verify_tested_source(self.root, "a" * 40)


if __name__ == "__main__":
    unittest.main()
