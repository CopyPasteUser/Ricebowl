"""SG7 regression tests for GitHub runner Ubuntu download mirror fallback.

Never change a real apt configuration: all filesystem write tests use tmp
files and mock the ephemeral GitHub Actions root authorization boundary.
"""
from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts import ci_ubuntu_archive as archive


ROOT = Path(__file__).resolve().parents[1]


class RunnerArchiveTests(unittest.TestCase):
    def test_only_ec2_archive_uris_switch_to_signed_public_ubuntu_mirror(self):
        sample = (
            "Types: deb\nURIs: http://us-east-2.ec2.archive.ubuntu.com/ubuntu/\n"
            "Suites: noble noble-updates noble-backports\n"
            "Components: main universe restricted multiverse\n"
            "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n\n"
            "Types: deb\nURIs: http://security.ubuntu.com/ubuntu/\n"
            "Suites: noble-security\n"
        )
        result = archive.rewrite_sources(sample)
        self.assertEqual(result.count("https://archive.ubuntu.com/ubuntu/"), 1)
        self.assertIn("URIs: http://security.ubuntu.com/ubuntu/", result)
        self.assertIn("Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg", result)
        self.assertIn("Suites: noble noble-updates noble-backports", result)
        self.assertEqual(archive.rewrite_sources(result), result)

    def test_only_whitelisted_exact_archive_hosts_are_changed(self):
        for uri in (
            "http://us-east-2.ec2.archive.ubuntu.com/ubuntu",
            "http://eu-west-1.ec2.archive.ubuntu.com/ubuntu/",
            "http://ap-south-1.ec2.archive.ubuntu.com/ubuntu",
        ):
            with self.subTest(uri=uri):
                self.assertEqual(archive.rewrite_sources(uri),
                                 uri.replace(uri.split("/ubuntu")[0],
                                             "https://archive.ubuntu.com"))
        for uri in (
            "https://archive.ubuntu.com/ubuntu/",
            "http://security.ubuntu.com/ubuntu/",
            "http://evil-us-east-2.ec2.archive.ubuntu.com.attacker/ubuntu/",
            "http://us-east-2.ec2.archive.ubuntu.com/ubuntuevil/",
            "http://some-mirror.example/ubuntu/",
        ):
            self.assertEqual(archive.rewrite_sources(uri), uri)

    def test_runner_helper_fails_closed_on_non_ci_and_symlinks(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ubuntu.sources"
            path.write_text("URIs: http://us-east-2.ec2.archive.ubuntu.com/ubuntu/\n")
            with mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "restricted"):
                    archive.update_runner_sources(path)
            with (
                mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}),
                mock.patch.object(archive.os, "geteuid", return_value=0),
            ):
                linked = Path(td) / "symlink.sources"
                linked.symlink_to(path)
                with self.assertRaisesRegex(RuntimeError, "Unexpected"):
                    archive.update_runner_sources(linked)
            self.assertIn("us-east-2.ec2", path.read_text())

    def test_runner_source_rewrite_is_atomic_and_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ubuntu.sources"
            old = "URIs: http://us-east-2.ec2.archive.ubuntu.com/ubuntu/\n"
            path.write_text(old)
            mode = stat.S_IFREG | 0o644
            with (
                mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}),
                mock.patch.object(archive.os, "geteuid", return_value=0),
                mock.patch.object(Path, "lstat",
                                  return_value=SimpleNamespace(st_mode=mode, st_uid=0)),
            ):
                self.assertTrue(archive.update_runner_sources(path))
                self.assertFalse(archive.update_runner_sources(path))
            self.assertEqual(path.read_text(),
                             "URIs: https://archive.ubuntu.com/ubuntu/\n")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
            self.assertEqual(len(list(Path(td).iterdir())), 1)

    def test_ci_keeps_all_wayland_gates_and_bounds_apt_network_retries(self):
        yaml = (ROOT / ".github/workflows/wayland-session.yml").read_text()
        self.assertEqual(yaml.count("      - 'scripts/ci_ubuntu_archive.py'"), 2)
        self.assertIn("sudo env GITHUB_ACTIONS=true /usr/bin/python3 "
                      "scripts/ci_ubuntu_archive.py", yaml)
        self.assertLess(yaml.index("scripts/ci_ubuntu_archive.py\n          sudo"),
                        yaml.index("apt-get -o Acquire::Retries"))
        self.assertEqual(yaml.count("Acquire::Retries=2"), 3)
        self.assertEqual(yaml.count("Acquire::https::Timeout=15"), 3)
        for contract in (
            "Validate and test isolated session runtime",
            "Build non-installed login session package",
            "Boot actual labwc and Waybar headlessly",
            "Verify real source-locked Mako 1.11 notification arrivals in labwc",
            "Capture real Luna GTK system UI under native labwc",
        ):
            self.assertIn(contract, yaml)


    def test_gtk_python_ci_uses_same_source_and_exact_package_list(self):
        yaml = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertEqual(yaml.count("Install GTK introspection for Linux tests"), 1)
        self.assertIn("timeout-minutes: 20", yaml)
        self.assertIn(
            "sudo env GITHUB_ACTIONS=true /usr/bin/python3 scripts/ci_ubuntu_archive.py",
            yaml,
        )
        self.assertEqual(yaml.count("Acquire::Retries=2"), 2)
        self.assertEqual(yaml.count("Acquire::http::Timeout=15"), 2)
        self.assertEqual(yaml.count("Acquire::https::Timeout=15"), 2)
        self.assertIn("apt-get -o Acquire::Retries=2", yaml)
        self.assertIn(
            "install -y python3-gi python3-cairo python3-gi-cairo python3-pil "
            "gir1.2-gtk-3.0 xvfb dbus-x11 gir1.2-wnck-3.0 "
            "librsvg2-common xfwm4 xfconf thunar xdotool", yaml,
        )
        # A successful dependency step is never allowed to replace the actual
        # Python/GTK/Xvfb, RiceSpice or screenshot acceptance suite.
        for step in (
            "/usr/bin/python3 -m unittest discover -s tests -v",
            "tests.test_de_settings_gui -v",
            "tests.test_wayland_luna_settings -v",
            "tests.test_luna_system_ux_fidelity -v",
        ):
            self.assertIn(step, yaml)
        self.assertLess(
            yaml.index("scripts/ci_ubuntu_archive.py"),
            yaml.index("Install GTK introspection for Linux tests") + 500,
        )


if __name__ == "__main__":
    unittest.main()
