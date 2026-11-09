"""Bounded native RiceSpice input, accessibility and Wayland monitor regression tests."""

import json
import os
import stat
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from macrice.de import display_presets, preferences, session, wayland_displays
from macrice import display_guard


SAMPLE_MONITORS = '''eDP-1 "Laptop panel"
 Physical size: 310x170 mm
 Enabled: yes
 Modes:
  1920x1080 px, 60.000000 Hz (preferred, current)
  1280x720 px, 60.000000 Hz
 Position: 0,0
 Transform: normal
 Scale: 1.000000
HDMI-A-1 "External"
 Enabled: yes
 Modes:
  2560x1440 px, 59.950000 Hz (current)
  1920x1080 px, 60.000000 Hz (preferred)
 Position: 1920,0
 Scale: 1.250000
DP-1 "Disconnected"
 Enabled: no
'''


class RiceSpicePreferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp.name})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_private_save_roundtrip_and_stale_write(self):
        original = preferences.load()
        self.assertEqual(original, preferences.DEFAULTS)
        requested = {**original, "pointer_speed": -0.5, "natural_scroll": True,
                     "gtk_text_scale": 1.25, "cursor_size": 48,
                     "input_enabled": True, "accessibility_enabled": True}
        self.assertEqual(preferences.save(requested, expected=original), requested)
        path = Path(self.tmp.name) / "ricebowl/ricespice.json"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        self.assertEqual(preferences.load(), requested)
        with self.assertRaisesRegex(preferences.PreferenceError, "changed elsewhere"):
            preferences.save(original, expected=original)

    def test_malformed_and_unsafe_file_never_changes_session(self):
        base = Path(self.tmp.name) / "ricebowl"
        base.mkdir(mode=0o700)
        path = base / "ricespice.json"
        path.write_text('{"version":1,"pointer_speed":99}')
        path.chmod(0o600)
        with self.assertRaises(preferences.PreferenceError):
            preferences.load()
        path.chmod(0o644)
        with self.assertRaisesRegex(preferences.PreferenceError, "Unsafe"):
            preferences.load()
        path.unlink()
        path.symlink_to(base / "elsewhere")
        with self.assertRaises(preferences.PreferenceError):
            preferences.load()

    def test_legacy_v1_preferences_migrate_without_enabling_orca(self):
        path = Path(self.tmp.name) / "ricebowl/ricespice.json"
        path.parent.mkdir(mode=0o700)
        legacy = {key: value for key, value in preferences.DEFAULTS.items()
                  if key not in ("screen_reader_enabled", "high_contrast")}
        path.write_text(json.dumps({"version": 1, **legacy}))
        path.chmod(0o600)
        current = preferences.load()
        self.assertFalse(current["screen_reader_enabled"])
        self.assertFalse(current["high_contrast"])
        preferences.save({**current, "accessibility_enabled": True,
                          "high_contrast": True}, expected=current)
        self.assertEqual(json.loads(path.read_text())["version"], 2)
        env = {}
        preferences.apply_session_environment(env, preferences.load())
        self.assertEqual(env["GTK_THEME"], "HighContrast")

    def test_rejects_unknown_or_boolean_numeric_values(self):
        original = preferences.load()
        for change in ({"pointer_speed": True}, {"cursor_size": 4096},
                       {"repeat_rate": 0}, {"gtk_text_scale": float("nan")}):
            with self.subTest(change=change), self.assertRaises(preferences.PreferenceError):
                preferences.save({**original, **change}, expected=original)
        self.assertFalse((Path(self.tmp.name) / "ricebowl/ricespice.json").exists())

    def test_private_labwc_xml_and_session_environment(self):
        with tempfile.TemporaryDirectory() as runtime:
            cfg = session._custom_labwc_config(None, runtime, {
                **preferences.DEFAULTS, "input_enabled": True,
                "repeat_rate": 35, "tap_to_click": False,
            })
            root = ET.parse(cfg / "rc.xml").getroot()
            self.assertEqual(root.findtext("keyboard/repeatRate"), "35")
            self.assertEqual(root.findtext("keyboard/repeatDelay"), "600")
            self.assertEqual(root.findtext("libinput/device[@category='touchpad']/tap"), "no")
            self.assertTrue((cfg / "menu.xml").is_file())
            self.assertEqual(ET.parse(session.resources() / "labwc/rc.xml").getroot().find(
                "libinput"), None)
            env = {}
            preferences.apply_session_environment(env, {
                **preferences.DEFAULTS, "accessibility_enabled": True,
                "cursor_size": 48, "gtk_text_scale": 1.5,
            })
            self.assertEqual(env, {"XCURSOR_SIZE": "48", "GDK_DPI_SCALE": "1.5"})

    def test_accessibility_only_does_not_change_keyboard_or_pointer(self):
        with tempfile.TemporaryDirectory() as runtime:
            cfg = session._custom_labwc_config(None, runtime, {
                **preferences.DEFAULTS, "accessibility_enabled": True,
                "cursor_size": 64,
            })
            tree = ET.parse(cfg / "rc.xml")
            self.assertIsNone(tree.getroot().find("libinput"))
            self.assertIsNone(tree.getroot().find("keyboard/repeatRate"))
            env = {"XCURSOR_SIZE": "99"}
            preferences.apply_session_environment(env, {
                **preferences.DEFAULTS, "input_enabled": True,
            })
            self.assertEqual(env, {"XCURSOR_SIZE": "99"})

    def test_existing_0755_ricebowl_parent_is_supported(self):
        parent = Path(self.tmp.name) / "ricebowl"
        parent.mkdir(mode=0o755)
        current = preferences.load()
        preferences.save({**current, "input_enabled": True}, expected=current)
        self.assertEqual(preferences.load()["input_enabled"], True)

    def test_monitor_presets_are_private_and_stale_safe(self):
        outputs = wayland_displays.parse(SAMPLE_MONITORS)
        snapshot = display_presets.from_outputs(outputs)
        self.assertEqual(display_presets.load(), [])
        display_presets.save(snapshot, expected=[])
        path = Path(self.tmp.name) / "ricebowl/ricespice-displays.json"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(display_presets.load(), snapshot)
        with self.assertRaisesRegex(ValueError, "changed"):
            display_presets.save([], expected=[])
        display_presets.save([], expected=snapshot)
        self.assertEqual(display_presets.load(), [])
        with self.assertRaises(ValueError):
            display_presets.save([{"name": "DP-1;rm", "mode": "1920x1080@60Hz",
                                   "scale": 1.0, "x": 0, "y": 0}], expected=[])

    @unittest.skipIf(os.geteuid() == 0, "session cleanup requires a real non-root owner")
    def test_start_uses_isolated_config_only_when_saved(self):
        baseline = preferences.load()
        preferences.save({**baseline, "input_enabled": True,
                          "accessibility_enabled": True, "repeat_rate": 50}, expected=baseline)
        tools = {name: f"/usr/bin/{name}" for name in (*session.REQUIRED_TOOLS, "swayidle")}
        with tempfile.TemporaryDirectory() as runtime:
            Path(runtime).chmod(0o700)
            env = {"XDG_RUNTIME_DIR": runtime,
                   "DBUS_SESSION_BUS_ADDRESS": "unix:path=test", "DISPLAY": ":2"}
            calls = []

            def fake_exec(program, argv, spawned_env):
                calls.append((program, argv, spawned_env))
                raise OSError("simulate failed exec")

            with mock.patch("macrice.de.session._check_runtime_dir"):
                with self.assertRaises(OSError):
                    session.start(nested=True, environment=env, which=tools.get,
                                  execute=fake_exec)
            _, argv, spawn_env = calls[0]
            self.assertIn("ricebowl-labwc-", argv[argv.index("--config-dir") + 1])
            self.assertEqual(spawn_env["XCURSOR_SIZE"], "24")
            self.assertFalse(Path(spawn_env["RICEBOWL_DE_SESSION_CONFIG"]).exists(),
                             "A failed login must clean up its temporary settings")

    @unittest.skipIf(os.geteuid() == 0, "Wayland sessions cannot run as root")
    def test_orca_preference_only_enters_full_session_environment(self):
        original = preferences.load()
        preferences.save({**original, "accessibility_enabled": True,
                          "screen_reader_enabled": True}, expected=original)
        tools = {name: f"/usr/bin/{name}" for name in (*session.REQUIRED_TOOLS, "swayidle")}
        with tempfile.TemporaryDirectory() as runtime:
            Path(runtime).chmod(0o700)
            env = {"XDG_RUNTIME_DIR": runtime,
                   "DBUS_SESSION_BUS_ADDRESS": "unix:path=test", "RICEBOWL_DM_SESSION": "1"}
            calls = []

            def fake_exec(program, argv, child_env):
                calls.append(dict(child_env))
                raise OSError("simulate failed exec")

            with mock.patch("macrice.de.session._check_runtime_dir"):
                with self.assertRaises(OSError):
                    session.start(environment=env, which=tools.get, execute=fake_exec)
                self.assertEqual(calls[-1]["RICEBOWL_DE_SCREEN_READER"], "1")
                with self.assertRaises(OSError):
                    session.start(nested=True, environment=env, which=tools.get, execute=fake_exec)
                self.assertNotIn("RICEBOWL_DE_SCREEN_READER", calls[-1])


