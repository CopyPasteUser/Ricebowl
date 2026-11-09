"""Standalone Wayland Debian package contracts; no host installation."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "scripts/build_wayland_core_deb.sh"
DESKTOP = ROOT / "scripts/build_wayland_desktop_deb.sh"
SESSION = ROOT / "packaging/wayland/ricebowl-wayland-session"


def run(*argv: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, text=True, capture_output=True, timeout=120, env=env,
                          check=False)


@unittest.skipUnless(shutil.which("git") and shutil.which("dpkg-deb"),
                     "Needs a tracked Git checkout and dpkg-deb")
class WaylandBundleTests(unittest.TestCase):
    def test_core_package_is_reproducible_and_standalone(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, second = root / "core-a.deb", root / "core-b.deb"
            env = {**os.environ, "SOURCE_DATE_EPOCH": "1704067200"}
            for target in (first, second):
                result = run("bash", str(CORE), str(target), env=env)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(run("dpkg-deb", "-f", str(first), "Package").stdout.strip(),
                             "ricebowl-wayland-core")
            self.assertEqual(run("dpkg-deb", "-f", str(first), "Architecture").stdout.strip(),
                             "all")
            self.assertIn("python3-gi", run("dpkg-deb", "-f", str(first), "Depends").stdout)
            extracted = root / "extracted"
            self.assertEqual(run("dpkg-deb", "-x", str(first), str(extracted)).returncode, 0)
            application = extracted / "usr/lib/ricebowl-wayland"
            for path in ("launcher.py", "macrice/cli.py", "macrice/de/session.py",
                         "macrice/de/resources/labwc/rc.xml",
                         "macrice/creator_gui.py", "assets/wallpapers/aurora-night.jpg",
                         "examples/wayland/heritage-modern-v10.json"):
                self.assertTrue((application / path).is_file(), path)
            self.assertTrue((extracted / "usr/bin/ricebowl-wayland-app").is_file())
            self.assertFalse(any(p.name == "__pycache__" for p in application.rglob("*")))
            self.assertFalse(any(p.suffix == ".pyc" for p in application.rglob("*")))
            self.assertFalse(any(p.is_symlink() for p in application.rglob("*")))
            help_result = run(sys.executable, "-B", str(application / "launcher.py"),
                              "de", "--help")
            self.assertEqual(help_result.returncode, 0, help_result.stderr)
            result = run("bash", str(CORE), str(first), env=env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing to overwrite", result.stderr)
            invalid = run("bash", str(CORE), "relative.deb", env=env)
            self.assertNotEqual(invalid.returncode, 0)

    def test_aggregate_package_is_reproducible_and_dependency_only(self):
        if run("dpkg", "--print-architecture").stdout.strip() != "amd64":
            self.skipTest("Native bundle currently targets amd64 only")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, second = root / "bundle-a.deb", root / "bundle-b.deb"
            env = {**os.environ, "SOURCE_DATE_EPOCH": "1704067200"}
            for target in (first, second):
                result = run("sh", str(DESKTOP), str(target), env=env)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(run("dpkg-deb", "-f", str(first), "Package").stdout.strip(),
                             "ricebowl-wayland-desktop")
            dependencies = run("dpkg-deb", "-f", str(first), "Depends").stdout
            for name in ("ricebowl-wayland-core", "ricebowl-wayland-session",
                         "ricebowl-riceplate-native"):
                self.assertIn(name, dependencies)
            archive = run("dpkg-deb", "--contents", str(first)).stdout
            self.assertNotIn("postinst", archive)
            self.assertNotIn("usr/bin/", archive)
            self.assertNotIn("wayland-sessions", archive)

    def test_existing_login_wrapper_keeps_legacy_fallback(self):
        contents = SESSION.read_text(encoding="utf-8")
        self.assertIn("app=/usr/bin/ricebowl-wayland-app", contents)
        self.assertIn('app="$HOME/.local/bin/ricebowl"', contents)
        self.assertIn('exec "$app" de start --panel native', contents)
        self.assertIn('exec "$app" de start', contents)
        self.assertNotIn("xfce4-panel", contents)


if __name__ == "__main__":
    unittest.main()
