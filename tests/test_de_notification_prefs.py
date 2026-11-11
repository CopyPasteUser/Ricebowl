"""RicePop font/banner choices are private, fail-closed and next-login only."""

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macrice.de import notification_prefs, notifications, session


class NotificationAppearanceTests(unittest.TestCase):
    def test_session_generates_only_a_disposable_full_login_mako_override(self):
        class FinishedProcess:
            def poll(self):
                return 0

            def wait(self, **_kwargs):
                return 0

            def terminate(self):
                pass

        with tempfile.TemporaryDirectory() as config, \
             tempfile.TemporaryDirectory() as runtime, \
             mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": config}):
            Path(runtime).chmod(0o700)
            notification_prefs.save({**notification_prefs.DEFAULTS,
                                     "font_family": "DejaVu Sans", "font_size": 14},
                                    expected=notification_prefs.DEFAULTS)
            captured = []

            def spawn(command, **kwargs):
                if command[0] == "/usr/bin/mako":
                    path = Path(command[2])
                    captured.append((path, path.read_text(), dict(kwargs["env"])))
                return FinishedProcess()

            env = {"XDG_RUNTIME_DIR": runtime, "RICEBOWL_DE_SHELL_CHILD": "1",
                   "WAYLAND_DISPLAY": "wayland-0", "RICEBOWL_DE_NESTED": "0"}
            choices = {"mako": "/usr/bin/mako", "waybar": "/usr/bin/waybar",
                       "swayidle": "/usr/bin/swayidle", "swaylock": "/usr/bin/swaylock"}
            with mock.patch.object(session.signal, "signal"), \
                    mock.patch.object(session, "_start_auto_monitor_trial", return_value=None):
                session.shell(environment=env, which=choices.get, spawn=spawn)
            self.assertEqual(len(captured), 1)
            path, content, child_env = captured[0]
            self.assertTrue(path.name == "mako.conf")
            self.assertTrue(path.parent.name.startswith("ricebowl-pop-"))
            self.assertIn("font=DejaVu Sans 14", content)
            self.assertEqual(child_env["RICEBOWL_DE_MAKO_CONFIG"], str(path))
            self.assertFalse(path.exists(), "The private config must die with the session")

            captured.clear()
            env["RICEBOWL_DE_NESTED"] = "1"
            with mock.patch.object(session.signal, "signal"):
                session.shell(environment=env, which=choices.get, spawn=spawn)
            self.assertEqual(len(captured), 1)
            self.assertEqual(captured[0][0], session.resources() / "mako.conf")
            self.assertNotIn("RICEBOWL_DE_MAKO_CONFIG", captured[0][2])

    def test_private_versioned_preferences_and_stale_write_guard(self):
        with tempfile.TemporaryDirectory() as config, \
                mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": config}):
            self.assertIsNone(notification_prefs.load_optional())
            base = notification_prefs.load()
            selected = {**base, "font_family": "DejaVu Sans", "font_size": 14,
                        "default_timeout": 7000, "max_visible": 3}
            self.assertEqual(notification_prefs.save(selected, expected=base), selected)
            path = Path(config) / "ricebowl" / "ricepop-appearance.json"
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(notification_prefs.load(), selected)
            with self.assertRaisesRegex(ValueError, "changed"):
                notification_prefs.save(base, expected=base)
            self.assertEqual(notification_prefs.save(base, expected=selected), base)

    def test_font_and_mako_settings_never_accept_injection_or_implicit_values(self):
        base = notification_prefs.DEFAULTS
        for bad in ("Sans\n[mode=default]", "Sans=0", "", "Sans/Other", "A" * 81):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                notification_prefs.validate({**base, "font_family": bad})
        for key, bad in (("font_size", 11), ("font_size", True),
                         ("default_timeout", -1), ("max_visible", 200)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                notification_prefs.validate({**base, key: bad})
        text = notification_prefs.render({**base, "font_family": "DejaVu Sans",
                                          "font_size": 16, "default_timeout": 4000,
                                          "max_visible": 2})
        self.assertIn("font=DejaVu Sans 16\n", text)
        self.assertIn("default-timeout=4000\n", text)
        self.assertIn("max-visible=2\n", text)
        self.assertIn("[mode=ricebowl-do-not-disturb]\ninvisible=1\n", text)

    def test_invalid_private_configuration_fails_closed_without_auto_overwrite(self):
        with tempfile.TemporaryDirectory() as config, \
                mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": config}):
            parent = Path(config) / "ricebowl"
            parent.mkdir(mode=0o700)
            saved = parent / "ricepop-appearance.json"
            saved.write_text('{"version":99,"font_family":"Sans"}')
            saved.chmod(0o600)
            with self.assertRaises(ValueError):
                notification_prefs.load_optional()
            saved.write_text('{"version":true,"font_family":"Sans",'
                             '"font_size":12,"default_timeout":0,"max_visible":5}')
            with self.assertRaises(ValueError):
                notification_prefs.load_optional()
            with self.assertRaises(ValueError):
                notification_prefs.save(notification_prefs.DEFAULTS,
                                        expected=notification_prefs.DEFAULTS)

    def test_owner_proof_accepts_only_a_private_session_mako_config(self):
        with tempfile.TemporaryDirectory() as runtime:
            root = Path(runtime)
            root.chmod(0o700)
            private = root / "ricebowl-pop-accepted"
            private.mkdir(mode=0o700)
            config = private / "mako.conf"
            config.write_text(notification_prefs.render(notification_prefs.DEFAULTS))
            config.chmod(0o600)
            with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": runtime,
                                            "RICEBOWL_DE_MAKO_CONFIG": str(config)}):
                self.assertEqual(notifications._expected_mako_config(os.fsencode(config)),
                                 os.fsencode(config))
                config.chmod(0o644)
                with self.assertRaises(ValueError):
                    notifications._expected_mako_config(os.fsencode(config))
                config.chmod(0o600)
                private.chmod(0o755)
                with self.assertRaises(ValueError):
                    notifications._expected_mako_config(os.fsencode(config))
                private.chmod(0o700)
            with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": runtime,
                                            "RICEBOWL_DE_MAKO_CONFIG": "/tmp/mako.conf"}):
                with self.assertRaises(ValueError):
                    notifications._expected_mako_config(os.fsencode(config))
            with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": runtime}, clear=True):
                self.assertEqual(notifications._expected_mako_config(os.fsencode(config)),
                                 os.fsencode(config))
            # Labwc applications need not inherit the shell supervisor's
            # environment variable: the guarded Mako /proc argv is sufficient.
            with mock.patch.dict(os.environ, {
                    "XDG_RUNTIME_DIR": runtime, "XDG_SESSION_DESKTOP": "ricebowl",
                    "WAYLAND_DISPLAY": "wayland-0", "RICEBOWL_DE_NESTED": "0"}, clear=True), \
                    mock.patch.object(notifications.shutil, "which",
                                      side_effect=lambda name: name), \
                    mock.patch.object(notifications.subprocess, "run", return_value=
                                      subprocess.CompletedProcess([], 0, b"PID=999\n", b"")), \
                    mock.patch("builtins.open", mock.mock_open(
                        read_data=b"/usr/bin/mako\0--config\0" + os.fsencode(config) + b"\0")):
                self.assertEqual(notifications._owned_mako(), ("makoctl", 999))


if __name__ == "__main__":
    unittest.main()
