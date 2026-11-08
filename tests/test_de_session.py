"""Session safety: login, nested mode, sandboxed config and supervised clients."""

import os
import json
import shlex
import signal
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from macrice.de import session


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
        self.tools = {name: f"/usr/bin/{name}" for name in (*session.REQUIRED_TOOLS, "dbus-run-session")}

    def which(self, command):
        return self.tools.get(command)

    @mock.patch("macrice.de.session.os.geteuid", return_value=1000)
    @mock.patch("macrice.de.session._check_runtime_dir")
    def test_nested_exec_uses_isolated_config_and_preserves_parent_bus(self, _runtime, _uid):
        env = {**self.env, "DISPLAY": ":0", "XDG_CURRENT_DESKTOP": "XFCE"}
        with self.assertRaises(_ExecCalled) as caught:
            session.start(nested=True, environment=env, which=self.which, execute=_record_exec)
        call = caught.exception
        self.assertEqual(call.program, "/usr/bin/labwc")
        self.assertIn("--config-dir", call.argv)
        self.assertEqual(call.argv[call.argv.index("--config-dir") + 1],
                         str(session.resources() / "labwc"))
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

    def test_missing_tool_fails_before_starting_compositor(self):
        with self.assertRaisesRegex(session.SessionError, "Missing Wayland preview dependencies: foot"):
            session.start(environment=self.env, which=lambda name: None if name == "foot"
                          else self.which(name), execute=_record_exec)

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
        self.assertIn("--config", commands[-1])
        self.assertIn(str(session.resources() / "waybar/config.jsonc"), commands[-1])
        self.assertFalse(any(command[0] == "/usr/bin/swayidle" for command in commands))
        self.assertTrue(all(proc.terminated for proc in processes[:-1]))

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
        self.assertIn("swaylock -f", commands)
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

    def test_root_menu_has_terminal_and_safe_logout(self):
        menu = ET.parse(session.resources() / "labwc/menu.xml").getroot()
        self.assertEqual(menu.tag, "openbox_menu")
        self.assertEqual(menu.find(".//menu").get("id"), "root-menu")
        self.assertIsNotNone(menu.find(".//action[@name='Exit']"))
        self.assertIsNotNone(menu.find(".//action[@command='foot']"))


if __name__ == "__main__":
    unittest.main()
