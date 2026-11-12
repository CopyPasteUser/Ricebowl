"""RiceClip history cleanup only after confirmed full Wayland screen lock."""

import io
import subprocess
import unittest
from contextlib import redirect_stderr
from unittest import mock

from macrice.cli import main as cli
from macrice.de import clip
from macrice.de import lock


FULL_SESSION = {"RICEBOWL_DE_NESTED": "0",
                "RICEBOWL_DE_SHELL_CHILD": "1",
                "WAYLAND_DISPLAY": "wayland-test"}


class RiceClipLockTests(unittest.TestCase):
    def test_successful_lock_clears_watchers_only_after_lock_confirmation(self):
        order = []

        def run(command, **kwargs):
            order.append(("lock", list(command)))
            self.assertTrue(kwargs["check"])
            self.assertEqual(kwargs["timeout"], 20)
            return subprocess.CompletedProcess(command, 0)

        def clear(operation):
            order.append(("clear", operation))
            return {"ok": True, "count": 0}

        report = lock.lock_screen(environment=FULL_SESSION,
                                  which=lambda name: "/usr/bin/swaylock",
                                  run=run, clear=clear)
        self.assertEqual(report, {"locked": True, "riceclip_cleared": True,
                                  "riceclip_inactive": False})
        self.assertEqual(order, [("lock", ["/usr/bin/swaylock", "-f"]),
                                 ("clear", "clear")])

    def test_failing_locker_never_reports_a_lock_or_clears_history(self):
        def fail(command, **_kwargs):
            raise subprocess.CalledProcessError(1, command)

        clear = mock.Mock()
        with self.assertRaisesRegex(lock.ScreenLockError, "not confirmed"):
            lock.lock_screen(environment=FULL_SESSION,
                             which=lambda name: "/usr/bin/swaylock",
                             run=fail, clear=clear)
        clear.assert_not_called()

    def test_missing_locker_and_nested_preview_fail_before_side_effects(self):
        clear = mock.Mock()
        runner = mock.Mock()
        for environment in (
            {"RICEBOWL_DE_NESTED": "1", "RICEBOWL_DE_SHELL_CHILD": "1",
             "WAYLAND_DISPLAY": "wayland-test"},
            {"RICEBOWL_DE_NESTED": "0", "RICEBOWL_DE_SHELL_CHILD": "0",
             "WAYLAND_DISPLAY": "wayland-test"},
            {"RICEBOWL_DE_NESTED": "0", "RICEBOWL_DE_SHELL_CHILD": "1"},
            {},
        ):
            with self.subTest(environment=environment):
                with self.assertRaises(lock.ScreenLockError):
                    lock.lock_screen(environment=environment, run=runner, clear=clear)
        with self.assertRaisesRegex(lock.ScreenLockError, "unavailable"):
            lock.lock_screen(environment=FULL_SESSION, which=lambda name: None,
                             run=runner, clear=clear)
        runner.assert_not_called()
        clear.assert_not_called()

    def test_failed_watcher_does_not_undo_completed_locker(self):
        def unavailable(_operation):
            raise clip.ClipError("not_running")

        runner = mock.Mock(return_value=subprocess.CompletedProcess([], 0))
        report = lock.lock_screen(environment=FULL_SESSION,
                                  which=lambda name: "/usr/bin/swaylock",
                                  run=runner, clear=unavailable)
        self.assertTrue(report["locked"])
        self.assertFalse(report["riceclip_cleared"])
        runner.assert_called_once()

    def test_verified_absent_optional_watcher_is_a_normal_lock_outcome(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(lock.clip, "socket_path",
                               return_value=Path(directory) / "absent.sock"):
            report = lock.lock_screen(
                environment=FULL_SESSION, which=lambda _name: "/usr/bin/swaylock",
                run=lambda command, **_kwargs: subprocess.CompletedProcess(command, 0),
                clear=lambda _operation: (_ for _ in ()).throw(clip.ClipError("not_running")))
        self.assertTrue(report["locked"])
        self.assertFalse(report["riceclip_cleared"])
        self.assertTrue(report["riceclip_inactive"])

    def test_cli_lock_cannot_run_from_preview_or_json_and_never_autostarts_watcher(self):
        with mock.patch.object(lock, "lock_screen", return_value={
            "locked": True, "riceclip_cleared": True,
            "riceclip_inactive": False}) as wrapper, \
             mock.patch.object(clip, "watch") as watcher:
            self.assertEqual(cli(["de", "lock"]), 0)
            wrapper.assert_called_once_with()
            watcher.assert_not_called()
            for extra in (["--nested"], ["--json"], ["--recipe", "xp-luna"]):
                with self.subTest(extra=extra), redirect_stderr(io.StringIO()):
                    self.assertEqual(cli(["de", "lock", *extra]), 1)
            wrapper.assert_called_once_with()

    def test_cli_reports_unconfirmed_clear_without_leaking_private_clipboard(self):
        with mock.patch.object(lock, "lock_screen", return_value={
            "locked": True, "riceclip_cleared": False,
            "riceclip_inactive": False}), \
             redirect_stderr(io.StringIO()) as warnings:
            self.assertEqual(cli(["de", "lock"]), 0)
        self.assertIn("not confirmed", warnings.getvalue())
        self.assertNotIn("secret-selection", warnings.getvalue())


if __name__ == "__main__":
    unittest.main()
