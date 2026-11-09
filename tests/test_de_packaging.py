"""The optional login package must be self-contained and reversible."""

import configparser
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from macrice.de.session import project_root


class SessionPackageTests(unittest.TestCase):
    def test_desktop_entry_and_portal_routing(self):
        source = project_root() / "packaging/wayland"
        desktop = configparser.ConfigParser(interpolation=None)
        desktop.read(source / "ricebowl.desktop")
        self.assertEqual(desktop["Desktop Entry"]["Type"], "Application")
        self.assertEqual(desktop["Desktop Entry"]["Exec"], "/usr/bin/ricebowl-wayland-session")
        self.assertIn("RiceBowl;", desktop["Desktop Entry"]["DesktopNames"])
        native = configparser.ConfigParser(interpolation=None)
        self.assertEqual(native.read(source / "ricebowl-native.desktop"),
                         [str(source / "ricebowl-native.desktop")])
        self.assertEqual(native["Desktop Entry"]["Type"], "Application")
        self.assertEqual(native["Desktop Entry"]["Exec"],
                         "/usr/bin/ricebowl-wayland-session --native")
        self.assertEqual(native["Desktop Entry"]["TryExec"], "/usr/bin/riceplate-native")
        self.assertEqual(native["Desktop Entry"]["DesktopNames"],
                         desktop["Desktop Entry"]["DesktopNames"])
        portal = configparser.ConfigParser(interpolation=None)
        portal.read(source / "ricebowl-portals.conf")
        self.assertEqual(portal["preferred"]["org.freedesktop.impl.portal.ScreenCast"], "wlr")
        self.assertEqual(portal["preferred"]["default"], "gtk")

    def test_session_launcher_routes_only_explicit_native_choice(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            executable = home / ".local/bin/ricebowl"
            executable.parent.mkdir(parents=True)
            binary = root / "bin"
            binary.mkdir()
            marker = root / "args"
            executable.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$@" > "$RICEBOWL_ARGS_FILE"\n',
                encoding="utf-8")
            executable.chmod(0o700)
            script = project_root() / "packaging/wayland/ricebowl-wayland-session"
            env = {**os.environ, "HOME": str(home), "PATH": str(binary),
                   "RICEBOWL_ARGS_FILE": str(marker)}

            def invoke(*arguments):
                return subprocess.run(["/bin/sh", str(script), *arguments],
                                      capture_output=True, text=True, env=env,
                                      timeout=5, check=False)

            default = invoke()
            self.assertEqual(default.returncode, 0, default.stderr)
            self.assertEqual(marker.read_text().splitlines(), ["de", "start"])
            marker.unlink()
            no_binary = invoke("--native")
            self.assertNotEqual(no_binary.returncode, 0)
            self.assertIn("riceplate-native", no_binary.stderr)
            self.assertFalse(marker.exists())
            for arguments in (("--unexpected",), ("--native", "--unexpected")):
                result = invoke(*arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(marker.exists())
            native_binary = binary / "riceplate-native"
            native_binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            native_binary.chmod(0o700)
            native = invoke("--native")
            self.assertEqual(native.returncode, 0, native.stderr)
            self.assertEqual(marker.read_text().splitlines(),
                             ["de", "start", "--panel", "native"])

    @unittest.skipUnless(shutil.which("dpkg-deb"), "Debian package tools not installed")
    def test_package_build_does_not_install_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / "session.deb"
            script = project_root() / "scripts/build_wayland_session_deb.sh"
            result = subprocess.run(["sh", str(script), str(package)], text=True,
                                    capture_output=True, timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            contents = subprocess.check_output(
                ["dpkg-deb", "--contents", str(package)], text=True, timeout=10)
            for name in ("usr/bin/ricebowl-wayland-session",
                         "usr/share/wayland-sessions/ricebowl.desktop",
                         "usr/share/wayland-sessions/ricebowl-native.desktop",
                         "usr/share/xdg-desktop-portal/ricebowl-portals.conf",
                         "usr/lib/systemd/user/ricebowl-session.target"):
                self.assertIn(name, contents)
            self.assertEqual(subprocess.check_output(
                ["dpkg-deb", "--field", str(package), "Version"],
                text=True, timeout=10).strip(), "0.1.0~preview3")
            result = subprocess.run(["sh", str(script), str(package)], text=True,
                                    capture_output=True, timeout=30, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing to overwrite", result.stderr)

    @unittest.skipUnless(all(shutil.which(command) for command in
                             ("dpkg-deb", "dpkg-shlibdeps", "dpkg-query", "readelf")),
                         "Native Debian packaging tools not installed")
    def test_native_preview_package_preserves_binary_and_is_reproducible(self):
        # The cloud development sandbox has no dpkg package database; unlike
        # normal Ubuntu CI, its glibc has no shlibs metadata to derive deps.
        if subprocess.run(["dpkg-query", "-W", "libc6"], capture_output=True,
                          check=False).returncode:
            self.skipTest("Host libc is not registered in the Debian package database")
        with tempfile.TemporaryDirectory() as temp:
            source = Path("/bin/true")
            first, second = Path(temp) / "first.deb", Path(temp) / "second.deb"
            script = project_root() / "scripts/build_riceplate_native_deb.sh"
            for output in (first, second):
                result = subprocess.run(["sh", str(script), str(source), str(output)],
                                        capture_output=True, text=True, check=False,
                                        timeout=30, env={**os.environ,
                                                         "SOURCE_DATE_EPOCH": "1704067200"})
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(subprocess.check_output(
                ["dpkg-deb", "--field", str(first), "Architecture"], text=True).strip(),
                "amd64")
            dependencies = subprocess.check_output(
                ["dpkg-deb", "--field", str(first), "Depends"], text=True)
            self.assertIn("libc6", dependencies)
            with tempfile.TemporaryDirectory() as extracted:
                subprocess.run(["dpkg-deb", "--extract", str(first), extracted],
                               check=True, timeout=10)
                self.assertEqual((Path(extracted) / "usr/bin/riceplate-native").read_bytes(),
                                 source.read_bytes())
            result = subprocess.run(["sh", str(script), str(source), str(first)],
                                    capture_output=True, text=True, check=False, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing to overwrite", result.stderr)

    def test_native_package_rejects_non_elf_and_relative_target(self):
        with tempfile.TemporaryDirectory() as temp:
            invalid = Path(temp) / "not-binary"
            invalid.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            invalid.chmod(0o755)
            script = project_root() / "scripts/build_riceplate_native_deb.sh"
            result = subprocess.run(["sh", str(script), str(invalid),
                                     str(Path(temp) / "invalid.deb")],
                                    capture_output=True, text=True, check=False, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("x86-64 ELF", result.stderr)
            relative = subprocess.run(["sh", str(script), "/bin/true", "preview.deb"],
                                      capture_output=True, text=True, check=False, timeout=10)
            self.assertNotEqual(relative.returncode, 0)
            self.assertIn("absolute .deb", relative.stderr)


if __name__ == "__main__":
    unittest.main()