class WaylandMonitorTests(unittest.TestCase):
    def test_reads_only_enabled_and_advertised_modes(self):
        outputs = wayland_displays.parse(SAMPLE_MONITORS)
        self.assertEqual([out.name for out in outputs], ["eDP-1", "HDMI-A-1"])
        self.assertEqual(outputs[0].current_mode, "1920x1080@60.000000Hz")
        self.assertEqual(outputs[1].scale, 1.25)
        self.assertEqual(outputs[1].position, (1920, 0))
        with self.assertRaisesRegex(ValueError, "advertised"):
            wayland_displays._validated("eDP-1", "800x600@60Hz", 1.0, outputs)
        with self.assertRaisesRegex(ValueError, "scale"):
            wayland_displays._validated("eDP-1", outputs[0].current_mode, 4, outputs)

    def test_rejects_incomplete_inventory_and_injection(self):
        for value in ("", SAMPLE_MONITORS.replace("(preferred, current)", "(preferred)")
                      .replace("(current)", ""),
                      SAMPLE_MONITORS.replace('eDP-1 "Laptop panel"',
                                              'eDP-1;sh "Laptop panel"'),
                      SAMPLE_MONITORS * 30):
            with self.subTest(value=value[:40]), self.assertRaises(ValueError):
                wayland_displays.parse(value)

    def test_outside_ricebowl_no_monitor_query_or_write(self):
        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "XFCE",
                                             "RICEBOWL_DE_SHELL_CHILD": "0"}), \
                mock.patch("macrice.de.wayland_displays._run") as run:
            with self.assertRaisesRegex(RuntimeError, "restricted"):
                wayland_displays.inventory()
            run.assert_not_called()

    def test_worker_times_out_and_restores_original_mode(self):
        with tempfile.TemporaryDirectory() as runtime:
            root = Path(runtime)
            change = display_guard.DisplayChange("a" * 32, root)
            display_guard._write_new(display_guard._request_path(change), {
                "name": "eDP-1", "mode": "1280x720@60.000000Hz", "scale": 1.5,
                "old_mode": "1920x1080@60.000000Hz", "old_scale": 1.0,
            })
            state = {"mode": "1920x1080@60.000000Hz", "scale": 1.0}
            operations = []

            def apply(name, mode, scale):
                operations.append((name, mode, scale))
                state.update(mode=mode, scale=scale)

            def current():
                return (wayland_displays.Output("eDP-1", state["mode"],
                        ("1920x1080@60.000000Hz", "1280x720@60.000000Hz"),
                        state["scale"]),)

            with mock.patch("macrice.de.wayland_displays.inventory", side_effect=current), \
                    mock.patch("macrice.de.wayland_displays._set", side_effect=apply), \
                    mock.patch("macrice.de.wayland_displays.time.monotonic",
                               side_effect=(0, 19)):
                self.assertEqual(wayland_displays.run_worker(change), 1)
            self.assertEqual(operations[-1], ("eDP-1", "1920x1080@60.000000Hz", 1.0))
            self.assertEqual(display_guard.read_status(change)[0], "reverted")
            self.assertFalse(display_guard._request_path(change).exists())

    def test_confirmation_keeps_trial_without_rollback(self):
        with tempfile.TemporaryDirectory() as runtime:
            change = display_guard.DisplayChange("b" * 32, Path(runtime))
            display_guard._write_new(display_guard._request_path(change), {
                "name": "eDP-1", "mode": "1280x720@60.000000Hz", "scale": 1.5,
                "old_mode": "1920x1080@60.000000Hz", "old_scale": 1.0,
            })
            applied = []

            def apply(_name, mode, scale):
                applied.append((mode, scale))
                display_guard._write_new(display_guard._keep_path(change), {"keep": True})

            def matched(_name, mode, scale):
                return (mode, scale) == applied[-1]

            original = wayland_displays.parse(SAMPLE_MONITORS)
            with mock.patch("macrice.de.wayland_displays.inventory", return_value=original), \
                    mock.patch("macrice.de.wayland_displays._set", side_effect=apply), \
                    mock.patch("macrice.de.wayland_displays._matches", side_effect=matched):
                self.assertEqual(wayland_displays.run_worker(change), 0)
            self.assertEqual(applied, [("1280x720@60.000000Hz", 1.5)])
            self.assertEqual(display_guard.read_status(change)[0], "kept")

    def test_confirmed_mode_change_requests_owner_only_waybar_refresh(self):
        with tempfile.TemporaryDirectory() as runtime:
            change = display_guard.DisplayChange("f" * 32, Path(runtime))
            display_guard._write_new(display_guard._request_path(change), {
                "name": "eDP-1", "mode": "1280x720@60.000000Hz", "scale": 1.5,
                "old_mode": "1920x1080@60.000000Hz", "old_scale": 1.0,
            })

            def apply(_name, _mode, _scale):
                display_guard._write_new(display_guard._keep_path(change), {"keep": True})

            with mock.patch("macrice.de.wayland_displays.inventory",
                            return_value=wayland_displays.parse(SAMPLE_MONITORS)), \
                    mock.patch("macrice.de.wayland_displays._set", side_effect=apply), \
                    mock.patch("macrice.de.wayland_displays._matches", return_value=True), \
                    mock.patch.dict(os.environ, {"RICEBOWL_DE_LIVE": "1"}), \
                    mock.patch("macrice.de.live.request", return_value={"ok": True}) as refresh:
                self.assertEqual(wayland_displays.run_worker(change), 0)
            refresh.assert_called_once_with("refresh-outputs")
            self.assertEqual(display_guard.read_status(change)[0], "kept")

    def test_worker_rejects_stale_topology_before_changing_output(self):
        with tempfile.TemporaryDirectory() as runtime:
            change = display_guard.DisplayChange("c" * 32, Path(runtime))
            display_guard._write_new(display_guard._request_path(change), {
                "name": "eDP-1", "mode": "1280x720@60.000000Hz", "scale": 1.5,
                "old_mode": "1920x1080@60.000000Hz", "old_scale": 2.0,
            })
            with mock.patch("macrice.de.wayland_displays.inventory",
                            return_value=wayland_displays.parse(SAMPLE_MONITORS)), \
                    mock.patch("macrice.de.wayland_displays._set") as apply:
                self.assertEqual(wayland_displays.run_worker(change), 1)
            apply.assert_not_called()
            self.assertEqual(display_guard.read_status(change)[0], "failed")

    def test_position_change_rolls_back_if_not_confirmed(self):
        with tempfile.TemporaryDirectory() as runtime:
            change = display_guard.DisplayChange("d" * 32, Path(runtime))
            display_guard._write_new(display_guard._request_path(change), {
                "name": "eDP-1", "mode": "1920x1080@60.000000Hz", "scale": 1.0,
                "old_mode": "1920x1080@60.000000Hz", "old_scale": 1.0,
                "x": 1920, "y": 0, "old_x": 0, "old_y": 0,
            })
            position = [0, 0]
            commands = []

            def apply(name, mode, scale, target):
                commands.append((name, mode, scale, target))
                position[:] = target

            def snapshot():
                return (wayland_displays.Output("eDP-1", "1920x1080@60.000000Hz",
                        ("1920x1080@60.000000Hz",), 1.0, tuple(position)),)

            with mock.patch("macrice.de.wayland_displays.inventory", side_effect=snapshot), \
                    mock.patch("macrice.de.wayland_displays._set", side_effect=apply), \
                    mock.patch("macrice.de.wayland_displays.time.monotonic",
                               side_effect=(0, 19)):
                self.assertEqual(wayland_displays.run_worker(change), 1)
            self.assertEqual(position, [0, 0])
            self.assertEqual(commands[0][-1], (1920, 0))
            self.assertEqual(commands[-1][-1], (0, 0))
            self.assertEqual(display_guard.read_status(change)[0], "reverted")


if __name__ == "__main__":
    unittest.main()
