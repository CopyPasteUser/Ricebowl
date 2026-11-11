"""Versioned Wayland Debian upgrade/downgrade release contracts.

Heavy apt lifecycle is exercised in the native Ubuntu 24.04 CI container.
These tests fail quickly on incompatible package metadata or a missing
pinned-baseline rollback path, even on a non-Debian developer machine.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging/wayland"
BASELINE_SHA = "b3d615a7cc508049050eb06c7952ef5a8d26e598"


def field(path: str, key: str) -> str:
    text = (PACKAGING / path).read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(key)}: (.+)$", text, re.MULTILINE)
    if match is None:
        raise AssertionError(f"{path}: missing Debian {key}")
    return match.group(1)


class DebianUpgradeContracts(unittest.TestCase):
    def test_current_core_native_and_meta_have_consistent_dependency_versions(self):
        self.assertEqual(field("core-control", "Version"), "0.1.0~preview2")
        self.assertEqual(field("desktop-control", "Version"), "0.1.0~preview3")
        self.assertIn("ricebowl-wayland-core (= 0.1.0~preview2)",
                      field("desktop-control", "Depends"))
        self.assertEqual(field("control", "Version"), "0.1.0~preview3")
        self.assertEqual(field("native-control.in", "Version"), "0.1.0~preview2")
        self.assertIn("ricebowl-riceplate-native (>= 0.1.0~preview2)",
                      field("desktop-control", "Depends"))

    @unittest.skipUnless(shutil.which("dpkg"), "Debian version ordering unavailable")
    def test_upgrade_version_is_strictly_newer_than_pinned_baseline(self):
        self.assertEqual(subprocess.run(
            ["dpkg", "--compare-versions", "0.1.0~preview1", "lt", "0.1.0~preview2"],
            check=False, timeout=5).returncode, 0)
        self.assertEqual(subprocess.run(
            ["dpkg", "--compare-versions", "0.1.0~preview2", "lt", "0.1.0~preview3"],
            check=False, timeout=5).returncode, 0)

    def test_rollback_smoke_uses_pinned_old_sources_and_real_apt(self):
        script = (ROOT / "scripts/smoke_wayland_upgrade_rollback.sh").read_text()
        self.assertIn(f"baseline={BASELINE_SHA}", script)
        self.assertIn('worktree add --detach "$worktree" "$baseline"', script)
        self.assertIn('"$worktree/scripts/build_wayland_core_deb.sh"', script)
        self.assertIn('"$worktree/scripts/build_wayland_desktop_deb.sh"', script)
        self.assertIn("--allow-downgrades", script)
        self.assertIn("truncate -s 41", script)
        self.assertIn("sha256sum -c --status", script)
        self.assertIn("ricebowl-wayland-desktop", script)
        self.assertIn("check_user_state", script)
        self.assertIn("apt-get purge", script)
        self.assertIn("docker run --rm -i", script)

    def test_provenance_is_part_of_core_package_not_user_config(self):
        builder = (ROOT / "scripts/build_wayland_core_deb.sh").read_text()
        self.assertIn("git -C \"$project_root\" rev-parse --verify HEAD", builder)
        self.assertIn("usr/lib/ricebowl-wayland/BUILDINFO", builder)
        self.assertIn("source_commit=%s", builder)
        self.assertNotIn("HOME/", builder)
        self.assertNotIn("/etc/xdg", builder)


if __name__ == "__main__":
    unittest.main()
