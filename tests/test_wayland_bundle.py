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
VERIFY = ROOT / "scripts/verify_wayland_package_set.sh"


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
            self.assertEqual(run("dpkg-deb", "-f", str(first), "Version").stdout.strip(),
                             "0.1.0~preview2")
            self.assertIn("python3-gi", run("dpkg-deb", "-f", str(first), "Depends").stdout)
            extracted = root / "extracted"
            self.assertEqual(run("dpkg-deb", "-x", str(first), str(extracted)).returncode, 0)
            application = extracted / "usr/lib/ricebowl-wayland"
            for path in ("launcher.py", "macrice/cli.py", "macrice/de/session.py",
                         "macrice/de/resources/labwc/rc.xml",
                         "macrice/creator_gui.py", "assets/wallpapers/aurora-night.jpg",
                         "examples/wayland/heritage-modern-v10.json"):
                self.assertTrue((application / path).is_file(), path)
            buildinfo = extracted / "usr/lib/ricebowl-wayland/BUILDINFO"
            self.assertTrue(buildinfo.is_file())
            lines = buildinfo.read_text(encoding="utf-8").splitlines()
            self.assertIn("format=1", lines)
            self.assertIn("version=0.1.0~preview2", lines)
            self.assertIn("source_date_epoch=1704067200", lines)
            commit = subprocess.check_output(
                ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                text=True, timeout=10).strip()
            self.assertIn(f"source_commit={commit}", lines)
            self.assertTrue((extracted / "usr/bin/ricebowl-wayland-app").is_file())
            private_command = extracted / "usr/lib/ricebowl-wayland/bin/ricebowl"
            self.assertTrue(private_command.is_file())
            self.assertTrue(os.access(private_command, os.X_OK))
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

    def test_packages_use_head_even_with_staged_and_unstaged_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary) / "checkout"
            added = run("git", "-C", str(ROOT), "worktree", "add", "--detach", "-q",
                        str(checkout), "HEAD")
            self.assertEqual(added.returncode, 0, added.stderr)
            try:
                # Exercise the new builders in an isolated tree while leaving
                # the real checkout and its current changes untouched.
                for name in ("build_wayland_core_deb.sh", "build_wayland_session_deb.sh",
                             "build_wayland_desktop_deb.sh"):
                    shutil.copy2(ROOT / "scripts" / name, checkout / "scripts" / name)
                launcher = checkout / "launcher.py"
                launcher.write_bytes(b"raise RuntimeError('uncommitted')\n" + launcher.read_bytes())
                add = run("git", "-C", str(checkout), "add", "launcher.py")
                self.assertEqual(add.returncode, 0, add.stderr)
                desktop = checkout / "packaging/wayland/ricebowl.desktop"
                desktop.write_text(desktop.read_text() + "\n# uncommitted change\n")
                meta_control = checkout / "packaging/wayland/desktop-control"
                meta_control.write_text(meta_control.read_text() + "\n# uncommitted\n")
                core_control = checkout / "packaging/wayland/core-control"
                core_control.write_text(core_control.read_text() + "\n# uncommitted\n")
                (checkout / "macrice/injected_module.py").write_text("print('untracked')\n")

                packages = [("bash", "build_wayland_core_deb.sh", "core.deb"),
                            ("sh", "build_wayland_session_deb.sh", "session.deb"),
                            ("sh", "build_wayland_desktop_deb.sh", "desktop.deb")]
                for shell, script, filename in packages:
                    package = Path(temporary) / filename
                    result = run(shell, str(checkout / "scripts" / script), str(package))
                    self.assertEqual(result.returncode, 0, result.stderr)
                application = Path(temporary) / "application"
                session = Path(temporary) / "session"
                self.assertEqual(run("dpkg-deb", "-x", str(Path(temporary) / "core.deb"),
                                     str(application)).returncode, 0)
                self.assertEqual(run("dpkg-deb", "-x", str(Path(temporary) / "session.deb"),
                                     str(session)).returncode, 0)
                expected_launcher = subprocess.check_output(
                    ["git", "-C", str(ROOT), "show", "HEAD:launcher.py"], timeout=10)
                self.assertEqual((application / "usr/lib/ricebowl-wayland/launcher.py").read_bytes(),
                                 expected_launcher)
                self.assertFalse((application / "usr/lib/ricebowl-wayland/macrice/injected_module.py").exists())
                expected_desktop = subprocess.check_output(
                    ["git", "-C", str(ROOT), "show", "HEAD:packaging/wayland/ricebowl.desktop"],
                    timeout=10)
                self.assertEqual((session / "usr/share/wayland-sessions/ricebowl.desktop").read_bytes(),
                                 expected_desktop)
                self.assertEqual(run("dpkg-deb", "-f", str(Path(temporary) / "desktop.deb"),
                                     "Version").stdout.strip(), "0.1.0~preview3")
                self.assertNotIn("# uncommitted", run(
                    "dpkg-deb", "-f", str(Path(temporary) / "desktop.deb"),
                    "Description").stdout)
            finally:
                removed = run("git", "-C", str(ROOT), "worktree", "remove", "--force",
                              str(checkout))
                self.assertEqual(removed.returncode, 0, removed.stderr)

    @unittest.skipUnless(shutil.which("dpkg-deb") and shutil.which("dpkg"),
                         "Debian package tools needed")
    def test_read_only_package_set_gate_and_tampering(self):
        if run("dpkg", "--print-architecture").stdout.strip() != "amd64":
            self.skipTest("Native preview currently supports amd64 only")
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            core, session, native, desktop = (folder / name for name in
                                              ("core.deb", "session.deb", "native.deb", "desktop.deb"))
            for interpreter, script, target in (("bash", CORE, core),
                                                ("sh", ROOT / "scripts/build_wayland_session_deb.sh", session),
                                                ("sh", DESKTOP, desktop)):
                result = run(interpreter, str(script), str(target))
                self.assertEqual(result.returncode, 0, result.stderr)
            fixture = folder / "native-stage"
            (fixture / "DEBIAN").mkdir(parents=True)
            (fixture / "usr/bin").mkdir(parents=True)
            (fixture / "DEBIAN/control").write_text(
                "Package: ricebowl-riceplate-native\nVersion: 0.1.0~preview2\n"
                "Architecture: amd64\nMaintainer: RiceBowl QA\n"
                "Description: isolated package-set fixture\n")
            shutil.copy2("/bin/true", fixture / "usr/bin/riceplate-native")
            built = run("dpkg-deb", "--build", "--root-owner-group", str(fixture), str(native))
            self.assertEqual(built.returncode, 0, built.stderr)
            argv = ("bash", str(VERIFY), str(core), str(session), str(native), str(desktop))
            checked = run(*argv)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertIn("Verified four opt-in", checked.stdout)

            extracted = folder / "tamper-stage"
            self.assertEqual(run("dpkg-deb", "-R", str(core), str(extracted)).returncode, 0)
            buildinfo = extracted / "usr/lib/ricebowl-wayland/BUILDINFO"
            buildinfo.write_text(buildinfo.read_text().replace("source_commit=", "source_commit=tampered"))
            corrupted = folder / "tampered.deb"
            self.assertEqual(run("dpkg-deb", "--build", "--root-owner-group",
                                 str(extracted), str(corrupted)).returncode, 0)
            rejected = run("bash", str(VERIFY), str(corrupted), str(session),
                           str(native), str(desktop))
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("provenance", rejected.stderr)

            session_stage = folder / "unsafe-session-stage"
            self.assertEqual(run("dpkg-deb", "-R", str(session), str(session_stage)).returncode,
                             0)
            forbidden = session_stage / "etc/xdg/xfce4/xfconf/xfce-perchannel-xml"
            forbidden.mkdir(parents=True)
            (forbidden / "xfce4-panel.xml").write_text("<forbidden/>\n")
            unsafe = folder / "unsafe-session.deb"
            self.assertEqual(run("dpkg-deb", "--build", "--root-owner-group",
                                 str(session_stage), str(unsafe)).returncode, 0)
            rejected = run("bash", str(VERIFY), str(core), str(unsafe),
                           str(native), str(desktop))
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("Unexpected installed path", rejected.stderr)

            (session_stage / "DEBIAN/postinst").write_text("#!/bin/sh\nexit 0\n")
            (session_stage / "DEBIAN/postinst").chmod(0o755)
            with_script = folder / "maintainer-script.deb"
            self.assertEqual(run("dpkg-deb", "--build", "--root-owner-group",
                                 str(session_stage), str(with_script)).returncode, 0)
            rejected = run("bash", str(VERIFY), str(core), str(with_script),
                           str(native), str(desktop))
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("maintainer scripts", rejected.stderr)

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
            self.assertEqual(run("dpkg-deb", "-f", str(first), "Version").stdout.strip(),
                             "0.1.0~preview3")
            dependencies = run("dpkg-deb", "-f", str(first), "Depends").stdout
            for name in ("ricebowl-wayland-core", "ricebowl-wayland-session",
                         "ricebowl-riceplate-native"):
                self.assertIn(name, dependencies)
            self.assertIn("ricebowl-wayland-core (= 0.1.0~preview2)", dependencies)
            self.assertIn("ricebowl-riceplate-native (>= 0.1.0~preview2)", dependencies)
            archive = run("dpkg-deb", "--contents", str(first)).stdout
            self.assertNotIn("postinst", archive)
            self.assertNotIn("usr/bin/", archive)
            self.assertNotIn("wayland-sessions", archive)

    def test_existing_login_wrapper_keeps_legacy_fallback(self):
        contents = SESSION.read_text(encoding="utf-8")
        self.assertIn("app=/usr/bin/ricebowl-wayland-app", contents)
        self.assertIn('PATH="/usr/lib/ricebowl-wayland/bin:', contents)
        self.assertIn('app="$HOME/.local/bin/ricebowl"', contents)
        self.assertIn('exec "$app" de start --panel native', contents)
        self.assertIn('exec "$app" de start', contents)
        self.assertNotIn("xfce4-panel", contents)

    def test_installed_package_smoke_is_isolated_and_gated_in_ci(self):
        smoke = (ROOT / "scripts/smoke_wayland_packaged_login.sh").read_text()
        workflow = (ROOT / ".github/workflows/riceplate-native.yml").read_text()
        self.assertIn('"${RICEBOWL_PACKAGED_CI:-}" != 1', smoke)
        self.assertIn("[ ! -f /.dockerenv ]", smoke)
        self.assertIn("runuser -u ricebowl-smoke", smoke)
        self.assertIn("/usr/bin/ricebowl-wayland-session --native", smoke)
        self.assertIn("native_login_prerequisites_ready", smoke)
        self.assertIn("pgrep -u", smoke)
        self.assertIn("grim", smoke)
        self.assertIn("RICEBOWL_PACKAGED_CI=1 sh /tests/packaged-login.sh", workflow)


if __name__ == "__main__":
    unittest.main()
