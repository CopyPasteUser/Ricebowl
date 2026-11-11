"""Creator → installed recipe → real private Wayland socket → live/restore.

The labwc child processes are controlled fakes: this verifies the actual
application and supervisor protocols, transaction/selection state and cleanup,
not visual or physical input readiness (those need real hardware acceptance).
"""

import os
import subprocess
import tempfile
import threading
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from macrice.de import creator_activation as activation
from macrice.de import creator_workspace as workspace, live, recipes, staging
from macrice.de import live_recovery, riceprofile
from macrice.de.session import _LiveSwitch, resources


class Process:
    def __init__(self):
        self.stopped = False

    def poll(self):
        return 0 if self.stopped else None

    def terminate(self):
        self.stopped = True

    def kill(self):
        self.stopped = True

    def wait(self, timeout=None):
        return 0


class WaylandCreatorEndToEndTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.runtime = root / "runtime"
        self.config = root / "config"
        self.state = root / "state"
        self.menu_dir = root / "session"
        for directory in (self.runtime, self.config, self.state, self.menu_dir):
            directory.mkdir(mode=0o700)
        self.menu = self.menu_dir / "menu.xml"
        self.menu.write_bytes((resources() / "labwc/menu.xml").read_bytes())
        self.env = {
            "XDG_RUNTIME_DIR": str(self.runtime),
            "WAYLAND_DISPLAY": "wayland-creator-qa",
            "XDG_CONFIG_HOME": str(self.config),
            "XDG_STATE_HOME": str(self.state),
            "RICEBOWL_DE_SESSION_CONFIG": str(self.menu_dir),
            "RICEBOWL_DE_RECIPE": "classic",
        }
        env_patch = mock.patch.dict(os.environ, self.env)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.cleanup_stack = ExitStack()
        self.addCleanup(self.cleanup_stack.close)
        self.old_panel, self.old_wallpaper = Process(), Process()
        self.background = [self.old_wallpaper]
        self.commands = []
        self.spawned = []
        self.missing_tool = None

        def which(name):
            return None if name == self.missing_tool else "/usr/bin/" + name

        def spawn(command, **_kwargs):
            self.commands.append(command)
            process = Process()
            self.spawned.append(process)
            return process

        self.supervisor = _LiveSwitch(
            env=self.env, mode="native", which=which, spawn=spawn,
            cleanup=self.cleanup_stack, initial_panel=self.old_panel,
            initial_wallpaper=self.old_wallpaper, background=self.background,
        )
        sleep = mock.patch("macrice.de.session.time.sleep", return_value=None)
        reconfigure = mock.patch.object(self.supervisor, "_reconfigure")
        for patch in (sleep, reconfigure):
            patch.start()
            self.addCleanup(patch.stop)

    @contextmanager
    def server(self):
        try:
            context = live.listen(self.env)
            listener = context.__enter__()
        except PermissionError:
            if os.environ.get("GITHUB_ACTIONS") == "true":
                self.fail("GitHub CI must exercise the real private Wayland socket")
            # The local managed sandbox can deny AF_UNIX creation. Keep the
            # full Creator/controller integration covered here by using the
            # exact protocol handler; CI additionally validates the socket.
            def direct(action, *, recipe=None, sha256=None, expected=None, environment=None):
                try:
                    return self.supervisor.handle({
                        "action": action, "recipe": recipe,
                        "sha256": sha256, "expected": expected,
                    })
                except live.LiveError as exc:
                    return {"version": 1, "ok": False, "error": {
                        "code": exc.code, "message": str(exc),
                    }}

            with mock.patch.object(live, "request", side_effect=direct):
                yield
            return
        stop = threading.Event()

        def serve():
            while not stop.is_set():
                live.serve_once(listener, self.supervisor.handle, timeout=0.02)

        worker = threading.Thread(target=serve, name="wayland-creator-e2e-server")
        worker.start()
        try:
            yield
        finally:
            stop.set()
            worker.join(timeout=3)
            context.__exit__(None, None, None)
            self.assertFalse(worker.is_alive(), "Supervisor thread leaked")
            self.assertFalse(live.socket_path(self.env).exists(), "Owner socket leaked")

    def test_two_distinct_drafts_install_switch_restore_and_preserve_host(self):
        before_menu = self.menu.read_bytes()
        host_marker = self.state / "untouched-xfce-session"
        host_marker.write_text("XFCE session must not change")
        heritage = workspace.create_draft("heritage")
        orbit = workspace.create_draft("orbit")
        self.assertNotEqual(recipes.load(str(heritage.path)).layout,
                            recipes.load(str(orbit.path)).layout)
        self.assertEqual(recipes.current_selection(), ("classic", None))
        for draft in (heritage, orbit):
            self.assertTrue(activation.install(activation.inspect_install(draft)))
            self.assertEqual(recipes.current_selection(), ("classic", None))
        with self.server():
            for draft, previous in ((heritage, "classic"), (orbit, heritage.recipe_id)):
                plan = activation.inspect_live(draft)
                self.assertEqual(plan.expected_active, previous)
                self.assertTrue(plan.next_login_persisted)
                receipt = activation.apply_live(plan)
                self.assertTrue(receipt["changed"])
                self.assertEqual(receipt["semantic_sha256"], draft.semantic_sha256)
                self.assertEqual(receipt["previous"], previous)
                self.assertEqual(recipes.current_selection()[0], draft.recipe_id)
                self.assertEqual(staging._hash(draft.recipe_id), draft.semantic_sha256)
            restore_plan = activation.inspect_restore()
            self.assertEqual(restore_plan.previous, heritage.recipe_id)
            receipt = activation.restore_live(restore_plan)
            self.assertEqual(receipt["active"], heritage.recipe_id)
            self.assertEqual(recipes.current_selection()[0], heritage.recipe_id)
            self.assertEqual(self.supervisor.active, heritage.recipe_id)
        self.assertTrue(self.old_panel.stopped)
        self.assertTrue(self.old_wallpaper.stopped)
        self.assertEqual(len(self.background), 1)
        self.assertEqual(host_marker.read_text(), "XFCE session must not change")
        # The menu belongs only to this private opt-in labwc session.
        self.assertNotEqual(self.menu.read_bytes(), before_menu)
        self.assertTrue(all(command[0].startswith("/usr/bin/") for command in self.commands))

    def test_failed_wayland_component_keeps_earlier_live_session(self):
        draft = workspace.create_draft("orbit")
        activation.install(activation.inspect_install(draft))
        before_menu = self.menu.read_bytes()
        self.missing_tool = "swaybg"
        with self.server():
            plan = activation.inspect_live(draft)
            with self.assertRaisesRegex(activation.ActivationError, "Wallpaper component"):
                activation.apply_live(plan)
        self.assertEqual(self.commands, [])
        self.assertEqual(self.menu.read_bytes(), before_menu)
        self.assertEqual(recipes.current_selection(), ("classic", None))
        self.assertFalse(self.old_panel.stopped)
        self.assertFalse(self.old_wallpaper.stopped)

    def test_late_selection_failure_restores_entire_creator_switch_and_allows_retry(self):
        heritage = workspace.create_draft("heritage")
        orbit = workspace.create_draft("orbit")
        for draft in (heritage, orbit):
            activation.install(activation.inspect_install(draft))
        (self.menu_dir / ".ricebowl-managed").touch(mode=0o600)
        profile = riceprofile.ProfileSession.prepare(
            self.menu_dir, self.env, recipes.load("classic"),
            which=lambda name: name,
            run=lambda *args, **kwargs: SimpleNamespace(returncode=0))
        self.supervisor.profile = profile
        with self.server():
            activation.apply_live(activation.inspect_live(heritage))
            before_selection = recipes._selection_snapshot()
            before_menu = self.menu.read_bytes()
            chrome = self.menu_dir / "themerc-override"
            before_chrome = chrome.read_bytes() if chrome.exists() else None
            before_clients = {client: (self.menu_dir / client.filename).read_bytes()
                              for client in profile.clients}
            retained_panel, retained_wallpaper = self.supervisor.panel, self.supervisor.wallpaper
            old_change = recipes.change_selection

            def fail_after_commit(*args, **kwargs):
                old_change(*args, **kwargs)
                raise OSError("injected failure after committing next-login selection")

            with mock.patch.object(recipes, "change_selection", side_effect=fail_after_commit):
                with self.assertRaisesRegex(activation.ActivationError, "previous rice retained"):
                    activation.apply_live(activation.inspect_live(orbit))

            self.assertEqual(recipes._selection_snapshot(), before_selection)
            self.assertEqual(self.menu.read_bytes(), before_menu)
            self.assertEqual(chrome.read_bytes() if chrome.exists() else None, before_chrome)
            self.assertEqual({client: (self.menu_dir / client.filename).read_bytes()
                              for client in profile.clients}, before_clients)
            self.assertIs(self.supervisor.panel, retained_panel)
            self.assertIs(self.supervisor.wallpaper, retained_wallpaper)
            self.assertFalse(retained_panel.stopped)
            self.assertFalse(retained_wallpaper.stopped)
            self.assertTrue(all(proc.stopped for proc in self.spawned[-2:]))
            self.assertEqual(self.background, [retained_wallpaper])
            self.assertIsNone(live_recovery.read())
            self.assertEqual(self.supervisor.active, heritage.recipe_id)

            # Same reviewed draft must still be usable after *complete* rollback.
            switched = activation.apply_live(activation.inspect_live(orbit))
            self.assertEqual(switched["active"], orbit.recipe_id)
            self.assertEqual(switched["previous"], heritage.recipe_id)
            self.assertEqual(recipes.current_selection()[0], orbit.recipe_id)
            restored = activation.restore_live(activation.inspect_restore())
            self.assertEqual(restored["active"], heritage.recipe_id)
            self.assertIsNone(live_recovery.read())

    def test_failed_rollback_reconfigure_reports_unsafe_and_keeps_journal(self):
        draft = workspace.create_draft("orbit")
        activation.install(activation.inspect_install(draft))
        before_menu = self.menu.read_bytes()
        self.supervisor._reconfigure.side_effect = [
            subprocess.CalledProcessError(1, "labwc --reconfigure"),
            live.LiveError("labwc unavailable during rollback", code="component_unavailable"),
        ]
        with self.server():
            with self.assertRaisesRegex(activation.ActivationError, "recovery incomplete"):
                activation.apply_live(activation.inspect_live(draft))
            self.assertEqual(self.supervisor.active, "classic")
            self.assertEqual(recipes._selection_snapshot(), None)
            self.assertEqual(self.menu.read_bytes(), before_menu)
            self.assertFalse(self.old_panel.stopped)
            self.assertFalse(self.old_wallpaper.stopped)
            self.assertTrue(all(proc.stopped for proc in self.spawned))
            self.assertIsNotNone(live_recovery.read())
            # A new switch must not silently proceed while a rollback is unproven.
            self.supervisor._reconfigure.side_effect = None
            with self.assertRaisesRegex(activation.ActivationError, "requires recovery"):
                activation.apply_live(activation.inspect_live(draft))
            self.assertEqual(self.supervisor.active, "classic")
            with mock.patch.object(live_recovery, "_owner_running", return_value=False):
                self.assertEqual(live_recovery.reconcile()["status"], "unchanged")
            self.assertIsNone(live_recovery.read())
            self.assertEqual(activation.apply_live(activation.inspect_live(draft))["active"],
                             draft.recipe_id)

    def test_failed_explicit_restore_keeps_current_rice_until_retry(self):
        heritage = workspace.create_draft("heritage")
        orbit = workspace.create_draft("orbit")
        for draft in (heritage, orbit):
            activation.install(activation.inspect_install(draft))
        with self.server():
            activation.apply_live(activation.inspect_live(heritage))
            activation.apply_live(activation.inspect_live(orbit))
            plan = activation.inspect_restore()
            self.assertEqual((plan.expected_active, plan.previous),
                             (orbit.recipe_id, heritage.recipe_id))
            before_selection = recipes._selection_snapshot()
            before_menu = self.menu.read_bytes()
            before_panel, before_wallpaper = self.supervisor.panel, self.supervisor.wallpaper
            original_spawn = self.supervisor.spawn

            def die_on_new_panel(command, **kwargs):
                candidate = original_spawn(command, **kwargs)
                if command[0].endswith("riceplate-native"):
                    candidate.stopped = True
                return candidate

            with mock.patch.object(self.supervisor, "spawn", side_effect=die_on_new_panel):
                with self.assertRaisesRegex(activation.ActivationError, "component exited"):
                    activation.restore_live(plan)
            self.assertEqual(self.supervisor.active, orbit.recipe_id)
            self.assertEqual(recipes._selection_snapshot(), before_selection)
            self.assertEqual(self.menu.read_bytes(), before_menu)
            self.assertIs(self.supervisor.panel, before_panel)
            self.assertIs(self.supervisor.wallpaper, before_wallpaper)
            self.assertEqual(self.background, [before_wallpaper])
            self.assertFalse(before_panel.stopped)
            self.assertFalse(before_wallpaper.stopped)
            self.assertTrue(all(proc.stopped for proc in self.spawned[-2:]))
            self.assertIsNone(live_recovery.read())
            restored = activation.restore_live(plan)
            self.assertEqual(restored["active"], heritage.recipe_id)
            self.assertEqual(recipes.current_selection()[0], heritage.recipe_id)

    def test_stale_review_is_rejected_before_wayland_mutation(self):
        draft = workspace.create_draft("heritage")
        activation.install(activation.inspect_install(draft))
        before_menu = self.menu.read_bytes()
        with self.server():
            plan = activation.inspect_live(draft)
            # A competing next-login actor changed the selection while the
            # Creator confirmation was open. Live apply may not clobber it.
            staging.stage("chrome", staging._hash("chrome"), expected_active="classic")
            with self.assertRaisesRegex(activation.ActivationError, "Next-login selection"):
                activation.apply_live(plan)
        self.assertEqual(recipes.current_selection()[0], "chrome")
        self.assertEqual(self.supervisor.active, "classic")
        self.assertEqual(self.menu.read_bytes(), before_menu)
        self.assertFalse(self.old_panel.stopped)
        self.assertFalse(self.old_wallpaper.stopped)

    def test_parallel_creator_roundtrip_with_same_active_id_cannot_erase_history(self):
        draft = workspace.create_draft("heritage")
        activation.install(activation.inspect_install(draft))
        before_menu = self.menu.read_bytes()
        old_change = recipes.change_selection
        chrome_sha, classic_sha = staging._hash("chrome"), staging._hash("classic")

        def competing_stage(*args, **kwargs):
            # The other Creator stages Chrome and then Classic, leaving the
            # active ID unchanged but publishing a different undo history.
            old_change("chrome", expected_active="classic",
                       expected_semantic_sha256=chrome_sha)
            old_change("classic", expected_active="chrome",
                       expected_semantic_sha256=classic_sha)
            return old_change(*args, **kwargs)

        with self.server():
            plan = activation.inspect_live(draft)
            with mock.patch.object(recipes, "change_selection", side_effect=competing_stage):
                with self.assertRaisesRegex(activation.ActivationError, "selection changed"):
                    activation.apply_live(plan)
            self.assertEqual(recipes.current_selection(), ("classic", "chrome"))
            self.assertEqual(self.supervisor.active, "classic")
            self.assertEqual(self.menu.read_bytes(), before_menu)
            self.assertFalse(self.old_panel.stopped)
            self.assertFalse(self.old_wallpaper.stopped)
            self.assertIsNone(live_recovery.read())

            # Review the actual new state and switch only with fresh consent.
            applied = activation.apply_live(activation.inspect_live(draft))
            self.assertEqual(applied["active"], draft.recipe_id)
            self.assertEqual(applied["previous"], "classic")

    def test_private_selection_rehydrates_restore_after_supervisor_restart(self):
        draft = workspace.create_draft("heritage")
        activation.install(activation.inspect_install(draft))
        with self.server():
            activation.apply_live(activation.inspect_live(draft))
        self.assertEqual(recipes.selected_recipe(), draft.recipe_id)
        # Simulate the next opt-in login: the new controller receives only
        # the saved ID, private selection state and fresh native processes.
        self.env["RICEBOWL_DE_RECIPE"] = draft.recipe_id
        replacement_panel, replacement_wallpaper = Process(), Process()
        self.supervisor = _LiveSwitch(
            env=self.env, mode="native", which=lambda n: "/usr/bin/" + n,
            spawn=lambda command, **kwargs: Process(), cleanup=self.cleanup_stack,
            initial_panel=replacement_panel, initial_wallpaper=replacement_wallpaper,
            background=[replacement_wallpaper],
        )
        with mock.patch.object(self.supervisor, "_reconfigure"):
            with self.server():
                plan = activation.inspect_restore()
                self.assertEqual((plan.expected_active, plan.previous),
                                 (draft.recipe_id, "classic"))
                restored = activation.restore_live(plan)
        self.assertEqual(restored["active"], "classic")
        self.assertEqual(recipes.current_selection()[0], "classic")
        self.assertTrue(replacement_panel.stopped)
        self.assertTrue(replacement_wallpaper.stopped)


if __name__ == "__main__":
    unittest.main()
