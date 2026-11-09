"""Protect the installed portal selection and opt-in capture safety boundary."""

from __future__ import annotations

import configparser
import os
import subprocess
import unittest

from macrice.de.session import DESKTOP_NAME, project_root


class WaylandPortalTests(unittest.TestCase):
    def test_installed_desktop_selects_exact_portal_config(self):
        root = project_root()
        chosen = DESKTOP_NAME.split(":", 1)[0].lower()
        path = root / "packaging/wayland" / f"{chosen}-portals.conf"
        self.assertTrue(path.is_file())
        portal = configparser.ConfigParser(interpolation=None)
        self.assertEqual(portal.read(path), [str(path)])
        routes = portal["preferred"]
        self.assertEqual(routes["default"], "gtk")
        self.assertEqual(routes["org.freedesktop.impl.portal.ScreenCast"], "wlr")
        self.assertEqual(routes["org.freedesktop.impl.portal.Screenshot"], "wlr")
        self.assertNotIn("chooser_type", path.read_text(encoding="utf-8"))

    def test_capture_probe_refuses_regular_login(self):
        script = project_root() / "scripts/check_wayland_portals.py"
        result = subprocess.run(
            ["/usr/bin/python3", str(script)],
            env={key: value for key, value in os.environ.items()
                 if key not in ("WLR_BACKENDS", "RICEBOWL_DE_NESTED")},
            capture_output=True, text=True, timeout=5, check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing to request a capture outside disposable CI", result.stderr)

    def test_capture_selection_is_in_disposable_harness_only(self):
        root = project_root()
        harness = (root / "scripts/smoke_wayland_portals.sh").read_text(encoding="utf-8")
        self.assertIn("chooser_type=none", harness)
        self.assertIn("dbus-run-session", harness)
        self.assertIn("mktemp -d", harness)
        self.assertIn("dbus-update-activation-environment", harness)
        self.assertIn("/usr/libexec/xdg-desktop-portal-wlr", harness)
        self.assertNotIn("--systemd", harness)

    def test_create_session_uses_valid_glib_tuple_signature(self):
        client = (project_root() / "scripts/check_wayland_portals.py").read_text(
            encoding="utf-8")
        self.assertIn('request(CAST, "CreateSession", "(a{sv})"', client)

    def test_capture_requests_generate_unique_portal_handles(self):
        client = (project_root() / "scripts/check_wayland_portals.py").read_text(
            encoding="utf-8")
        self.assertIn('options["handle_token"] = GLib.Variant("s",', client)
        self.assertIn('"session_handle_token": GLib.Variant("s",', client)
        self.assertIn('secrets.token_hex(', client)


if __name__ == "__main__":
    unittest.main()
