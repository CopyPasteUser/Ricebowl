"""Fail-closed boundaries for the SG6 clean-checkout four-package rebuild gate.

The complete byte-for-byte rebuild runs in native GitHub CI with real .deb
archives and an actual native ELF. These focused tests inject failure at the
gate's trust boundaries without installing anything on the test host.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/verify_wayland_clean_rebuild.sh"
WORKFLOW = ROOT / ".github/workflows/riceplate-native.yml"


@unittest.skipUnless(shutil.which("git") and shutil.which("bash"),
                     "Git and bash are needed for the isolated source fixture")
class CleanRebuildGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ricebowl-rebuild-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir()
        shutil.copyfile(SCRIPT, self.root / "scripts/verify_wayland_clean_rebuild.sh")
        subprocess.run(["git", "-C", str(self.root), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=CI",
                        "-c", "user.email=ci@example.invalid",
                        "commit", "--allow-empty", "-qm", "isolated source fixture"],
                       check=True)
        self.sha = subprocess.check_output(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True).strip()
        self.packages = []
        for name in ("core", "session", "native", "desktop"):
            path = self.root / (name + ".deb")
            path.write_bytes(b"synthetic test boundary; not a Debian archive")
            self.packages.append(str(path))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("dpkg-deb", "dpkg-shlibdeps", "readelf", "cmp", "sha256sum"):
            stub = self.bin / name
            stub.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = --field ]; then\n"
                "  printf '%s\\n' \"$FAKE_SOURCE_COMMIT\"\n"
                "else\n"
                "  printf '%s\\n' \"$1\" >> \"$DPKG_CALLS\"\n"
                "  exit 93\n"
                "fi\n", encoding="utf-8")
            stub.chmod(0o755)
        verifier = self.root / "scripts/verify_wayland_package_set.sh"
        verifier.write_text(
            "#!/bin/sh\n"
            "printf 'called\\n' >> \"$VERIFIER_LOG\"\n"
            "exit \"$VERIFIER_EXIT\"\n", encoding="utf-8")
        verifier.chmod(0o755)
        self.verifier_log = self.root / "verifier.log"
        self.dpkg_calls = self.root / "dpkg.log"

    def invoke(self, *packages, claimed=None, validator_exit=0):
        env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                   FAKE_SOURCE_COMMIT=claimed or self.sha,
                   VERIFIER_LOG=str(self.verifier_log),
                   VERIFIER_EXIT=str(validator_exit),
                   DPKG_CALLS=str(self.dpkg_calls))
        return subprocess.run(
            ["bash", str(self.root / "scripts/verify_wayland_clean_rebuild.sh"),
             *(self.packages if not packages else packages)],
            env=env, text=True, capture_output=True, timeout=15, check=False)

    def test_missing_and_relative_inputs_block_before_any_verifier(self):
        result = subprocess.run(
            ["bash", str(self.root / "scripts/verify_wayland_clean_rebuild.sh")],
            capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        invalid = self.invoke("relative-core.deb", *self.packages[1:])
        self.assertEqual(invalid.returncode, 2)
        self.assertFalse(self.verifier_log.exists())
        self.assertFalse(self.dpkg_calls.exists())

    def test_unsafe_bundle_blocks_before_archive_extraction(self):
        rejected = self.invoke(validator_exit=71)
        self.assertEqual(rejected.returncode, 71)
        self.assertEqual(self.verifier_log.read_text(), "called\n")
        self.assertFalse(self.dpkg_calls.exists())

    def test_self_reported_commit_cannot_impersonate_checked_out_source(self):
        rejected = self.invoke(claimed="0" * 40)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("does not match checked-out source commit", rejected.stderr)
        self.assertEqual(self.verifier_log.read_text(), "called\n")
        self.assertFalse(self.dpkg_calls.exists())

    def test_rebuild_is_a_required_native_ci_step_with_both_path_triggers(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("bash scripts/verify_wayland_clean_rebuild.sh", workflow)
        for filename in ("scripts/verify_wayland_clean_rebuild.sh",
                         "tests/test_wayland_clean_rebuild.py"):
            self.assertEqual(workflow.count("      - '" + filename + "'"), 2,
                             "must trigger on both push and pull request")
        self.assertLess(workflow.index("Reject inconsistent or unsafe Wayland release packages"),
                        workflow.index("Rebuild all four packages from clean tracked source"))
        self.assertLess(workflow.index("Rebuild all four packages from clean tracked source"),
                        workflow.index("Install, reinstall and purge complete preview"))


if __name__ == "__main__":
    unittest.main()
