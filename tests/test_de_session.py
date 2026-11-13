"""Session safety: login, nested mode, sandboxed config and supervised clients."""

import os
import io
import json
import shlex
import signal
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import nullcontext
from pathlib import Path
from unittest import mock

from macrice.de import session
from macrice.de import live_recovery, recipes, staging


class _ExecCalled(Exception):
    def __init__(self, program, argv, env):
        self.program = program
        self.argv = argv
        self.env = env


def _record_exec(program, argv, env):
    raise _ExecCalled(program, argv, env)


class _FakeProcess:
    def __init__(self):
        self.terminated = False
        self.killed = False

    def poll(self):
        return 0 if self.terminated else None

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True
        self.terminated = True

    def wait(self, timeout=None):
        return 0


class WaylandSessionTests(unittest.TestCase):
    def setUp(self):
        self.runtime = tempfile.TemporaryDirectory()
        os.chmod(self.runtime.name, 0o700)
        self.addCleanup(self.runtime.cleanup)
        self.env = {"XDG_RUNTIME_DIR": self.runtime.name, "DBUS_SESSION_BUS_ADDRESS": "unix:path=test"}
        self.tools = {name: f"/usr/bin/{name}" for name in
                      (*session.REQUIRED_TOOLS, "dbus-run-session", "swayidle")}

    def which(self, command):
        return self.tools.get(command)

    def test_luna_window_chrome_is_private_and_other_rices_unmodified(self):
        luna = recipes.parse((Path(__file__).resolve().parents[1] /
                              "examples/wayland/xp-luna-columns.json").read_bytes())
        directory = session._custom_labwc_config(luna, self.runtime.name)
        self.addCleanup(session._cleanup_labwc_config,
                        {"RICEBOWL_DE_SESSION_CONFIG": str(directory),
                         "XDG_RUNTIME_DIR": self.runtime.name})
        override = directory / "themerc-override"
        self.assertEqual(override.stat().st_uid, os.geteuid())
        self.assertEqual(override.stat().st_mode & 0o777, 0o600)
        text = override.read_text(encoding="utf-8")
        self.assertIn("window.active.title.bg: Gradient Vertical", text)
        self.assertIn("window.active.title.bg.color: #4b9bed", text)
        self.assertIn("window.active.border.color: #0a3278", text)
        self.assertTrue((directory / ".ricebowl-managed").is_file())
        classic = session._custom_labwc_config(None, self.runtime.name)
        self.addCleanup(session._cleanup_labwc_config,
                        {"RICEBOWL_DE_SESSION_CONFIG": str(classic),
                         "XDG_RUNTIME_DIR": self.runtime.name})
        self.assertFalse((classic / "themerc-override").exists())

    @mock.patch("macrice.de.session.os.geteuid", return_value=1000)
    @mock.patch("macrice.de.session._check_runtime_dir")
    def test_nested_exec_uses_isolated_config_and_preserves_parent_bus(self, _runtime, _uid):
        env = {**self.env, "DISPLAY": ":0", "XDG_CURRENT_DESKTOP": "XFCE"}
        with self.assertRaises(_ExecCalled) as caught:
            session.start(nested=True, environment=env, which=self.which, execute=_record_exec)
        call = caught.exception
        self.assertEqual(call.program, "/usr/bin/labwc")
        self.assertIn("--config-dir", call.argv)
        active_config = Path(call.argv[call.argv.index("--config-dir") + 1])
        self.assertEqual(active_config.parent, Path(self.runtime.name))
        self.assertTrue((active_config / ".ricebowl-managed").is_file())
        self.assertEqual(call.env["RICEBOWL_DE_LIVE"], "1")
        self.assertEqual(call.env["LABWC_UPDATE_ACTIVATION_ENV"], "0")
        self.assertEqual(call.env["XDG_CURRENT_DESKTOP"], session.DESKTOP_NAME)
        self.assertEqual(env["XDG_CURRENT_DESKTOP"], "XFCE")
        self.assertIn("de shell", call.argv[-1])
        wrapper = shlex.split(call.argv[-1])
        self.assertEqual(wrapper[:2], ["sh", "-c"])
        self.assertIn("labwc --exit", wrapper[2])

    def test_existing_desktop_requires_nested_or_login_wrapper(self):
        with self.assertRaisesRegex(session.SessionError, "already active"):
            session.start(environment={**self.env, "DISPLAY": ":0"}, which=self.which,
                          execute=_record_exec)

    @mock.patch("macrice.de.session.os.geteuid", return_value=1000)
    @mock.patch("macrice.de.session._check_runtime_dir")
    def test_login_manager_does_not_inherit_greeter_display(self, _runtime, _uid):
        env = {**self.env, "RICEBOWL_DM_SESSION": "1", "DISPLAY": ":10",
               "WAYLAND_DISPLAY": "wayland-greeter", "LABWC_UPDATE_ACTIVATION_ENV": "0"}
        with self.assertRaises(_ExecCalled) as caught:
            session.start(environment=env, which=self.which, execute=_record_exec)
        self.assertNotIn("DISPLAY", caught.exception.env)
        self.assertNotIn("WAYLAND_DISPLAY", caught.exception.env)
        self.assertNotIn("LABWC_UPDATE_ACTIVATION_ENV", caught.exception.env)

    @mock.patch("macrice.de.session._check_runtime_dir")
    def test_start_works_with_mint_22_labwc_071_options(self, _runtime):
        with self.assertRaises(_ExecCalled) as caught:
            session.start(environment=self.env, which=self.which, execute=_record_exec)
        self.assertIn("--startup", caught.exception.argv)
        self.assertNotIn("--session", caught.exception.argv)

    @mock.patch("macrice.de.session.os.geteuid", return_value=1000)
    @mock.patch("macrice.de.session._check_runtime_dir")
    def test_unsafe_interrupted_switch_uses_classic_for_next_login(self, _runtime, _uid):
        with mock.patch("macrice.de.live_recovery.reconcile", return_value={
                "status": "unsafe", "use_saved_selection": False}):
            with self.assertRaises(_ExecCalled) as caught:
                session.start(environment=self.env, which=self.which, execute=_record_exec)
        self.assertEqual(caught.exception.env["RICEBOWL_DE_RECIPE"], "classic")
        self.assertEqual(caught.exception.program, "/usr/bin/labwc")

    @mock.patch("macrice.de.session._check_runtime_dir")
    def test_full_login_recovers_just_the_interrupted_next_login_selection(self, _runtime):
        config = Path(self.runtime.name) / "config"
        config.mkdir(mode=0o700)
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)}):
            digest = staging._hash("chrome")
            live_recovery.begin("chrome", digest, None)
            recipes.change_selection("chrome", expected_active="classic",
                                     expected_semantic_sha256=digest)
            with mock.patch.object(live_recovery, "_owner_running", return_value=False):
                with self.assertRaises(_ExecCalled) as caught:
                    session.start(environment=self.env, which=self.which, execute=_record_exec)
            self.assertEqual(caught.exception.env.get("RICEBOWL_DE_RECIPE"), None)
            self.assertIsNone(recipes._selection_snapshot())
            self.assertIsNone(live_recovery.read())

    def test_corrupt_selection_and_ricespice_preferences_keep_owner_data_untouched(self):
        config = Path(self.runtime.name) / "config"
        private = config / "ricebowl"
        selections = private / "recipes"
        selections.mkdir(parents=True, mode=0o700)
        config.chmod(0o700)
        private.chmod(0o700)
        selection = selections / ".active-recipe"
        preferences = private / "ricespice.json"
        selection.write_bytes(b"{broken-selection\n")
        preferences.write_bytes(b"{broken-preferences\n")
        selection.chmod(0o600)
        preferences.chmod(0o600)
        original = (selection.read_bytes(), preferences.read_bytes())
        warnings = io.StringIO()

        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)}), \
             mock.patch("sys.stderr", warnings), \
             self.assertRaises(_ExecCalled) as caught:
            session.start(environment=self.env, which=self.which, execute=_record_exec)

        self.assertEqual(caught.exception.program, "/usr/bin/labwc")
        self.assertNotIn("RICEBOWL_DE_RECIPE", caught.exception.env)
        self.assertNotIn("RICEBOWL_DE_SCREEN_READER", caught.exception.env)
        self.assertNotIn("GTK_THEME", caught.exception.env)
        self.assertIn("ignoring invalid saved recipe selection", warnings.getvalue())
        self.assertIn("ignoring unsafe RiceSpice preferences", warnings.getvalue())
        self.assertEqual((selection.read_bytes(), preferences.read_bytes()), original)

    def test_missing_tool_fails_before_starting_compositor(self):
        with self.assertRaisesRegex(session.SessionError, "Missing Wayland preview dependencies: foot"):
            session.start(environment=self.env, which=lambda name: None if name == "foot"
                          else self.which(name), execute=_record_exec)

    def test_full_login_requires_idle_lock_but_nested_preview_does_not(self):
        missing_idle = lambda name: None if name == "swayidle" else self.which(name)
        with self.assertRaisesRegex(session.SessionError, "swayidle"):
            session.start(environment=self.env, which=missing_idle,
                          execute=_record_exec)
        with self.assertRaises(_ExecCalled) as caught:
            session.start(nested=True, environment=self.env,
                          which=missing_idle, execute=_record_exec)
        self.assertEqual(caught.exception.program, "/usr/bin/labwc")

    def test_missing_bus_reexecs_at_most_once(self):
        env = {"XDG_RUNTIME_DIR": self.runtime.name}
        with self.assertRaises(_ExecCalled) as caught:
            session.start(environment=env, which=self.which, execute=_record_exec)
        self.assertEqual(caught.exception.program, "/usr/bin/dbus-run-session")
        self.assertEqual(caught.exception.argv[1], "--")
        self.assertEqual(caught.exception.env["RICEBOWL_DE_BUS_REEXEC"], "1")
        with self.assertRaisesRegex(session.SessionError, "unbounded restart"):
            session.start(environment={**env, "RICEBOWL_DE_BUS_REEXEC": "1"},
                          which=self.which, execute=_record_exec)

    @mock.patch("macrice.de.session.os.geteuid", return_value=1000)
    @mock.patch("macrice.de.session._check_runtime_dir")
    def test_selected_recipe_survives_one_time_dbus_reexec(self, _runtime, _uid):
        with self.assertRaises(_ExecCalled) as caught:
            session.start(nested=True, recipe="chrome",
                          environment={"XDG_RUNTIME_DIR": self.runtime.name},
                          which=self.which, execute=_record_exec)
        self.assertEqual(caught.exception.program, "/usr/bin/dbus-run-session")
        self.assertEqual(caught.exception.argv[-2:], ["--recipe", "chrome"])

    @mock.patch("macrice.de.session.os.geteuid", return_value=os.getuid())
    @mock.patch("macrice.de.session._check_runtime_dir")
    def test_imported_recipe_id_is_resolved_for_native_and_dbus_reexec(self, _runtime, _uid):
        from macrice.de import recipes
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "config"
            config.mkdir(mode=0o700)
            source = Path(folder) / "portable.json"
            data = json.loads(recipes.BUILTINS["chrome"].read_text())
            data["id"] = "portable-rice"
            source.write_text(json.dumps(data), encoding="utf-8")
            source.chmod(0o600)
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)}):
                _, installed = recipes.import_recipe(source)
                tools = {**self.tools, "riceplate-native": "/usr/bin/riceplate-native"}
                with self.assertRaises(_ExecCalled) as caught:
                    session.start(nested=True, panel="native", recipe="portable-rice",
                                  environment={"XDG_RUNTIME_DIR": self.runtime.name},
                                  which=tools.get, execute=_record_exec)
            call = caught.exception
            self.assertEqual(call.program, "/usr/bin/dbus-run-session")
            self.assertEqual(call.argv[-4:], ["--recipe", str(installed), "--panel", "native"])
            self.assertEqual(call.env["RICEBOWL_DE_RECIPE"], str(installed))

    @mock.patch("macrice.de.session.os.geteuid", return_value=1000)
    @mock.patch("macrice.de.session._check_runtime_dir")
    def test_native_panel_requires_installed_binary_and_survives_dbus_reexec(self, _runtime, _uid):
        with self.assertRaisesRegex(session.SessionError, "not installed"):
            session.start(nested=True, panel="native", environment=self.env,
                          which=self.which, execute=_record_exec)
        tools = {**self.tools, "riceplate-native": "/usr/bin/riceplate-native"}
        with self.assertRaises(_ExecCalled) as caught:
            session.start(nested=True, panel="native", recipe="chrome",
                          environment={"XDG_RUNTIME_DIR": self.runtime.name},
                          which=tools.get, execute=_record_exec)
        self.assertEqual(caught.exception.argv[-4:], ["--recipe", "chrome", "--panel", "native"])
        self.assertEqual(caught.exception.env["RICEBOWL_DE_PANEL"], "native")

    @mock.patch("macrice.de.session.os.geteuid", return_value=1000)
    @mock.patch("macrice.de.session._check_runtime_dir")
    def test_native_panel_opt_in_not_inherited_from_parent(self, _runtime, _uid):
        with self.assertRaises(_ExecCalled) as caught:
            session.start(nested=True, environment={**self.env, "RICEBOWL_DE_PANEL": "native"},
                          which=self.which, execute=_record_exec)
        self.assertEqual(caught.exception.env["RICEBOWL_DE_PANEL"], "waybar")

    @mock.patch("macrice.de.session.os.geteuid", return_value=os.getuid())
    @mock.patch("macrice.de.session._check_runtime_dir")
    def test_bad_recipe_fails_before_labwc_exec(self, _runtime, _uid):
        # Bare imported IDs are now valid tokens, but an unknown ID must be
        # rejected before the compositor is launched.
        with self.assertRaisesRegex(ValueError, "safely"):
            session.start(nested=True, recipe="unknown-nonabsolute-recipe",
                          environment=self.env, which=self.which, execute=_record_exec)

    def test_wrong_runtime_directory_is_rejected(self):
        os.chmod(self.runtime.name, 0o755)
        with self.assertRaisesRegex(session.SessionError, "owner-only"):
            session.start(environment=self.env, which=self.which, execute=_record_exec)

    @mock.patch("macrice.de.session.os.geteuid", return_value=0)
    def test_no_root_session(self, _uid):
        with self.assertRaisesRegex(session.SessionError, "unprivileged"):
            session.start(environment=self.env, which=self.which, execute=_record_exec)

    def test_shell_rejects_calls_outside_its_labwc_session(self):
        with self.assertRaisesRegex(session.SessionError, "only run inside"):
            session.shell(environment={"WAYLAND_DISPLAY": "wayland-0"}, which=self.which)

    def test_suspend_gap_detects_kernel_wake_not_normal_idle(self):
        # A clock step on BOOTTIME alone is a real sleep interval, not an
        # NTP/wallclock correction or ordinary scheduling latency.
        samples = iter([(10.0, 100.0), (11.0, 101.2), (12.0, 102.2),
                        (13.0, 107.2), (14.0, 108.2)])
        detector = session._ResumeGap(reader=lambda: next(samples))
        self.assertEqual([detector.resumed() for _ in range(5)],
                         [False, False, False, True, False])

    def test_suspend_gap_disables_cleanly_if_clock_is_unavailable(self):
        def failed_clock():
            raise OSError("CLOCK_BOOTTIME not supported")
        self.assertFalse(session._ResumeGap(reader=failed_clock).resumed())
        with mock.patch.object(session.time, "CLOCK_BOOTTIME", create=True):
            detector = session._ResumeGap(reader=lambda: (1.0, 1.0))
            self.assertFalse(detector.resumed())

    def test_idle_guard_failure_ends_nonlive_supervision(self):
        class RunningPanel(_FakeProcess):
            def wait(self, timeout=None):
                if self.terminated:
                    return -15
                raise session.subprocess.TimeoutExpired("waybar", timeout)
        class LostIdle(_FakeProcess):
            def __init__(self):
                super().__init__()
                self.calls = 0
            def poll(self):
                self.calls += 1
                return 7 if self.calls > 1 else None
        panel = RunningPanel()
        self.assertEqual(session._wait_with_idle_guard(panel, LostIdle()), (1, True))
        self.assertTrue(panel.terminated)

    def test_nonlive_shell_does_not_block_when_idle_watcher_dies(self):
        commands = []
        class RunningPanel(_FakeProcess):
            def wait(self, timeout=None):
                if self.terminated:
                    return -15
                raise session.subprocess.TimeoutExpired("waybar", timeout)
        class CrashedIdle(_FakeProcess):
            calls = 0
            def poll(self):
                self.calls += 1
                return 4 if self.calls >= 2 else None
        panel = RunningPanel()
        def spawn(command, **_kwargs):
            commands.append(command)
            return CrashedIdle() if command[0] == "/usr/bin/swayidle" else panel
        env = {"RICEBOWL_DE_SHELL_CHILD": "1", "RICEBOWL_DE_NESTED": "0",
               "RICEBOWL_DE_LIVE": "0", "WAYLAND_DISPLAY": "wayland-0"}
        with mock.patch("macrice.de.session.signal.signal"), \
             mock.patch("sys.stderr"):
            self.assertEqual(session.shell(environment=env, which=self.which,
                                           spawn=spawn), 1)
        self.assertTrue(panel.terminated)
        self.assertEqual([cmd[0] for cmd in commands],
                         ["/usr/bin/swayidle", "/usr/bin/waybar"])

    def test_no_idle_guard_keeps_nested_immediate_wait(self):
        proc = _FakeProcess()
        self.assertEqual(session._wait_with_idle_guard(proc, None), (0, False))

    def test_wayland_output_event_debounce_is_event_driven_and_bounded(self):
        reading, writing = os.pipe()
        self.addCleanup(lambda: os.close(writing))
        with os.fdopen(reading, "rb", buffering=0) as stream:
            observer = session._OutputEvents(stream)
            self.assertFalse(observer.ready(10.0))  # No event, no inventory poll.
            os.write(writing, b"unrecognized\n")
            self.assertFalse(observer.ready(10.1))
            os.write(writing, b"changed\nchanged\n")
            self.assertFalse(observer.ready(10.2))
            self.assertFalse(observer.ready(10.7))
            os.write(writing, b"chan")
            self.assertFalse(observer.ready(10.71))
            os.write(writing, b"ged\n")
            self.assertFalse(observer.ready(10.75))  # Split event extends debounce.
            self.assertTrue(observer.ready(11.41))
            self.assertFalse(observer.ready(11.42))

    def test_shell_supervises_background_services_and_uses_private_panel_config(self):
        commands = []
        processes = []

        def spawn(command, **_kwargs):
            commands.append(command)
            process = _FakeProcess()
            processes.append(process)
            return process

        choices = {**self.tools, "swaybg": "/usr/bin/swaybg", "mako": "/usr/bin/mako",
                   "lxpolkit": "/usr/bin/lxpolkit", "swayidle": "/usr/bin/swayidle"}
        env = {"RICEBOWL_DE_SHELL_CHILD": "1", "RICEBOWL_DE_NESTED": "1",
               "WAYLAND_DISPLAY": "wayland-0"}
        with mock.patch("macrice.de.session.signal.signal"):
            result = session.shell(environment=env, which=choices.get, spawn=spawn)
        self.assertEqual(result, 0)
        self.assertIn(["/usr/bin/mako", "--config",
                       str(session.resources() / "mako.conf")], commands)
        self.assertIn("--config", commands[-1])
        self.assertIn(str(session.resources() / "waybar/config.jsonc"), commands[-1])
        self.assertFalse(any(command[0] == "/usr/bin/swayidle" for command in commands))
        self.assertTrue(all(proc.terminated for proc in processes[:-1]))

    def test_full_session_starts_before_sleep_lock_listener(self):
        commands = []
        def spawn(command, **_kwargs):
            commands.append(command)
            return _FakeProcess()
        env = {"RICEBOWL_DE_SHELL_CHILD": "1", "RICEBOWL_DE_NESTED": "0",
               "WAYLAND_DISPLAY": "wayland-0"}
        with mock.patch("macrice.de.session.signal.signal"):
            self.assertEqual(session.shell(environment=env, which=self.which,
                                           spawn=spawn), 0)
        idle = next(command for command in commands if command[0] == "/usr/bin/swayidle")
        lock = shlex.join([session.sys.executable,
                           str(session.project_root() / "launcher.py"), "de", "lock"])
        self.assertEqual(idle, ["/usr/bin/swayidle", "-w", "timeout", "600",
                                lock, "before-sleep", lock, "lock", lock])

    def test_idle_lock_watcher_crash_stops_live_session_instead_of_rescuing(self):
        commands = []
        panel = _FakeProcess()
        class DeadIdle(_FakeProcess):
            def poll(self):
                return 6
        def spawn(command, **_kwargs):
            commands.append(command)
            return DeadIdle() if command[0] == "/usr/bin/swayidle" else panel
        env = {"RICEBOWL_DE_SHELL_CHILD": "1", "RICEBOWL_DE_NESTED": "0",
               "RICEBOWL_DE_LIVE": "1", "WAYLAND_DISPLAY": "wayland-0"}
        with mock.patch("macrice.de.session.signal.signal"), \
             mock.patch("macrice.de.live.listen", return_value=nullcontext(object())), \
             mock.patch("macrice.de.session._LiveSwitch") as live, \
             mock.patch("sys.stderr"):
            live.return_value.panel = panel
            self.assertEqual(session.shell(environment=env, which=self.which,
                                           spawn=spawn), 1)
        self.assertTrue(panel.terminated)
        self.assertEqual(sum(command[0] == "/usr/bin/waybar" for command in commands), 1)

    def test_native_idle_guard_failure_never_starts_insecure_waybar_rescue(self):
        commands = []
        panel = _FakeProcess()
        class DeadIdle(_FakeProcess):
            def poll(self):
                return 9
        def spawn(command, **_kwargs):
            commands.append(command)
            return DeadIdle() if command[0] == "/usr/bin/swayidle" else panel
        env = {"RICEBOWL_DE_SHELL_CHILD": "1", "RICEBOWL_DE_NESTED": "0",
               "RICEBOWL_DE_PANEL": "native", "RICEBOWL_DE_LIVE": "1",
               "WAYLAND_DISPLAY": "wayland-0"}
        tools = {**self.tools, "riceplate-native": "/usr/bin/riceplate-native"}
        with mock.patch("macrice.de.session.signal.signal"), \
             mock.patch("macrice.de.live.listen", return_value=nullcontext(object())), \
             mock.patch("macrice.de.session._LiveSwitch") as live, \
             mock.patch("sys.stderr"):
            live.return_value.panel = panel
            self.assertEqual(session.shell(environment=env, which=tools.get,
                                           spawn=spawn), 1)
        self.assertTrue(panel.terminated)
        self.assertEqual([cmd[0] for cmd in commands],
                         ["/usr/bin/swayidle", "/usr/bin/riceplate-native"])

    def test_resume_rechecks_waybar_outputs_once_without_restarting_unmodified_panel(self):
        commands = []
        class MultipleTicks(_FakeProcess):
            calls = 0
            def poll(self):
                self.calls += 1
                return 0 if self.calls >= 5 else None
        panel = MultipleTicks()
        def spawn(command, **_kwargs):
            commands.append(command)
            return _FakeProcess() if command[0] == "/usr/bin/swayidle" else panel
        env = {"RICEBOWL_DE_SHELL_CHILD": "1", "RICEBOWL_DE_NESTED": "0",
               "RICEBOWL_DE_LIVE": "1", "WAYLAND_DISPLAY": "wayland-0"}
        times = iter([float(t) for t in range(20)])
        with mock.patch("macrice.de.session.signal.signal"), \
             mock.patch("macrice.de.live.listen", return_value=nullcontext(object())), \
             mock.patch("macrice.de.live.serve_once"), \
             mock.patch("macrice.de.session._LiveSwitch") as live, \
             mock.patch("macrice.de.session._ResumeGap") as gap, \
             mock.patch("macrice.de.session._refresh_changed_outputs",
                        return_value=("classic", "new-layout")) as refresh, \
             mock.patch("macrice.de.session.time.monotonic",
                        side_effect=lambda: next(times)):
            live.return_value.panel = panel
            live.return_value.active = "classic"
            live.return_value.fallback = False
            gap.return_value.resumed.side_effect = [True] + [False] * 19
            self.assertEqual(session.shell(environment=env, which=self.which,
                                           spawn=spawn), 0)
        refresh.assert_called_once()
        self.assertEqual(refresh.call_args.args[1][0], "classic")
        self.assertEqual([cmd[0] for cmd in commands],
                         ["/usr/bin/swayidle", "/usr/bin/waybar"])

    def test_orca_is_opt_in_only_for_full_ricebowl_sessions(self):
        commands = []
        def spawn(command, **_kwargs):
            commands.append(command)
            return _FakeProcess()

        tools = {**self.tools, "orca": "/usr/bin/orca"}
        env = {"RICEBOWL_DE_SHELL_CHILD": "1", "WAYLAND_DISPLAY": "wayland-0",
               "RICEBOWL_DE_SCREEN_READER": "1", "RICEBOWL_DE_NESTED": "0"}
        with mock.patch("macrice.de.session.signal.signal"):
            self.assertEqual(session.shell(environment=env, which=tools.get, spawn=spawn), 0)
        self.assertIn(["/usr/bin/orca"], commands)
        commands.clear()
        with mock.patch("macrice.de.session.signal.signal"):
            self.assertEqual(session.shell(environment={**env, "RICEBOWL_DE_NESTED": "1"},
                                           which=tools.get, spawn=spawn), 0)
        self.assertNotIn(["/usr/bin/orca"], commands)

    def test_native_panel_runs_without_waybar_when_it_exits_cleanly(self):
        commands = []

        def spawn(command, **_kwargs):
            commands.append(command)
            return _FakeProcess()

        env = {"RICEBOWL_DE_SHELL_CHILD": "1", "RICEBOWL_DE_NESTED": "1",
               "RICEBOWL_DE_PANEL": "native", "RICEBOWL_DE_RECIPE": "chrome",
               "WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": self.runtime.name}
        tools = {**self.tools, "riceplate-native": "/usr/bin/riceplate-native"}
        with mock.patch("macrice.de.session.signal.signal"):
            self.assertEqual(session.shell(environment=env, which=tools.get, spawn=spawn), 0)
        self.assertEqual(commands, [["/usr/bin/riceplate-native", "--recipe", "chrome"]])

    def test_native_crash_restores_waybar_instead_of_exiting_the_session(self):
        commands = []

        class FailedNative(_FakeProcess):
            def wait(self, timeout=None):
                return -11

        def spawn(command, **_kwargs):
            commands.append(command)
            if command[0] == "/usr/bin/riceplate-native":
                return FailedNative()
            return _FakeProcess()

        env = {"RICEBOWL_DE_SHELL_CHILD": "1", "RICEBOWL_DE_NESTED": "1",
               "RICEBOWL_DE_PANEL": "native", "WAYLAND_DISPLAY": "wayland-0"}
        tools = {**self.tools, "riceplate-native": "/usr/bin/riceplate-native"}
        with mock.patch("macrice.de.session.signal.signal"), \
             mock.patch("sys.stderr"):
            self.assertEqual(session.shell(environment=env, which=tools.get, spawn=spawn), 0)
        self.assertEqual(commands[0], ["/usr/bin/riceplate-native", "--recipe", "classic"])
        self.assertEqual(commands[1][0], "/usr/bin/waybar")

    def test_live_waybar_crash_rescues_once_without_touching_saved_selection(self):
        from macrice.de import recipes

        commands = []
        handlers = {}
        panels = 0

        class FailedWaybar(_FakeProcess):
            def poll(self):
                return 9

            def wait(self, timeout=None):
                return 9

        def spawn(command, **_kwargs):
            nonlocal panels
            commands.append(command)
            if command[0] == "/usr/bin/waybar":
                panels += 1
                return FailedWaybar() if panels == 1 else _FakeProcess()
            return _FakeProcess()

        def stop_after_rescue(listener, handler):
            handlers[signal.SIGTERM](signal.SIGTERM, None)

        env = {"RICEBOWL_DE_SHELL_CHILD": "1", "RICEBOWL_DE_NESTED": "1",
               "RICEBOWL_DE_PANEL": "waybar", "RICEBOWL_DE_LIVE": "1",
               "RICEBOWL_DE_RECIPE": "classic", "WAYLAND_DISPLAY": "wayland-0",
               "XDG_RUNTIME_DIR": self.runtime.name,
               "RICEBOWL_DE_SESSION_CONFIG": self.runtime.name}
        with mock.patch("macrice.de.session.signal.signal", side_effect=handlers.__setitem__), \
             mock.patch("macrice.de.live.listen", return_value=nullcontext(object())), \
             mock.patch("macrice.de.live.serve_once", side_effect=stop_after_rescue), \
             mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.runtime.name}), \
             mock.patch("macrice.de.session.time.sleep"):
            self.assertEqual(session.shell(environment=env, which=self.which, spawn=spawn), 0)
            self.assertEqual(recipes.current_selection()[0], "classic")
        self.assertEqual(panels, 2)

    def test_failed_waybar_rescue_does_not_restart_forever(self):
        commands = []

        class FailedWaybar(_FakeProcess):
            def poll(self):
                return 9

            def wait(self, timeout=None):
                return 9

        def spawn(command, **_kwargs):
            commands.append(command)
            return FailedWaybar()

        env = {"RICEBOWL_DE_SHELL_CHILD": "1", "RICEBOWL_DE_NESTED": "1",
               "RICEBOWL_DE_PANEL": "waybar", "RICEBOWL_DE_LIVE": "1",
               "RICEBOWL_DE_RECIPE": "classic", "WAYLAND_DISPLAY": "wayland-0",
               "XDG_RUNTIME_DIR": self.runtime.name,
               "RICEBOWL_DE_SESSION_CONFIG": self.runtime.name}
        with mock.patch("macrice.de.live.listen", return_value=nullcontext(object())), \
             mock.patch("macrice.de.session.signal.signal"), \
             mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.runtime.name}), \
             mock.patch("macrice.de.session.time.sleep"):
            self.assertEqual(session.shell(environment=env, which=self.which, spawn=spawn), 9)
        self.assertEqual(len([cmd for cmd in commands if cmd[0] == "/usr/bin/waybar"]), 2)

    def test_native_live_rescue_attempt_is_not_repeated_by_outer_fallback(self):
        commands = []

        class FailedPanel(_FakeProcess):
            def poll(self):
                return 9

            def wait(self, timeout=None):
                return 9

        def spawn(command, **_kwargs):
            commands.append(command)
            return FailedPanel()

        env = {"RICEBOWL_DE_SHELL_CHILD": "1", "RICEBOWL_DE_NESTED": "1",
               "RICEBOWL_DE_PANEL": "native", "RICEBOWL_DE_LIVE": "1",
               "RICEBOWL_DE_RECIPE": "classic", "WAYLAND_DISPLAY": "wayland-0",
               "XDG_RUNTIME_DIR": self.runtime.name,
               "RICEBOWL_DE_SESSION_CONFIG": self.runtime.name}
        tools = {**self.tools, "riceplate-native": "/usr/bin/riceplate-native"}
        with mock.patch("macrice.de.live.listen", return_value=nullcontext(object())), \
             mock.patch("macrice.de.session.signal.signal"), \
             mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.runtime.name}), \
             mock.patch("macrice.de.session.time.sleep"):
            self.assertEqual(session.shell(environment=env, which=tools.get, spawn=spawn), 9)
        self.assertEqual([command[0] for command in commands],
                         ["/usr/bin/riceplate-native", "/usr/bin/waybar"])

    def test_native_launch_failure_restores_waybar(self):
        commands = []

        def spawn(command, **_kwargs):
            commands.append(command)
            if command[0] == "/usr/bin/riceplate-native":
                raise OSError("missing library")
            return _FakeProcess()

        env = {"RICEBOWL_DE_SHELL_CHILD": "1", "RICEBOWL_DE_NESTED": "1",
               "RICEBOWL_DE_PANEL": "native", "WAYLAND_DISPLAY": "wayland-0"}
        tools = {**self.tools, "riceplate-native": "/usr/bin/riceplate-native"}
        with mock.patch("macrice.de.session.signal.signal"), \
             mock.patch("sys.stderr"):
            self.assertEqual(session.shell(environment=env, which=tools.get, spawn=spawn), 0)
        self.assertEqual(commands[-1][0], "/usr/bin/waybar")

    def test_native_user_shutdown_never_restarts_waybar(self):
        handlers = {}
        commands = []

        class StoppingNative(_FakeProcess):
            def wait(self, timeout=None):
                if self.terminated:
                    return -15
                handlers[signal.SIGTERM](signal.SIGTERM, None)
                return -15

        def spawn(command, **_kwargs):
            commands.append(command)
            return StoppingNative()

        env = {"RICEBOWL_DE_SHELL_CHILD": "1", "RICEBOWL_DE_NESTED": "1",
               "RICEBOWL_DE_PANEL": "native", "WAYLAND_DISPLAY": "wayland-0"}
        tools = {**self.tools, "riceplate-native": "/usr/bin/riceplate-native"}
        with mock.patch("macrice.de.session.signal.signal", side_effect=handlers.__setitem__):
            self.assertEqual(session.shell(environment=env, which=tools.get, spawn=spawn), -15)
        self.assertEqual(len(commands), 1)

    def test_shutdown_during_native_spawn_cleans_up_without_starting_waybar(self):
        handlers = {}
        commands = []
        process = _FakeProcess()

        def spawn(command, **_kwargs):
            commands.append(command)
            handlers[signal.SIGINT](signal.SIGINT, None)
            return process

        env = {"RICEBOWL_DE_SHELL_CHILD": "1", "RICEBOWL_DE_NESTED": "1",
               "RICEBOWL_DE_PANEL": "native", "WAYLAND_DISPLAY": "wayland-0"}
        tools = {**self.tools, "riceplate-native": "/usr/bin/riceplate-native"}
        with mock.patch("macrice.de.session.signal.signal", side_effect=handlers.__setitem__):
            self.assertEqual(session.shell(environment=env, which=tools.get, spawn=spawn), 130)
        self.assertEqual(len(commands), 1)
        self.assertTrue(process.terminated)

    def test_failed_panel_start_cleans_up_background_services(self):
        processes = []

        def spawn(command, **_kwargs):
            if command[0] == "/usr/bin/waybar":
                raise OSError("panel unavailable")
            process = _FakeProcess()
            processes.append(process)
            return process

        env = {"RICEBOWL_DE_SHELL_CHILD": "1", "RICEBOWL_DE_NESTED": "0",
               "WAYLAND_DISPLAY": "wayland-0"}
        choices = {**self.tools, "swaybg": "/usr/bin/swaybg", "swayidle": "/usr/bin/swayidle"}
        with self.assertRaisesRegex(OSError, "panel unavailable"):
            session.shell(environment=env, which=choices.get, spawn=spawn)
        self.assertTrue(processes)
        self.assertTrue(all(process.terminated for process in processes))

    def test_bundled_labwc_keybindings_are_valid_xml(self):
        config = ET.parse(session.resources() / "labwc/rc.xml")
        self.assertEqual(config.getroot().tag, "labwc_config")
        commands = [item.get("command") for item in config.findall(".//action")]
        self.assertIn("ricebowl de lock", commands)
        self.assertIn("foot", commands)
        keybindings = {
            key.get("key"): key.find("action").get("command")
            for key in config.findall(".//keyboard/keybind")
        }
        self.assertEqual(keybindings["XF86AudioRaiseVolume"],
                         "wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%+ --limit 1.0")
        self.assertEqual(keybindings["XF86AudioLowerVolume"],
                         "wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-")
        self.assertEqual(keybindings["XF86AudioMute"],
                         "wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle")
        self.assertEqual(keybindings["XF86MonBrightnessUp"],
                         "brightnessctl --class=backlight set 5%+")
        self.assertEqual(keybindings["XF86MonBrightnessDown"],
                         "brightnessctl --class=backlight set 5%-")
        self.assertEqual(keybindings["Print"], "ricebowl de shot --clipboard")
        self.assertEqual(keybindings["S-Print"],
                         "ricebowl de shot --shot-mode region --clipboard")
        self.assertEqual(len(keybindings), len(config.findall(".//keyboard/keybind")))

    def test_root_menu_has_terminal_and_safe_logout(self):
        menu = ET.parse(session.resources() / "labwc/menu.xml").getroot()
        self.assertEqual(menu.tag, "openbox_menu")
        self.assertEqual(menu.find(".//menu").get("id"), "root-menu")
        self.assertIsNotNone(menu.find(".//action[@name='Exit']"))
        self.assertIsNotNone(menu.find(".//action[@command='foot']"))


if __name__ == "__main__":
    unittest.main()
