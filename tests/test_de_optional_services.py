"""Recovery contracts for optional Wayland integrations.

These tests never start labwc or alter the system/user login session.
"""

from __future__ import annotations

import unittest
from unittest import mock

from macrice.de import session


class FakeProcess:
    def __init__(self, exit_code: int | None = None):
        self.exit_code = exit_code
        self.terminated = False

    def poll(self):
        return 0 if self.terminated else self.exit_code

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0 if self.terminated or self.exit_code is None else self.exit_code


class OptionalWaylandServiceTests(unittest.TestCase):
    def setUp(self):
        self.nested = {"RICEBOWL_DE_SHELL_CHILD": "1", "RICEBOWL_DE_NESTED": "1",
                       "WAYLAND_DISPLAY": "wayland-0"}
        self.tools = {tool: "/usr/bin/" + tool for tool in (
            "waybar", "swaybg", "mako", "lxpolkit", "mate-polkit",
            "riceplate-native", "swayidle", "swaylock")}

    def test_optional_spawn_failure_falls_through_to_next_polkit_agent(self):
        attempts = []

        def spawn(command, **kwargs):
            attempts.append(command[0])
            if command[0] in ("/usr/bin/swaybg", "/usr/bin/mako", "/usr/bin/lxpolkit"):
                raise OSError("executable failed after PATH lookup")
            return FakeProcess()

        env = {**self.nested, "RICEBOWL_DE_PANEL": "native"}
        with mock.patch("macrice.de.session.signal.signal"), mock.patch("sys.stderr"):
            result = session.shell(environment=env, which=self.tools.get, spawn=spawn)
        self.assertEqual(result, 0)
        self.assertIn("/usr/bin/mako", attempts)
        self.assertIn("/usr/bin/lxpolkit", attempts)
        self.assertIn("/usr/bin/mate-polkit", attempts)
        self.assertEqual(attempts[-1], "/usr/bin/riceplate-native")
        self.assertNotIn("/usr/bin/waybar", attempts)

    def test_one_crash_retry_and_no_restart_storm(self):
        attempts = []
        background = []

        def spawn(command, **kwargs):
            attempts.append(command)
            return FakeProcess(exit_code=17)

        with mock.patch("sys.stderr"):
            service = session._OptionalService(
                "RicePop", ["/usr/bin/mako"], env=self.nested, spawn=spawn,
                background=background)
            for _ in range(10):
                service.check()
        self.assertEqual(attempts, [["/usr/bin/mako"], ["/usr/bin/mako"]])
        self.assertEqual(len(background), 2)
        self.assertTrue(service.retried)

    def test_successful_optional_exit_is_not_respawned(self):
        attempts = []
        def spawn(command, **kwargs):
            attempts.append(command)
            return FakeProcess(exit_code=0)
        service = session._OptionalService(
            "agent", ["/usr/bin/lxpolkit"], env=self.nested, spawn=spawn,
            background=[])
        service.check()
        service.check()
        self.assertEqual(len(attempts), 1)

    def test_optional_retry_spawn_failure_preserves_shell(self):
        attempts = []

        def spawn(command, **kwargs):
            attempts.append(command[0])
            if command[0] == "/usr/bin/mako":
                if attempts.count("/usr/bin/mako") > 1:
                    raise OSError("temporary failure")
                return FakeProcess(exit_code=1)
            return FakeProcess()

        choices = {"waybar": "/usr/bin/waybar", "mako": "/usr/bin/mako"}
        with mock.patch("macrice.de.session.signal.signal"), mock.patch("sys.stderr"):
            self.assertEqual(session.shell(environment=self.nested,
                                           which=choices.get, spawn=spawn), 0)
        self.assertEqual(attempts.count("/usr/bin/mako"), 2)
        self.assertEqual(attempts.count("/usr/bin/waybar"), 1)

    def test_nonlive_session_retries_crashed_notifications(self):
        attempts = []
        restarted = FakeProcess()

        def spawn(command, **kwargs):
            attempts.append(command[0])
            if command[0] == "/usr/bin/mako":
                return FakeProcess(exit_code=9) if attempts.count("/usr/bin/mako") == 1 else restarted
            return FakeProcess()

        choices = {"waybar": "/usr/bin/waybar", "mako": "/usr/bin/mako"}
        with mock.patch("macrice.de.session.signal.signal"), mock.patch("sys.stderr"):
            self.assertEqual(session.shell(environment=self.nested,
                                           which=choices.get, spawn=spawn), 0)
        self.assertEqual(attempts.count("/usr/bin/mako"), 2)
        self.assertTrue(restarted.terminated)

    def test_lock_watcher_starts_before_optional_full_session_clients(self):
        attempts = []

        def spawn(command, **kwargs):
            attempts.append(command[0])
            return FakeProcess()

        env = {**self.nested, "RICEBOWL_DE_NESTED": "0"}
        choices = {"waybar": "/usr/bin/waybar", "mako": "/usr/bin/mako",
                   "swayidle": "/usr/bin/swayidle", "swaylock": "/usr/bin/swaylock"}
        with (mock.patch("macrice.de.session.signal.signal"),
              mock.patch("macrice.de.notification_prefs.load_optional", return_value=None),
              mock.patch("macrice.de.session._start_auto_monitor_trial", return_value=None)):
            self.assertEqual(session.shell(environment=env,
                                           which=choices.get, spawn=spawn), 0)
        self.assertEqual(attempts[0], "/usr/bin/swayidle")
        self.assertLess(attempts.index("/usr/bin/swayidle"),
                        attempts.index("/usr/bin/mako"))
        self.assertLess(attempts.index("/usr/bin/swayidle"),
                        attempts.index("/usr/bin/waybar"))

    def test_security_critical_idle_guard_failure_still_aborts_full_session(self):
        attempts = []

        def spawn(command, **kwargs):
            attempts.append(command[0])
            if command[0] == "/usr/bin/swayidle":
                raise OSError("swayidle cannot start")
            return FakeProcess()

        env = {**self.nested, "RICEBOWL_DE_NESTED": "0"}
        choices = {"waybar": "/usr/bin/waybar", "swayidle": "/usr/bin/swayidle",
                   "swaylock": "/usr/bin/swaylock"}
        with self.assertRaisesRegex(OSError, "swayidle cannot start"):
            session.shell(environment=env, which=choices.get, spawn=spawn)
        self.assertIn("/usr/bin/swayidle", attempts)
        self.assertNotIn("/usr/bin/waybar", attempts)


if __name__ == "__main__":
    unittest.main()
