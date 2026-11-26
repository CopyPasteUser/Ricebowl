"""SG7 WP7.3: tests for entries of docs/sg7-unsupported-error-states.md that were `unverified`."""
import io
import unittest
from contextlib import redirect_stderr
from unittest import mock

from macrice.cli import main as cli
from macrice.de import lock, notifications, recipes, settings


class LockActionProviderAbsentTests(unittest.TestCase):
    """The panel/menu `lock` action runs `ricebowl de lock`; absent providers fail loudly."""

    def test_missing_locker_makes_the_helper_exit_nonzero_with_the_reason(self):
        # RicePlate reports any non-zero helper exit as "Command: Could not run".
        with mock.patch.object(lock, "lock_screen", side_effect=lock.ScreenLockError(
                "swaylock is unavailable; screen not locked")), \
                redirect_stderr(io.StringIO()) as err:
            code = cli(["de", "lock"])
        self.assertNotEqual(code, 0)
        self.assertIn("swaylock is unavailable; screen not locked", err.getvalue())

    def test_real_missing_swaylock_and_nested_preview_never_claim_a_lock(self):
        env = {"RICEBOWL_DE_NESTED": "0", "RICEBOWL_DE_SHELL_CHILD": "1",
               "WAYLAND_DISPLAY": "wayland-test"}
        with self.assertRaisesRegex(lock.ScreenLockError, "swaylock is unavailable"):
            lock.lock_screen(environment=env, which=lambda _name: None)
        with self.assertRaisesRegex(lock.ScreenLockError, "full RiceBowl Wayland session"):
            lock.lock_screen(environment={**env, "RICEBOWL_DE_NESTED": "1"},
                             which=lambda name: "/usr/bin/" + name)


class ChromeRiceHasNoNativeNotificationsEntryTests(unittest.TestCase):
    def test_bundled_chrome_recipe_has_no_menu_or_panel_notifications_entry(self):
        recipe = recipes.load("chrome")
        self.assertIsNone(recipe.menu)
        tokens = [token for section in recipe.sections for token in section]
        self.assertNotIn("notifications", tokens)
        self.assertTrue(tokens, "the Chrome panel itself is populated")

    def test_notifications_remain_reachable_through_ricespice(self):
        self.assertIn("notifications", [key for key, _title, _desc in settings.SECTIONS])


class MakoVersionHasNoInAppNoticeTests(unittest.TestCase):
    """Mako < 1.11 never emits ActionInvoked for `makoctl invoke`; RiceBowl does not detect
    the version, so a zero exit status is the only success signal it has."""

    def test_no_version_probe_exists_and_invoke_success_is_the_makoctl_exit_status(self):
        self.assertFalse(any("version" in name.lower() for name in dir(notifications)
                             if name.lower().startswith(("mako", "_mako"))))
        active = [{"id": 7, "actions": [{"key": "default", "label": "Open"}]}]
        calls = []

        def run(argv, **_kwargs):
            calls.append(argv)
            return mock.Mock(returncode=0, stdout=b"", stderr=b"")

        with mock.patch.object(notifications, "_mutation_host",
                               return_value=("/usr/bin/makoctl", 11)), \
                mock.patch.object(notifications, "_verify_snapshot_owner"), \
                mock.patch.object(notifications, "_fresh_active", return_value=active), \
                mock.patch.object(notifications, "_verify_snapshot_target"), \
                mock.patch.object(notifications.subprocess, "run", side_effect=run):
            result = notifications.invoke(7, "default", expected_owner_pid=11)
        self.assertTrue(result["invoked"])
        self.assertEqual(calls, [["/usr/bin/makoctl", "invoke", "-n", "7", "--", "default"]],
                         "no `--version` or other probe is run")


if __name__ == "__main__":
    unittest.main()
