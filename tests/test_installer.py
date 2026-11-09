import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macrice.installer import (
    InstallOptions, InstallationError, _check_existing, _check_entrypoints,
    _install_manager, _write_entrypoints, install, plan, project_root,
)


class InstallerTests(unittest.TestCase):
    def test_plan_preserves_xfce_panel_by_default(self):
        commands = dict(plan(project_root(), InstallOptions()))
        self.assertIn("--start-hidden", commands["Control Center"])
        self.assertNotIn("--autostart", commands["MacBar"])
        self.assertNotIn("--replace-xfce", " ".join(map(str, commands.values())))
        self.assertIn("--no-start", dict(plan(project_root(), InstallOptions(no_start=True)))["Control Center"])
        self.assertIn("--autostart", dict(plan(project_root(), InstallOptions(bar_autostart=True)))["MacBar"])

    def test_unmanaged_existing_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "macrice"
            path.mkdir()
            (path / "user-file.txt").write_text("preserve me")
            with self.assertRaises(InstallationError):
                _check_existing(path)
            self.assertEqual((path / "user-file.txt").read_text(), "preserve me")

    def test_dry_run_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            with mock.patch.dict(os.environ, {
                "XDG_DATA_HOME": str(base / "data"),
                "XDG_BIN_HOME": str(base / "bin"),
                "XDG_CONFIG_HOME": str(base / "config"),
            }), mock.patch("macrice.installer._check_system_package"):
                lines = []
                self.assertIsNone(install(InstallOptions(dry_run=True), output=lines.append))
                self.assertTrue(any("Plank" in line for line in lines))
                self.assertFalse((base / "data").exists())
                self.assertFalse((base / "config").exists())

    def test_wrapper_and_desktop_entry_are_user_local(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            installed = base / "data" / "macrice"
            installed.mkdir(parents=True)
            (installed / "launcher.py").write_text("# test")
            with mock.patch.dict(os.environ, {
                "XDG_DATA_HOME": str(base / "data"), "XDG_BIN_HOME": str(base / "bin"),
            }):
                _write_entrypoints(installed)
                wrapper = base / "bin" / "macrice"
                self.assertIn(str(installed / "launcher.py"), wrapper.read_text())
                self.assertTrue(os.access(wrapper, os.X_OK))
                entry = (base / "data/applications/macrice.desktop").read_text()
                self.assertIn("Name=MacRice Settings", entry)
                self.assertNotIn("sudo", entry)
                hub = base / "bin" / "ricehub"
                self.assertTrue(os.access(hub, os.X_OK))
                self.assertIn('" hub "$@"', hub.read_text())
                toggle = base / "bin" / "ricehub-toggle"
                self.assertTrue(os.access(toggle, os.X_OK))
                self.assertIn("gapplication action", toggle.read_text())
                self.assertIn("aero-menu", toggle.read_text())
                hub_entry = (base / "data/applications/ricehub.desktop").read_text()
                self.assertIn("Name=RiceBowl (legacy launcher)", hub_entry)
                self.assertIn("assets/ricebowl-symbolic.svg", hub_entry)
                self.assertNotIn("sudo", hub_entry)
                self.assertIn("Rice Creator", (base / "data/applications/ricebowl-creator.desktop").read_text())
                self.assertIn("creator)", (base / "bin/ricebowl").read_text())
                self.assertIn("riceclip|riceshot)", (base / "bin/ricebowl").read_text())
                self.assertIn("riceclip open", (base / "data/applications/riceclip.desktop").read_text())
                self.assertIn("riceshot --mode region", (base / "data/applications/riceshot.desktop").read_text())

    def test_installed_ricehub_entrypoint_loads_bundled_application(self):
        """The installed launcher must work, not just `python -m macrice`."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            environment = {
                **os.environ,
                "XDG_DATA_HOME": str(base / "data"),
                "XDG_BIN_HOME": str(base / "bin"),
                "XDG_CONFIG_HOME": str(base / "config"),
            }
            with mock.patch.dict(os.environ, environment):
                installed = _install_manager(project_root())
                _write_entrypoints(installed)
            self.assertTrue((installed / "examples/wayland/heritage-modern-v10.json").is_file())

            result = subprocess.run(
                [str(base / "bin/ricehub"), "--help"],
                env=environment,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("hub", result.stdout)
            self.assertTrue((installed / "macrice/hub_catalog.py").is_file())
            self.assertTrue((installed / "macrice/rice_windows.py").is_file())
            self.assertTrue((installed / "RICE_WINDOWS_ROADMAP.md").is_file())
            self.assertTrue((installed / "RICEPLATE_DESKTOP_ROADMAP.md").is_file())
            self.assertTrue((installed / "XFCE_RESOURCE_BOUNDARIES.md").is_file())
            self.assertTrue((installed / "RICEBOWL_DE_ROADMAP.md").is_file())
            self.assertTrue((installed / "WAYLAND_SESSION.md").is_file())
            self.assertTrue((installed / "macrice/de/diagnostics.py").is_file())
            self.assertTrue((installed / "macrice/de/session.py").is_file())
            self.assertTrue((installed / "macrice/de/resources/labwc/rc.xml").is_file())
            self.assertTrue((installed / "RICEPACK_SPEC.md").is_file())
            self.assertTrue((installed / "macrice/riceware/packs.py").is_file())

            updater_help = subprocess.run(
                [str(base / "bin/ricebowl"), "update", "--help"],
                env=environment, capture_output=True, text=True, timeout=15, check=False,
            )
            self.assertEqual(updater_help.returncode, 0, updater_help.stderr)
            self.assertIn("--preserve-checkout", updater_help.stdout)
            self.assertIn("check --refresh --preserve-checkout",
                          (base / "bin/ricebowl").read_text())
            de_help = subprocess.run(
                [str(base / "bin/ricebowl"), "de", "--help"],
                env=environment, capture_output=True, text=True, timeout=15, check=False,
            )
            self.assertEqual(de_help.returncode, 0, de_help.stderr)
            self.assertIn("--json", de_help.stdout)
            for utility in ("riceclip", "riceshot"):
                with self.subTest(utility=utility):
                    help_result = subprocess.run(
                        [str(base / "bin/ricebowl"), utility, "--help"],
                        env=environment, capture_output=True, text=True,
                        timeout=15, check=False,
                    )
                    self.assertEqual(help_result.returncode, 0, help_result.stderr)
                    self.assertIn(utility, help_result.stdout)

    def test_fast_toggle_prefers_dbus_and_falls_back_for_cold_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installed = root / "data/macrice"
            installed.mkdir(parents=True)
            (installed / "launcher.py").write_text("import sys\nprint(' '.join(sys.argv[1:]))\n")
            env = {**os.environ, "XDG_DATA_HOME": str(root / "data"),
                   "XDG_BIN_HOME": str(root / "bin")}
            stub = root / "stub"
            stub.mkdir()
            dbus = stub / "gapplication"
            with mock.patch.dict(os.environ, env):
                _write_entrypoints(installed)
            env["PATH"] = str(stub) + ":/usr/bin:/bin"
            dbus.write_text("#!/bin/sh\nexit 0\n")
            dbus.chmod(0o755)
            command = [str(root / "bin/ricehub-toggle"), "aero-control"]
            fast = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
            self.assertEqual(fast.returncode, 0)
            self.assertEqual(fast.stdout, "")  # Resident action: no Python fallback.
            dbus.write_text("#!/bin/sh\nexit 1\n")
            cold = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
            self.assertEqual(cold.returncode, 0, cold.stderr)
            self.assertEqual(cold.stdout.strip(), "aero-shell --control")

    def test_unmanaged_launcher_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            binary = base / "bin/macrice"
            binary.parent.mkdir()
            binary.write_text("#!/bin/sh\necho user's program\n")
            with mock.patch.dict(os.environ, {
                "XDG_DATA_HOME": str(base / "data"), "XDG_BIN_HOME": str(base / "bin"),
            }):
                with self.assertRaises(InstallationError):
                    _check_entrypoints()
                self.assertEqual(binary.read_text(), "#!/bin/sh\necho user's program\n")

    def test_unmanaged_desktop_entry_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            desktop = base / "data/applications/macrice.desktop"
            desktop.parent.mkdir(parents=True)
            desktop.write_text("[Desktop Entry]\nName=User App\n")
            with mock.patch.dict(os.environ, {
                "XDG_DATA_HOME": str(base / "data"), "XDG_BIN_HOME": str(base / "bin"),
            }):
                with self.assertRaises(InstallationError):
                    _check_entrypoints()
                self.assertEqual(desktop.read_text(), "[Desktop Entry]\nName=User App\n")

    def test_unmanaged_ricehub_launcher_blocks_overwriting_any_entrypoint(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            binary = base / "bin/ricehub"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\necho my original app\n")
            with mock.patch.dict(os.environ, {
                "XDG_DATA_HOME": str(base / "data"), "XDG_BIN_HOME": str(base / "bin"),
            }):
                with self.assertRaises(InstallationError):
                    _write_entrypoints(base / "data/macrice")
                self.assertEqual(binary.read_text(), "#!/bin/sh\necho my original app\n")
                self.assertFalse((base / "bin/macrice").exists())

    def test_unmanaged_ricehub_desktop_file_blocks_install(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            desktop = base / "data/applications/ricehub.desktop"
            desktop.parent.mkdir(parents=True)
            desktop.write_text("[Desktop Entry]\nName=Unrelated user project\n")
            with mock.patch.dict(os.environ, {
                "XDG_DATA_HOME": str(base / "data"), "XDG_BIN_HOME": str(base / "bin"),
            }):
                with self.assertRaises(InstallationError):
                    _check_entrypoints()
                self.assertEqual(desktop.read_text(), "[Desktop Entry]\nName=Unrelated user project\n")


if __name__ == "__main__":
    unittest.main()
