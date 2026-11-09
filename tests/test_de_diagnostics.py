"""The Wayland restructuring must not disturb the working XFCE session."""

import io
import json
import unittest
from unittest.mock import patch

from macrice.cli import main
from macrice.de.diagnostics import inspect


class DesktopEnvironmentPreflightTests(unittest.TestCase):
    def test_available_tools_do_not_claim_complete_de(self):
        tools = {"labwc", "Xwayland", "dbus-run-session"}
        report = inspect(
            environment={"XDG_SESSION_TYPE": "wayland"},
            which=lambda name: f"/usr/bin/{name}" if name in tools else None,
        )
        self.assertTrue(report.compositor_available)
        self.assertFalse(report.nested_prerequisites_ready)
        self.assertFalse(report.login_prerequisites_ready)
        self.assertFalse(report.native_login_prerequisites_ready)
        self.assertFalse(report.standalone_de_ready)
        self.assertEqual(report.session_type, "wayland")
        self.assertEqual(report.checks[-1].status, "planned")
        self.assertEqual({c.key for c in report.checks},
                         {"labwc", "xwayland", "session-bus", "riceplate", "integration",
                          "waybar", "foot", "fuzzel", "swaylock", "swayidle"})

    def test_unknown_session_and_missing_tools_are_reported_truthfully(self):
        report = inspect(environment={"XDG_SESSION_TYPE": "custom", "DISPLAY": ":0"},
                         which=lambda _: None)
        self.assertEqual(report.session_type, "unknown")
        self.assertFalse(report.compositor_available)
        self.assertEqual(report.checks[0].status, "missing")
        self.assertEqual(report.checks[2].status, "optional")
        self.assertEqual(report.checks[3].status, "optional")

    def test_native_preview_is_detected_without_claiming_runtime_acceptance(self):
        tools = {"labwc", "dbus-run-session", "Xwayland", "riceplate-native"}
        report = inspect(environment={"XDG_SESSION_TYPE": "wayland"},
                         which=lambda name: f"/usr/bin/{name}" if name in tools else None)
        self.assertEqual(report.checks[3].status, "ok")
        self.assertIn("does not validate", report.checks[3].detail)
        self.assertFalse(report.standalone_de_ready)
        self.assertEqual(report.checks[-1].status, "planned")

    def test_nested_and_login_require_exact_session_dependencies(self):
        base = {"labwc", "waybar", "foot", "fuzzel", "swaylock", "dbus-run-session"}

        def report_with(tools):
            return inspect(environment={"XDG_SESSION_TYPE": "x11"},
                           which=lambda name: f"/usr/bin/{name}" if name in tools else None)

        nested = report_with(base)
        self.assertTrue(nested.nested_prerequisites_ready)
        self.assertFalse(nested.login_prerequisites_ready)
        self.assertFalse(nested.native_login_prerequisites_ready)
        self.assertEqual(next(c for c in nested.checks if c.key == "swayidle").status,
                         "missing")

        login = report_with(base | {"swayidle"})
        self.assertTrue(login.login_prerequisites_ready)
        self.assertFalse(login.native_login_prerequisites_ready)
        self.assertFalse(login.standalone_de_ready)

        native = report_with(base | {"swayidle", "riceplate-native"})
        self.assertTrue(native.native_login_prerequisites_ready)
        self.assertFalse(native.standalone_de_ready)

        for required in ("labwc", "waybar", "foot", "fuzzel", "swaylock"):
            with self.subTest(missing=required):
                self.assertFalse(report_with((base | {"swayidle"}) - {required})
                                 .login_prerequisites_ready)

    def test_session_bus_is_required_even_with_all_binaries(self):
        tools = {"labwc", "waybar", "foot", "fuzzel", "swaylock", "swayidle",
                 "riceplate-native"}
        report = inspect(environment={},
                         which=lambda name: f"/usr/bin/{name}" if name in tools else None)
        self.assertFalse(report.nested_prerequisites_ready)
        self.assertFalse(report.login_prerequisites_ready)
        self.assertFalse(report.native_login_prerequisites_ready)

    def test_cli_exit_code_reflects_full_login_dependencies(self):
        base = {"labwc", "waybar", "foot", "fuzzel", "swaylock", "dbus-run-session"}
        for tools, expected in ((base, 1), (base | {"swayidle"}, 0)):
            with self.subTest(expected=expected):
                report = inspect(environment={},
                                 which=lambda name: f"/usr/bin/{name}" if name in tools else None)
                output = io.StringIO()
                with patch("macrice.de.diagnostics.inspect", return_value=report), \
                     patch("sys.stdout", output):
                    self.assertEqual(main(["de", "check"]), expected)
                self.assertIn("Wayland login prerequisites:", output.getvalue())
                self.assertIn("hardware acceptance: not verified", output.getvalue())

    def test_does_not_expose_network_or_private_environment(self):
        private = "wifi-name-or-secret"
        report = inspect(
            environment={"XDG_SESSION_TYPE": "wayland", "SSID": private,
                         "DBUS_SESSION_BUS_ADDRESS": private},
            which=lambda _: None,
        )
        self.assertNotIn(private, json.dumps(report.as_dict()))
        self.assertEqual(report.checks[1].status, "ok")

    def test_cli_json_read_only_and_exit_status(self):
        output = io.StringIO()
        with patch("macrice.de.diagnostics.inspect", return_value=inspect(
            environment={"XDG_SESSION_TYPE": "x11"}, which=lambda _: None,
        )), patch("sys.stdout", output):
            self.assertEqual(main(["de", "check", "--json"]), 1)
        parsed = json.loads(output.getvalue())
        self.assertEqual(parsed["session_type"], "x11")
        self.assertFalse(parsed["standalone_de_ready"])
        self.assertEqual(parsed["checks"][0]["key"], "labwc")


if __name__ == "__main__":
    unittest.main()
