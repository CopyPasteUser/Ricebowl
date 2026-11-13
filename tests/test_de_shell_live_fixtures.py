"""Two distinct shell recipes exercise the actual supervisor transaction.

Process spawning/labwc reconfiguration is mocked; this is not a physical
compositor, screenshot or hardware integration claim.
"""
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from macrice.de import live, live_recovery, recipes, staging
from macrice.de.session import _LiveSwitch, resources

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "wayland"

class Process:
    def __init__(self, exit_code=None):
        self.exit_code = exit_code
        self.terminated = False
    def poll(self):
        return 0 if self.terminated else self.exit_code
    def terminate(self):
        self.terminated = True
    def kill(self):
        self.terminated = True
    def wait(self, timeout=None):
        return 0 if self.terminated else (self.exit_code or 0)

class LiveFixtureTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="ricebowl-shell-live-")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        config = root / "config"
        config.mkdir(mode=0o700)
        runtime = root / "runtime"
        runtime.mkdir(mode=0o700)
        session_root = runtime / "ricebowl-labwc-test"
        session_root.mkdir(mode=0o700)
        self.menu = session_root / "menu.xml"
        self.menu.write_text((resources() / "labwc/menu.xml").read_text())
        self.rc = session_root / "rc.xml"
        self.rc.write_text((resources() / "labwc/rc.xml").read_text())
        patch = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)})
        patch.start()
        self.addCleanup(patch.stop)
        self.cleanup_stack = ExitStack()
        self.addCleanup(self.cleanup_stack.close)
        self.tools = {name: f"/usr/bin/{name}" for name in
                      ("labwc","swaybg","riceplate-native","waybar")}
        self.starts = []
        self.fail_panel = False

        def spawn(command, **kwargs):
            failure = self.fail_panel and command[0].endswith("riceplate-native")
            proc = Process(1 if failure else None)
            self.starts.append((command, kwargs, proc))
            return proc

        self.old_panel = Process()
        self.old_background = Process()
        self.controller = _LiveSwitch(
            env={"XDG_RUNTIME_DIR": str(runtime),
                 "RICEBOWL_DE_SESSION_CONFIG": str(session_root),
                 "RICEBOWL_DE_RECIPE": "classic",
                 "WAYLAND_DISPLAY": "wayland-19"},
            mode="native", which=self.tools.get, spawn=spawn,
            cleanup=self.cleanup_stack, initial_panel=self.old_panel,
            initial_wallpaper=self.old_background,
            background=[self.old_background],
        )
        configure = mock.patch.object(self.controller, "_reconfigure")
        configure.start()
        self.addCleanup(configure.stop)
        sleep = mock.patch("macrice.de.session.time.sleep")
        sleep.start()
        self.addCleanup(sleep.stop)
        for name in ("test-taskbar-shell","test-dock-shell"):
            result, _path = recipes.import_recipe(EXAMPLES / f"{name}.json")
            self.assertEqual(result.recipe_id, name)

    def apply(self, name, expected):
        return self.controller.handle({"action":"apply", "recipe":name,
            "sha256":staging._hash(name), "expected":expected})

    def test_both_compositions_use_same_live_supervisor_and_restore(self):
        a,b = "test-taskbar-shell","test-dock-shell"
        one = self.apply(a, "classic")
        self.assertTrue(one["changed"])
        self.assertEqual(recipes.current_selection(), (a,"classic"))
        two = self.apply(b, a)
        self.assertTrue(two["changed"])
        self.assertEqual(recipes.current_selection(), (b,a))
        self.assertTrue(self.old_panel.terminated)
        self.assertTrue(self.old_background.terminated)
        self.assertTrue(any(cmd[0].endswith("riceplate-native") for cmd,_,_ in self.starts))
        restored = self.controller.handle({"action":"restore", "recipe":None,
                                           "sha256":None, "expected":b})
        self.assertEqual(restored["active"], a)
        self.assertEqual(recipes.current_selection(), (a,b))
        self.assertIsNone(live_recovery.read())

    def test_failed_dock_spawn_preserves_active_taskbar_recipe(self):
        a,b = "test-taskbar-shell","test-dock-shell"
        self.apply(a, "classic")
        prior_selection = recipes._selection_snapshot()
        prior_menu = self.menu.read_bytes()
        self.fail_panel = True
        with self.assertRaises(live.LiveError):
            self.apply(b, a)
        self.assertEqual(recipes._selection_snapshot(), prior_selection)
        self.assertEqual(self.menu.read_bytes(), prior_menu)
        self.assertIsNone(live_recovery.read())

if __name__ == "__main__":
    unittest.main()
