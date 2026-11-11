"""Full Wayland layout restores never leave a half-applied monitor arrangement."""

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macrice import display_guard
from macrice.de import display_presets, display_restore, session, wayland_displays
from macrice.cli import main


MODE = "1920x1080@60.000000Hz"
ALT = "1280x720@60.000000Hz"


def layout(state):
    return tuple(wayland_displays.Output(name, state[name][0], (MODE, ALT),
                                         state[name][1], state[name][2])
                 for name in ("eDP-1", "HDMI-A-1"))


class DisplayRestoreTests(unittest.TestCase):
    def setUp(self):
        self.original = {
            "eDP-1": (MODE, 1.0, (0, 0)),
            "HDMI-A-1": (MODE, 1.0, (1920, 0)),
        }
        self.target = {
            "eDP-1": (ALT, 1.25, (0, 0)),
            "HDMI-A-1": (ALT, 1.25, (1024, 0)),
        }
        self.saved = display_presets.from_outputs(layout(self.target))

    def test_plan_requires_exact_topology_and_advertised_modes(self):
        before, after = display_restore.plan(self.saved, layout(self.original))
        self.assertEqual(len(before), 2)
        self.assertEqual(after, self.saved)
        with self.assertRaisesRegex(ValueError, "already active"):
            display_restore.plan(self.saved, layout(self.target))
        with self.assertRaisesRegex(ValueError, "connected"):
            display_restore.plan(self.saved[:1], layout(self.original))
        unknown = [{**self.saved[0], "name": "DP-99"}, self.saved[1]]
        with self.assertRaisesRegex(ValueError, "connected"):
            display_restore.plan(unknown, layout(self.original))
        bad = [{**self.saved[0], "mode": "9000x3000@60Hz"}, self.saved[1]]
        with self.assertRaisesRegex(ValueError, "advertised"):
            display_restore.plan(bad, layout(self.original))

    def test_begin_never_starts_without_full_session_or_fresh_saved_data(self):
        with mock.patch.object(wayland_displays, "_in_session", return_value=False), \
             mock.patch.object(display_restore.subprocess, "Popen") as spawned:
            with self.assertRaisesRegex(RuntimeError, "restricted"):
                display_restore.begin(self.saved)
            spawned.assert_not_called()
        with mock.patch.object(wayland_displays, "_in_session", return_value=True), \
             mock.patch.object(display_presets, "load", return_value=[]), \
             mock.patch.object(display_restore.subprocess, "Popen") as spawned:
            with self.assertRaisesRegex(ValueError, "changed"):
                display_restore.begin(self.saved)
            spawned.assert_not_called()

    def _change(self, directory):
        change = display_guard.DisplayChange("a" * 32, Path(directory))
        display_guard._write_new(display_guard._request_path(change), {
            "version": 1,
            "baseline": display_presets.from_outputs(layout(self.original)),
            "target": self.saved,
        })
        return change

    def test_independent_guard_rolls_back_both_outputs_at_timeout(self):
        state = dict(self.original)
        operations = []

        def set_output(name, mode, scale, position):
            operations.append((name, mode, scale, position))
            state[name] = (mode, scale, position)

        with tempfile.TemporaryDirectory() as runtime:
            change = self._change(runtime)
            with mock.patch.object(wayland_displays, "inventory", side_effect=lambda: layout(state)), \
                 mock.patch.object(wayland_displays, "_set", side_effect=set_output), \
                 mock.patch.object(wayland_displays.time, "monotonic", side_effect=(0, 19)):
                self.assertEqual(display_restore.run_worker(change), 1)
            self.assertEqual(state, self.original)
            self.assertEqual(len(operations), 4)
            self.assertEqual([entry[0] for entry in operations],
                             ["eDP-1", "HDMI-A-1", "HDMI-A-1", "eDP-1"])
            self.assertEqual(display_guard.read_status(change)[0], "reverted")

    def test_guard_rolls_back_after_partial_second_output_failure(self):
        state = dict(self.original)
        operations = []

        def set_output(name, mode, scale, position):
            operations.append(name)
            state[name] = (mode, scale, position)
            if len(operations) == 2:
                raise RuntimeError("wlroots disconnected during second write")

        with tempfile.TemporaryDirectory() as runtime:
            change = self._change(runtime)
            with mock.patch.object(wayland_displays, "inventory", side_effect=lambda: layout(state)), \
                 mock.patch.object(wayland_displays, "_set", side_effect=set_output):
                self.assertEqual(display_restore.run_worker(change), 1)
            self.assertEqual(state, self.original)
            self.assertEqual(display_guard.read_status(change)[0], "reverted")

    def test_confirmed_full_layout_is_kept_and_sends_one_refresh(self):
        state = dict(self.original)
        with tempfile.TemporaryDirectory() as runtime:
            change = self._change(runtime)

            def set_output(name, mode, scale, position):
                state[name] = (mode, scale, position)
                if state == self.target:
                    display_guard._write_new(display_guard._keep_path(change), {"keep": True})

            with mock.patch.object(wayland_displays, "inventory", side_effect=lambda: layout(state)), \
                 mock.patch.object(wayland_displays, "_set", side_effect=set_output), \
                 mock.patch.dict("os.environ", {"RICEBOWL_DE_LIVE": "1"}), \
                 mock.patch("macrice.de.live.request", return_value={"ok": True}) as refreshed:
                self.assertEqual(display_restore.run_worker(change), 0)
            self.assertEqual(state, self.target)
            self.assertEqual(display_guard.read_status(change)[0], "kept")
            refreshed.assert_called_once_with("refresh-outputs")

    def test_worker_rejects_stale_output_before_any_mutation(self):
        state = dict(self.original)
        state["HDMI-A-1"] = (ALT, 1.0, (1920, 0))
        with tempfile.TemporaryDirectory() as runtime:
            change = self._change(runtime)
            with mock.patch.object(wayland_displays, "inventory", side_effect=lambda: layout(state)), \
                 mock.patch.object(wayland_displays, "_set") as setter:
                self.assertEqual(display_restore.run_worker(change), 1)
            setter.assert_not_called()
            self.assertEqual(display_guard.read_status(change)[0], "failed")

    def test_worker_rejects_unadvertised_saved_mode_without_partial_write(self):
        current = tuple(wayland_displays.Output(item.name, item.current_mode,
                         (MODE,), item.scale, item.position) for item in layout(self.original))
        with tempfile.TemporaryDirectory() as runtime:
            change = self._change(runtime)
            with mock.patch.object(wayland_displays, "inventory", return_value=current), \
                 mock.patch.object(wayland_displays, "_set") as setter:
                self.assertEqual(display_restore.run_worker(change), 1)
            setter.assert_not_called()
            self.assertEqual(display_guard.read_status(change)[0], "failed")
            self.assertFalse(display_guard._request_path(change).exists())

    def test_explicit_login_trial_opt_in_migrates_v1_and_resets_on_layout_changes(self):
        with tempfile.TemporaryDirectory() as home:
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": home}):
                display_presets.save(self.saved, expected=[])
                self.assertFalse(display_presets.auto_trial_enabled())
                self.assertTrue(display_presets.set_auto_trial(True, expected=False))
                target = Path(home) / "ricebowl/ricespice-displays.json"
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
                self.assertEqual(json.loads(target.read_text())["version"], 2)
                self.assertTrue(display_presets.auto_trial_enabled())
                with self.assertRaisesRegex(ValueError, "changed"):
                    display_presets.set_auto_trial(False, expected=False)
                display_presets.save(self.saved, expected=self.saved)
                self.assertTrue(display_presets.auto_trial_enabled())
                changed = [{**self.saved[0], "x": 200}, self.saved[1]]
                display_presets.save(changed, expected=self.saved)
                self.assertFalse(display_presets.auto_trial_enabled())
                with self.assertRaises(ValueError):
                    display_presets.set_auto_trial("yes", expected=False)
                display_presets.set_auto_trial(True, expected=False)
                display_presets.save([], expected=changed)
                self.assertFalse(display_presets.auto_trial_enabled())
                with self.assertRaisesRegex(ValueError, "Save a monitor"):
                    display_presets.set_auto_trial(True, expected=False)

    def test_legacy_v1_preset_is_safe_and_does_not_opt_in(self):
        with tempfile.TemporaryDirectory() as home, \
             mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": home}):
            root = Path(home) / "ricebowl"
            root.mkdir(mode=0o700)
            old = root / "ricespice-displays.json"
            old.write_text(json.dumps({"version": 1, "outputs": self.saved}))
            old.chmod(0o600)
            self.assertEqual(display_presets.load(), self.saved)
            self.assertFalse(display_presets.auto_trial_enabled())
            old.write_text(json.dumps({"version": 2, "outputs": self.saved,
                                       "auto_trial": "yes"}))
            with self.assertRaises(ValueError):
                display_presets.auto_trial_enabled()

    def test_session_autotrial_is_full_session_only_and_requires_gui(self):
        env = {"RICEBOWL_DE_NESTED": "0", "RICEBOWL_DE_SHELL_CHILD": "1"}
        with mock.patch.object(display_presets, "auto_trial_enabled", return_value=True), \
             mock.patch("macrice.de.settings._gtk_modules", return_value=(1, 2, 3)), \
             mock.patch.object(display_presets, "load", return_value=self.saved), \
             mock.patch.object(display_restore, "begin", return_value=
                               display_guard.DisplayChange("b" * 32, Path("/private"))) as begin, \
             mock.patch.object(session, "project_root", return_value=Path("/app")):
            spawned = mock.Mock(return_value=object())
            self.assertIsNone(session._start_auto_monitor_trial({**env, "RICEBOWL_DE_NESTED": "1"},
                                                                 spawned))
            spawned.assert_not_called()
            self.assertIsNotNone(session._start_auto_monitor_trial(env, spawned))
            begin.assert_called_once_with(self.saved)
            self.assertEqual(spawned.call_args.args[0][1:],
                             ["/app/launcher.py", "de", "display-confirm",
                              "--display-token", "b" * 32])
            self.assertEqual(spawned.call_args.kwargs["env"], env)

        with mock.patch.object(display_presets, "auto_trial_enabled", return_value=False), \
             mock.patch.object(display_restore, "begin") as begin:
            self.assertIsNone(session._start_auto_monitor_trial(env, mock.Mock()))
            begin.assert_not_called()
        with mock.patch.object(display_presets, "auto_trial_enabled", return_value=True), \
             mock.patch("macrice.de.settings._gtk_modules", side_effect=ImportError("GI absent")), \
             mock.patch.object(display_restore, "begin") as begin:
            self.assertIsNone(session._start_auto_monitor_trial(env, mock.Mock()))
            begin.assert_not_called()

    def test_confirmation_requires_wayland_and_explicit_token(self):
        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "XFCE",
                                              "RICEBOWL_DE_SHELL_CHILD": "0"}), \
             mock.patch("macrice.de.settings._gtk_modules") as gtk:
            from macrice.de.settings import launch_display_confirmation
            with self.assertRaisesRegex(ValueError, "full RiceBowl login"):
                launch_display_confirmation("a" * 32)
            gtk.assert_not_called()
        with mock.patch("builtins.print"):
            self.assertEqual(main(["de", "display-confirm"]), 1)
            self.assertEqual(main(["de", "settings", "--display-token", "a" * 32]), 1)


if __name__ == "__main__":
    unittest.main()
