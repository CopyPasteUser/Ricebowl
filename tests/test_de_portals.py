"""Pure portal probe contract checks; no compositor or D-Bus required."""
import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_wayland_portals.py"
spec = importlib.util.spec_from_file_location("ricebowl_portal_probe", SCRIPT)
portal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(portal)


def xml(*names):
    return "<node>" + "".join('<interface name="' + name + '"/>' for name in names) + "</node>"


class PortalProbeTests(unittest.TestCase):
    def test_extracts_dbus_interfaces_only(self):
        self.assertEqual(portal.parse_interfaces(xml("org.test.One", "org.test.Two")),
                         {"org.test.One", "org.test.Two"})
        with self.assertRaises(ValueError):
            portal.parse_interfaces("<not-node/>")

    def test_accepts_actual_required_interfaces(self):
        payload = xml(*sorted(portal.REQUIRED), "org.freedesktop.DBus.Introspectable")
        result = subprocess.CompletedProcess([], 0, stdout=payload, stderr="")
        with patch.object(portal.subprocess, "run", return_value=result) as run:
            self.assertEqual(portal.check(4), portal.REQUIRED | {
                "org.freedesktop.DBus.Introspectable"})
            self.assertEqual(run.call_args.kwargs["timeout"], 4)
            self.assertIn("--session", run.call_args.args[0])
            self.assertIn("--xml", run.call_args.args[0])

    def test_missing_screencast_fails_closed(self):
        result = subprocess.CompletedProcess([], 0,
            stdout=xml("org.freedesktop.portal.FileChooser",
                       "org.freedesktop.portal.Screenshot"), stderr="")
        with patch.object(portal.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "ScreenCast"):
                portal.check()

    def test_activation_failure_does_not_claim_success(self):
        result = subprocess.CompletedProcess([], 1, stdout="",
                                             stderr="No portal available")
        with patch.object(portal.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "No portal available"):
                portal.check()


if __name__ == "__main__":
    unittest.main()
