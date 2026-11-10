"""Physical Wayland acceptance is explicitly not a headless CI success flag."""

import io
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from macrice.cli import main
from macrice.de.acceptance import MANUAL_CHECKS, _socket_state, inspect
from macrice.de.session import DESKTOP_NAME


REQUIRED = {"labwc", "riceplate-native", "swaylock", "swayidle", "wlr-randr"}


def executable(name):
    return f"/usr/bin/{name}" if name in REQUIRED else None


def outputs(*args, **kwargs):
    return subprocess.CompletedProcess(args[0], 0, stdout=json.dumps([
        {"name": "redacted-display", "enabled": True, "scale": 1},
        {"name": "private-monitor-name", "enabled": True, "scale": 1.25},
        {"name": "disconnected", "enabled": False, "scale": 1},
    ]), stderr="")


class WaylandPhysicalAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = {"XDG_SESSION_TYPE": "wayland",
                    "XDG_CURRENT_DESKTOP": DESKTOP_NAME,
                    "RICEBOWL_DE_SHELL_CHILD": "1",
                    "RICEBOWL_DE_NESTED": "0",
                    "RICEBOWL_DE_PANEL": "native",
                    "XDG_RUNTIME_DIR": self.temp.name,
                    "WAYLAND_DISPLAY": "wayland-0",
                    "DBUS_SESSION_BUS_ADDRESS": "private-user-value",
                    "SSID": "private-network-value"}

    def test_real_native_session_gets_read_only_display_inventory_not_hardware_approval(self):
        calls = []

        def runner(*args, **kwargs):
            calls.append((args, kwargs))
            return outputs(*args, **kwargs)

        report = inspect(environment=self.env, which=executable,
                         socket_probe=lambda _: "present", run=runner)
        self.assertTrue(report.ready_for_manual_checks)
        self.assertEqual(report.active_outputs, 2)
        self.assertTrue(report.fractional_scale_present)
        self.assertEqual(report.output_probe, "observed")
        self.assertFalse(report.as_dict()["hardware_accepted"])
        self.assertIn("pending manual test", report.next_step)
        self.assertTrue(all(item.status == "pending" for item in report.manual_checks))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], (["/usr/bin/wlr-randr", "--json"],))
        self.assertTrue(calls[0][1]["capture_output"])
        self.assertTrue(calls[0][1]["check"])
        self.assertLessEqual(calls[0][1]["timeout"], 3)
        public = json.dumps(report.as_dict())
        for secret in ("private-user-value", "private-network-value", self.temp.name,
                       "redacted-display", "private-monitor-name"):
            self.assertNotIn(secret, public)
        self.assertGreaterEqual(len(MANUAL_CHECKS), 8)

    def test_xfce_nested_and_unmarked_sessions_are_not_physical_acceptance(self):
        for override in ({"XDG_SESSION_TYPE": "x11"},
                         {"RICEBOWL_DE_NESTED": "1"},
                         {"RICEBOWL_DE_PANEL": "waybar"},
                         {"RICEBOWL_DE_SHELL_CHILD": "0"},
                         {"XDG_CURRENT_DESKTOP": "XFCE"}):
            with self.subTest(override=override):
                env = self.env | override
                with patch("subprocess.run", side_effect=AssertionError("should not probe")):
                    report = inspect(environment=env, which=executable,
                                     socket_probe=lambda _: "present")
                self.assertFalse(report.ready_for_manual_checks)
                self.assertEqual(report.output_probe, "not-run")
                self.assertFalse(report.as_dict()["hardware_accepted"])
                self.assertIn("opt-in native", report.next_step)

    def test_broken_or_symlinked_socket_and_missing_binaries_fail_closed(self):
        with patch("subprocess.run", side_effect=AssertionError("should not probe")):
            self.assertEqual(_socket_state(self.env | {"WAYLAND_DISPLAY": "absent"}), "missing")
            file = Path(self.temp.name) / "regular-file"
            file.write_text("not a socket")
            self.assertEqual(_socket_state(self.env | {"WAYLAND_DISPLAY": file.name}), "invalid")
            link = Path(self.temp.name) / "linked-socket"
            link.symlink_to(file.name)
            self.assertEqual(_socket_state(self.env | {"WAYLAND_DISPLAY": link.name}), "invalid")
            self.assertFalse(inspect(environment=self.env,
                                     which=lambda name: None).ready_for_manual_checks)

    def test_owned_socket_metadata_without_opening_a_forbidden_test_socket(self):
        original_lstat = Path.lstat

        def owned_socket(path):
            if Path(path).name == "wayland-0":
                return SimpleNamespace(st_mode=stat.S_IFSOCK | 0o600,
                                       st_uid=os.getuid())
            return original_lstat(path)

        with patch.object(Path, "lstat", owned_socket):
            self.assertEqual(_socket_state(self.env), "present")
        def foreign_socket(path):
            if Path(path).name == "wayland-0":
                return SimpleNamespace(st_mode=stat.S_IFSOCK | 0o600,
                                       st_uid=os.getuid() + 1)
            return original_lstat(path)

        with patch.object(Path, "lstat", foreign_socket):
            self.assertEqual(_socket_state(self.env), "invalid")

    def test_invalid_or_unresponsive_output_reports_are_not_readiness(self):
        invalid = ["not json", "{}", "[]" ,
                   json.dumps([{"enabled": True, "scale": "secret"}]),
                   json.dumps([{"enabled": True, "scale": 0}]),
                   json.dumps([{"enabled": True, "scale": 1}] * 33),
                   json.dumps([{"enabled": True, "scale": 1}, "invalid"])]
        for value in invalid:
            with self.subTest(value=value[:40]):
                report = inspect(environment=self.env, which=executable,
                                 socket_probe=lambda _: "present",
                                 run=lambda *a, **kw: subprocess.CompletedProcess(a, 0, value, ""))
                self.assertFalse(report.ready_for_manual_checks)
        timed_out = inspect(environment=self.env, which=executable,
                            socket_probe=lambda _: "present",
                            run=lambda *a, **kw: (_ for _ in ()).throw(
                                subprocess.TimeoutExpired("wlr-randr", 3)))
        self.assertEqual(timed_out.output_probe, "unavailable")
        self.assertFalse(timed_out.ready_for_manual_checks)

    def test_cli_has_honest_status_and_rejects_mutating_options(self):
        report = inspect(environment=self.env, which=executable,
                         socket_probe=lambda _: "present", run=outputs)
        out = io.StringIO()
        with patch("macrice.de.acceptance.inspect", return_value=report), patch("sys.stdout", out):
            self.assertEqual(main(["de", "acceptance", "--json"]), 0)
        public = json.loads(out.getvalue())
        self.assertTrue(public["ready_for_manual_checks"])
        self.assertFalse(public["hardware_accepted"])
        self.assertEqual(public["outputs"]["active_count"], 2)
        for check in public["manual_checks"]:
            self.assertEqual(check["status"], "pending")
        out = io.StringIO()
        with patch("macrice.de.acceptance.inspect", return_value=report), patch("sys.stdout", out):
            self.assertEqual(main(["de", "acceptance"]), 0)
        self.assertIn("Hardware accepted: NO", out.getvalue())
        unready = inspect(environment=self.env | {"XDG_SESSION_TYPE": "x11"},
                          which=executable)
        with patch("macrice.de.acceptance.inspect", return_value=unready), patch("sys.stdout", io.StringIO()):
            self.assertEqual(main(["de", "acceptance", "--json"]), 1)
        with patch("sys.stderr", io.StringIO()) as errors:
            self.assertEqual(main(["de", "acceptance", "--nested"]), 1)
            self.assertIn("accepts only --json", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
