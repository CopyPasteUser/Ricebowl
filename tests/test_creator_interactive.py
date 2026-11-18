"""The Creator's interactive nested window is never an installed/live apply."""

import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from macrice.de import creator_interactive as interactive
from macrice.de import creator_workspace as workspace, recipes


class CreatorInteractiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for name in ("runtime", "config", "state"):
            (root / name).mkdir(mode=0o700)
        self.environment = {
            "DISPLAY": ":88", "XDG_RUNTIME_DIR": str(root / "runtime"),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_STATE_HOME": str(root / "state"),
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent-test-bus",
            "RICEBOWL_DE_SHELL_CHILD": "1", "WLR_BACKENDS": "headless",
        }
        patch = mock.patch.dict(os.environ, self.environment)
        patch.start()
        self.addCleanup(patch.stop)
        self.draft = workspace.create_draft("heritage")

    @staticmethod
    def all_tools(_name):
        return "/usr/bin/tool"

    def test_nested_preview_uses_fixed_argv_and_leaves_selection_untouched(self):
        captured = {}
        completed = threading.Event()
        outcome = []

        def spawn(argv, **kwargs):
            captured.update(argv=argv, options=kwargs)
            return subprocess.Popen([sys.executable, "-c",
                                     "import sys;sys.stderr.write('nested failed\\n');sys.exit(3)"],
                                    **kwargs)

        original = recipes.current_selection()
        run = interactive.launch(self.draft, lambda _run, result: (
            outcome.append(result), completed.set()),
            environment=self.environment, which=self.all_tools, spawn=spawn)
        self.assertTrue(completed.wait(8), "Nested process did not report completion")
        self.assertEqual(outcome[0].exit_code, 3)
        self.assertIn("nested failed", outcome[0].diagnostic)
        self.assertFalse(outcome[0].stopped_by_user)
        self.assertEqual(captured["argv"][-7:],
                         ["de", "start", "--nested", "--panel", "native", "--recipe",
                          str(self.draft.path)])
        self.assertEqual(captured["options"]["start_new_session"], True)
        self.assertNotIn("shell", captured["options"])
        self.assertNotIn("WLR_BACKENDS", captured["options"]["env"])
        self.assertNotIn("RICEBOWL_DE_SHELL_CHILD", captured["options"]["env"])
        self.assertEqual(run.draft.semantic_sha256, self.draft.semantic_sha256)
        self.assertEqual(recipes.current_selection(), original)

    def test_close_terminates_without_touching_selection(self):
        completed = threading.Event()
        outcomes = []

        def spawn(_argv, **kwargs):
            return subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"],
                                    **kwargs)

        run = interactive.launch(self.draft, lambda _run, result: (
            outcomes.append(result), completed.set()), environment=self.environment,
            which=self.all_tools, spawn=spawn)
        run.stop()
        run.stop()  # Repeated clicks must not start duplicate teardown.
        self.assertTrue(completed.wait(8), "Preview stop failed to reap its child")
        self.assertTrue(outcomes[0].stopped_by_user)
        self.assertNotEqual(outcomes[0].exit_code, 0)
        self.assertEqual(recipes.current_selection(), ("classic", None))

    def test_unresponsive_test_process_is_force_stopped(self):
        marker = Path(self.environment["XDG_RUNTIME_DIR"]) / "preview-ready"
        completed = threading.Event()
        outcomes = []

        def spawn(_argv, **kwargs):
            code = ("import pathlib,signal,time;"
                    "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                    f"pathlib.Path({str(marker)!r}).write_text('ready');"
                    "time.sleep(30)")
            return subprocess.Popen([sys.executable, "-c", code], **kwargs)

        run = interactive.launch(self.draft, lambda _run, result: (
            outcomes.append(result), completed.set()), environment=self.environment,
            which=self.all_tools, spawn=spawn)
        deadline = time.monotonic() + 3
        while not marker.is_file() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(marker.is_file(), "Test process did not install its TERM handler")
        with mock.patch.object(interactive, "_STOP_GRACE_SECONDS", 0.2):
            run.stop()
            self.assertTrue(completed.wait(4), "Unresponsive compositor was not reaped")
        self.assertEqual(outcomes[0].exit_code, -signal.SIGKILL)
        self.assertTrue(outcomes[0].stopped_by_user)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux process groups required")
    def test_early_wrapper_exit_reaps_orphan_that_ignores_term(self):
        # An interactive preview can lose its wrapper while labwc/DBus
        # descendants keep the inherited stderr pipe open. The wrapper's
        # zero exit code must not leave that private session running.
        marker = Path(self.environment["XDG_RUNTIME_DIR"]) / "grandchild-pid"
        completed = threading.Event()
        outcomes = []

        child = (
            "import os,pathlib,signal,time;"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
            f"pathlib.Path({str(marker)!r}).write_text(str(os.getpid()));"
            "time.sleep(30)"
        )

        def spawn(_argv, **kwargs):
            wrapper = (
                "import subprocess,sys,time;"
                f"subprocess.Popen([sys.executable,'-c',{child!r}],"
                " stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL);"
                "time.sleep(0.3)"
            )
            return subprocess.Popen([sys.executable, "-c", wrapper], **kwargs)

        with mock.patch.object(interactive, "_STOP_GRACE_SECONDS", 0.2):
            run = interactive.launch(self.draft, lambda _run, result: (
                outcomes.append(result), completed.set()),
                environment=self.environment, which=self.all_tools, spawn=spawn)
            pid = None
            try:
                deadline = time.monotonic() + 4
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(marker.is_file(), "Grandchild did not start")
                pid = int(marker.read_text())
                self.assertTrue(completed.wait(8), "Exited wrapper was not observed")
                self.assertEqual(outcomes[0].exit_code, 0)
                self.assertFalse(outcomes[0].stopped_by_user)

                # A zombie already terminated by SIGKILL is accepted because
                # PID 1 in some CI containers may not reap it immediately.
                def running() -> bool:
                    try:
                        status = Path(f"/proc/{pid}/stat").read_text()
                    except FileNotFoundError:
                        return False
                    return status.split(") ", 1)[1].split(" ", 1)[0] != "Z"

                deadline = time.monotonic() + 3
                while running() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertFalse(running(), "Orphaned nested preview child survived")
                self.assertEqual(recipes.current_selection(), ("classic", None))
            finally:
                # Protect CI if the regression returns and leaves a child.
                run.stop()
                if pid is not None:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_missing_display_and_dependencies_fail_before_spawn(self):
        with mock.patch.object(interactive.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(interactive.InteractivePreviewError, "graphical"):
                interactive.launch(self.draft, lambda *_: None,
                                   environment={k: v for k, v in self.environment.items()
                                                if k != "DISPLAY"}, which=self.all_tools)
            with self.assertRaisesRegex(interactive.InteractivePreviewError, "riceplate-native"):
                interactive.launch(self.draft, lambda *_: None,
                                   environment=self.environment,
                                   which=lambda name: None if name == "riceplate-native" else "/bin/true")
            spawn.assert_not_called()

    def test_stale_draft_and_unsafe_runtime_never_start(self):
        with mock.patch.object(interactive.subprocess, "Popen") as spawn:
            os.chmod(self.environment["XDG_RUNTIME_DIR"], 0o755)
            with self.assertRaisesRegex(interactive.InteractivePreviewError, "owner-only"):
                interactive.launch(self.draft, lambda *_: None,
                                   environment=self.environment, which=self.all_tools)
            os.chmod(self.environment["XDG_RUNTIME_DIR"], 0o700)
            self.draft.path.write_text(self.draft.path.read_text().replace(
                "Heritage Modern draft", "Changed outside Creator"))
            with self.assertRaisesRegex(interactive.InteractivePreviewError, "changed"):
                interactive.launch(self.draft, lambda *_: None,
                                   environment=self.environment, which=self.all_tools)
            spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
