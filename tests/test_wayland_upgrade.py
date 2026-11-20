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
SESSION_PREVIEW2_SHA = "c8274dee78386124470cb5ff9a4d2768bb019126"


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

    def test_native_and_session_use_real_older_sources_and_verify_installed_bytes(self):
        smoke = (ROOT / "scripts/smoke_wayland_upgrade_rollback.sh").read_text()
        self.assertIn(f"session_baseline={SESSION_PREVIEW2_SHA}", smoke)
        self.assertIn('worktree add --detach "$session_worktree" "$session_baseline"', smoke)
        self.assertIn('worktree add --detach "$worktree" "$baseline"', smoke)
        self.assertIn('"$session_worktree/scripts/build_wayland_session_deb.sh"', smoke)
        self.assertIn('"$worktree/scripts/build_riceplate_native_deb.sh"', smoke)
        self.assertIn('cargo build --release --locked', smoke)
        self.assertIn('cargo generate-lockfile', smoke)
        self.assertIn('cargo update --manifest-path', smoke)
        self.assertIn('--package uuid --precise 1.26.0', smoke)
        self.assertIn('old_native="$temp/old-packages/ricebowl-riceplate-native_0.1.0~preview1_amd64.deb"', smoke)
        self.assertIn('old_session2="$temp/old-packages/ricebowl-wayland-session_0.1.0~preview2_all.deb"', smoke)
        self.assertIn('check_version "$old_native" ricebowl-riceplate-native', smoke)
        self.assertIn('check_version "$old_session2" ricebowl-wayland-session', smoke)
        self.assertIn('PHASE 1b/5: real Session preview2 -> preview3', smoke)
        self.assertIn('PHASE 4/5: explicit rollback of saved previous Core/Meta/Native', smoke)
        self.assertIn('PHASE 5/5: re-upgrade every component', smoke)
        self.assertIn('/tmp/ricebowl-old-native.sha256', smoke)
        self.assertIn('/tmp/ricebowl-new-native.sha256', smoke)
        self.assertIn('sha256sum /usr/bin/riceplate-native', smoke)
        self.assertIn('check_version ricebowl-wayland-session', smoke)
        self.assertIn('test -z "$(dpkg --audit)"', smoke)
        # The historical native does not have a tracked Cargo.lock; this
        # source rebuild must not be presented as the historical binary's
        # reproducibility or a cryptographically signed release provenance.
        self.assertIn('NOT a byte-for-byte', smoke)

    def test_fatal_native_and_session_dpkg_configuration_is_recovered(self):
        script = (ROOT / "scripts/smoke_wayland_upgrade_rollback.sh").read_text()
        self.assertIn('for component in native session; do', script)
        self.assertIn("kill -KILL", script)
        self.assertIn('dpkg -i "$injected/broken.deb"', script)
        self.assertIn('dpkg -i "$authentic"', script)
        self.assertIn("post-installation script.*killed by signal", script)
        self.assertIn('check_user_state', script)
        self.assertIn('assert_selected xp-luna-columns', script)
        self.assertIn('sha256sum -c --status /tmp/ricebowl-v12-before.sha256', script)
        self.assertNotIn("rm -rf /home", script)
        self.assertNotIn("apt-get purge -y ricebowl-wayland-desktop", script.split('PHASE 3c/5:', 1)[1].split('PHASE 4/5:', 1)[0])

    def test_old_selected_rice_and_luna_v12_survive_real_apt_transition(self):
        script = (ROOT / "scripts/smoke_wayland_upgrade_rollback.sh").read_text()
        self.assertIn("/usr/lib/ricebowl-wayland/examples/wayland/heritage-modern-v10.json", script)
        self.assertIn("assert_review \"$legacy\" heritage-modern-v10 10", script)
        self.assertIn("run_as_owner de recipe-select --recipe heritage-modern-v10", script)
        self.assertIn("assert_selected heritage-modern-v10", script)
        self.assertIn("/usr/lib/ricebowl-wayland/examples/wayland/xp-luna-columns.json", script)
        self.assertIn("assert_review \"$luna\" xp-luna-columns 12", script)
        self.assertIn("run_as_owner de recipe-select --recipe xp-luna-columns", script)
        self.assertIn("run_as_owner de recipe-restore", script)
        self.assertIn("if run_as_owner de review --recipe \"$luna\"", script)
        self.assertIn("sha256sum -c --status /tmp/ricebowl-v12-before.sha256", script)
        self.assertIn("runuser -u owner", script)

    def test_interrupted_postinst_fault_is_repaired_without_user_or_xfce_reset(self):
        script = (ROOT / "scripts/smoke_wayland_upgrade_rollback.sh").read_text()
        self.assertIn("PHASE 3b/5: power-loss simulation", script)
        self.assertIn('dpkg-deb --raw-extract "$new_core"', script)
        self.assertIn('"$interruption/unpacked/DEBIAN/postinst"', script)
        self.assertIn('kill -KILL "$$"', script)
        self.assertNotIn('kill -KILL "$"', script)
        self.assertIn("post-installation script.*killed by signal", script)
        self.assertIn("Fault injection did not kill the package postinst", script)
        self.assertIn('dpkg -i "$interruption/interrupted-core.deb"', script)
        self.assertIn("Fault injection did not interrupt package configuration", script)
        self.assertIn('dpkg -i "$new_core"', script)
        self.assertIn('test -z "$(dpkg --audit)"', script)
        # Verify the selected old + new user-authored recipes survive the
        # mid-configuration failure and subsequent authentic-package repair.
        before, after = script.split("PHASE 3b/5:", 1)
        recovered = after.split("PHASE 4/5:", 1)[0]
        self.assertIn('sha256sum -c --status /tmp/ricebowl-v12-before.sha256',
                      recovered)
        self.assertIn('assert_selected xp-luna-columns', recovered)
        self.assertIn('check_user_state', recovered)
        self.assertIn('assert_review "$legacy" heritage-modern-v10 10', recovered)
        self.assertIn('assert_review "$luna" xp-luna-columns 12', recovered)
        self.assertNotIn("apt-get purge", recovered)
        self.assertNotIn("rm -rf /home", recovered)
        self.assertIn("docker run --rm -i", before)

    def test_session_reverse_transition_respects_real_meta_dependency(self):
        smoke = (ROOT / "scripts/smoke_wayland_upgrade_rollback.sh").read_text()
        downgrade = smoke.split("PHASE 3d/5:", 1)[1].split("PHASE 4/5:", 1)[0]
        # Both current and historical Meta require Session >= preview3.
        # Never force dpkg to downgrade Session under an installed Meta.
        self.assertLess(downgrade.index("apt-get remove -y ricebowl-wayland-desktop"),
                        downgrade.index('"$old_session2"'))
        self.assertLess(downgrade.index('"$old_session2"'),
                        downgrade.index('"$old_session3"'))
        self.assertIn("--allow-downgrades", downgrade)
        self.assertIn("check_version ricebowl-wayland-session '0.1.0~preview2'", downgrade)
        self.assertIn("check_version ricebowl-wayland-session '0.1.0~preview3'", downgrade)
        self.assertIn('\"$old_session_payload\"', downgrade)
        self.assertIn('check_version ricebowl-wayland-core', downgrade)
        self.assertIn('check_version ricebowl-riceplate-native', downgrade)
        self.assertIn('test -z "$(dpkg --audit)"', downgrade)
        self.assertIn("assert_selected xp-luna-columns", downgrade)
        self.assertIn("check_user_state", downgrade)
        self.assertIn("sha256sum -c --status /tmp/ricebowl-v12-before.sha256", downgrade)
        self.assertNotIn("--force-depends", downgrade)
        self.assertNotIn("apt-get purge", downgrade)
        self.assertNotIn("rm -rf /home", downgrade)

    def test_provenance_is_part_of_core_package_not_user_config(self):
        builder = (ROOT / "scripts/build_wayland_core_deb.sh").read_text()
        self.assertIn("git -C \"$project_root\" rev-parse --verify HEAD", builder)
        self.assertIn("usr/lib/ricebowl-wayland/BUILDINFO", builder)
        self.assertIn("source_commit=%s", builder)
        self.assertNotIn("HOME/", builder)
        self.assertNotIn("/etc/xdg", builder)

    def test_installed_native_login_recovers_from_corrupt_user_settings(self):
        smoke = (ROOT / "scripts/smoke_wayland_packaged_login.sh").read_text()
        self.assertIn('printf "%s\\n" "{broken-selection"', smoke)
        self.assertIn('printf "%s\\n" "{broken-preferences"', smoke)
        self.assertIn("ignoring invalid saved recipe selection:", smoke)
        self.assertIn("ignoring unsafe RiceSpice preferences:", smoke)
        self.assertIn('"$runtime/corrupt-fallback.png"', smoke)
        self.assertIn('sha256sum -c --status "$runtime/corrupt-before.sha256"', smoke)
        self.assertIn("^RICEBOWL_DE_RECIPE=", smoke)


if __name__ == "__main__":
    unittest.main()
