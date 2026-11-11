"""Live Wayland switching: reviewed CAS, component failure and socket isolation."""

import json
import os
import subprocess
import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from macrice.cli import main as cli
from macrice.de import creator_contract, live, live_recovery, recipes, riceprofile, staging
from macrice.de.session import _LiveSwitch, _refresh_changed_outputs, resources


class FakeProcess:
    def __init__(self, *, exit_code=None):
        self.exit_code = exit_code
        self.terminated = False

    def poll(self):
        return 0 if self.terminated else self.exit_code

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0 if self.terminated else self.exit_code or 0


class LiveRiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.runtime = root / "run"
        self.runtime.mkdir(mode=0o700)
        self.config = root / "config"
        self.config.mkdir(mode=0o700)
        self.menu_dir = self.runtime / "ricebowl-labwc-test"
        self.menu_dir.mkdir(mode=0o700)
        self.menu = self.menu_dir / "menu.xml"
        self.menu.write_text((resources() / "labwc/menu.xml").read_text())
        self.env = {"XDG_RUNTIME_DIR": str(self.runtime),
                    "RICEBOWL_DE_SESSION_CONFIG": str(self.menu_dir),
                    "RICEBOWL_DE_RECIPE": "classic", "WAYLAND_DISPLAY": "wayland-19"}
        self.env_patch = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.config)})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.tools = {name: f"/usr/bin/{name}" for name in
                      ("labwc", "swaybg", "riceplate-native", "waybar")}
        self.processes = []
        self.initial_panel = FakeProcess()
        self.initial_wallpaper = FakeProcess()
        self.background = [self.initial_wallpaper]
        self.cleanup_stack = ExitStack()
        self.addCleanup(self.cleanup_stack.close)
        self.failed_next = False

        def spawn(command, **kwargs):
            process = FakeProcess(exit_code=1 if self.failed_next and
                                  command[0].endswith("riceplate-native") else None)
            self.processes.append((command, kwargs, process))
            return process

        self.controller = _LiveSwitch(
            env=self.env, mode="native", which=self.tools.get, spawn=spawn,
            cleanup=self.cleanup_stack, initial_panel=self.initial_panel,
            initial_wallpaper=self.initial_wallpaper, background=self.background)
        self.reconfigure = mock.patch.object(self.controller, "_reconfigure")
        self.reconfigure.start()
        self.addCleanup(self.reconfigure.stop)
        self.sleep = mock.patch("macrice.de.session.time.sleep")
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def change(self, action, token=None, digest=None, expected="classic"):
        return self.controller.handle({"action": action, "recipe": token,
                                       "sha256": digest, "expected": expected})

    def import_luna(self):
        source = self.runtime / "luna.json"
        source.write_bytes((Path(__file__).resolve().parents[1] /
                            "examples/wayland/xp-luna-columns.json").read_bytes())
        source.chmod(0o600)
        return recipes.import_recipe(source)[0].recipe_id

    def test_luna_chrome_live_switch_and_restore_are_isolated(self):
        token = self.import_luna()
        override = self.menu_dir / "themerc-override"
        self.assertFalse(override.exists())
        response = self.change("apply", token, staging._hash(token))
        self.assertTrue(response["changed"])
        self.assertIn("#1654b5", override.read_text(encoding="utf-8"))
        self.assertEqual(override.stat().st_mode & 0o777, 0o600)
        self.assertEqual(recipes.current_selection()[0], token)
        self.change("restore", expected=token)
        self.assertFalse(override.exists())
        self.assertEqual(recipes.current_selection()[0], "classic")

    def test_luna_chrome_rolls_back_on_failed_selection(self):
        token = self.import_luna()
        original_menu = self.menu.read_bytes()
        with mock.patch.object(recipes, "change_selection",
                               side_effect=recipes.SelectionConflict("concurrent update")):
            with self.assertRaises(live.LiveError) as caught:
                self.change("apply", token, staging._hash(token))
        self.assertEqual(caught.exception.code, "selection_conflict")
        self.assertEqual(self.menu.read_bytes(), original_menu)
        self.assertFalse((self.menu_dir / "themerc-override").exists())
        self.assertEqual(recipes.current_selection(), ("classic", None))
        self.assertFalse(self.initial_panel.terminated)

    def test_luna_theme_is_removed_if_labwc_reconfigure_fails(self):
        token = self.import_luna()
        original_menu = self.menu.read_bytes()
        self.controller._reconfigure.side_effect = [
            subprocess.CalledProcessError(1, "labwc --reconfigure"), None,
        ]
        with self.assertRaises(live.LiveError) as caught:
            self.change("apply", token, staging._hash(token))
        self.assertEqual(caught.exception.code, "component_failed")
        self.assertEqual(self.menu.read_bytes(), original_menu)
        self.assertFalse((self.menu_dir / "themerc-override").exists())
        self.assertEqual(self.controller._reconfigure.call_count, 2)
        self.assertFalse(self.initial_panel.terminated)

    def test_luna_chrome_is_preserved_if_switch_away_fails(self):
        token = self.import_luna()
        self.change("apply", token, staging._hash(token))
        override = self.menu_dir / "themerc-override"
        original = override.read_bytes()
        with mock.patch.object(recipes, "change_selection",
                               side_effect=recipes.SelectionConflict("concurrent update")):
            with self.assertRaises(live.LiveError):
                self.change("apply", "chrome", staging._hash("chrome"), expected=token)
        self.assertEqual(override.read_bytes(), original)
        self.assertEqual(recipes.current_selection()[0], token)

    def test_native_live_switch_and_explicit_restore_are_persisted(self):
        digest = staging._hash("chrome")
        changed = self.change("apply", "chrome", digest)
        self.assertTrue(changed["changed"])
        self.assertEqual((changed["active"], changed["previous"]), ("chrome", "classic"))
        self.assertEqual(recipes.current_selection(), ("chrome", "classic"))
        self.assertTrue(self.initial_panel.terminated)
        self.assertTrue(self.initial_wallpaper.terminated)
        self.assertEqual(len(self.background), 1)
        self.assertTrue(any("riceplate-native" in item[0][0] for item in self.processes))
        self.assertTrue(any("swaybg" in item[0][0] for item in self.processes))
        restored = self.change("restore", expected="chrome")
        self.assertEqual((restored["active"], restored["previous"]), ("classic", "chrome"))
        self.assertEqual(recipes.current_selection(), ("classic", "chrome"))
        self.assertIsNone(live_recovery.read())

    def test_process_killed_after_selection_write_is_recovered_at_next_login(self):
        original = recipes._selection_snapshot()
        genuine = recipes.change_selection

        def interrupted_after_commit(*args, **kwargs):
            genuine(*args, **kwargs)
            raise KeyboardInterrupt("simulated SIGKILL between commit and journal cleanup")

        with mock.patch.object(recipes, "change_selection", side_effect=interrupted_after_commit):
            with self.assertRaisesRegex(KeyboardInterrupt, "simulated SIGKILL"):
                self.change("apply", "chrome", staging._hash("chrome"))
        self.assertEqual(recipes.current_selection()[0], "chrome")
        self.assertIsNotNone(live_recovery.read())
        with mock.patch.object(live_recovery, "_owner_running", return_value=False):
            recovery = live_recovery.reconcile()
        self.assertEqual(recovery["status"], "restored")
        self.assertEqual(recipes._selection_snapshot(), original)
        self.assertIsNone(live_recovery.read())

    def test_refresh_outputs_restarts_only_waybar_and_preserves_active_selection(self):
        self.controller.mode = "waybar"
        response = self.controller.handle({
            "action": "refresh-outputs", "recipe": None, "sha256": None, "expected": None,
        })
        self.assertTrue(response["changed"])
        self.assertEqual(response["active"], "classic")
        self.assertEqual(recipes.current_selection(), ("classic", None))
        self.assertTrue(self.initial_panel.terminated)
        self.assertFalse(self.initial_wallpaper.terminated)
        self.assertEqual(len(self.processes), 1)
        self.assertIn("--config", self.processes[0][0])
        self.assertTrue(self.controller.panel.poll() is None)

    def test_external_output_event_refreshes_only_when_compiled_layout_changes(self):
        self.controller.mode = "waybar"
        with mock.patch("macrice.de.session._waybar_recipe_config",
                        return_value=("same", "style")):
            signature = _refresh_changed_outputs(
                self.controller, ("classic", "same"), self.env, self.tools.get)
        self.assertEqual(signature, ("classic", "same"))
        self.assertEqual(self.processes, [])
        with mock.patch("macrice.de.session._waybar_recipe_config",
                        return_value=("new-output-width", "style")):
            signature = _refresh_changed_outputs(
                self.controller, signature, self.env, self.tools.get)
            self.assertEqual(signature, ("classic", "new-output-width"))
            self.assertEqual(len(self.processes), 1)
            _refresh_changed_outputs(self.controller, signature, self.env, self.tools.get)
        self.assertEqual(len(self.processes), 1)
        self.assertTrue(self.initial_panel.terminated)

    def test_refresh_outputs_fails_closed_with_old_bar_alive(self):
        self.controller.mode = "waybar"
        self.controller.which = lambda name: None if name == "waybar" else self.tools.get(name)
        with self.assertRaises(live.LiveError) as caught:
            self.controller.handle({
                "action": "refresh-outputs", "recipe": None, "sha256": None, "expected": None,
            })
        self.assertEqual(caught.exception.code, "component_failed")
        self.assertFalse(self.initial_panel.terminated)
        self.assertEqual(recipes.current_selection(), ("classic", None))

    def test_native_refresh_outputs_does_not_restart_panel(self):
        response = self.controller.handle({
            "action": "refresh-outputs", "recipe": None, "sha256": None, "expected": None,
        })
        self.assertFalse(response["changed"])
        self.assertFalse(self.initial_panel.terminated)
        self.assertEqual(self.processes, [])

    def test_shutdown_blocks_output_refresh_without_touching_live_panel(self):
        self.controller.mode = "waybar"
        self.controller.stopping = lambda: True
        with self.assertRaises(live.LiveError) as caught:
            self.controller.handle({
                "action": "refresh-outputs", "recipe": None, "sha256": None, "expected": None,
            })
        self.assertEqual(caught.exception.code, "session_stopping")
        self.assertFalse(self.initial_panel.terminated)
        self.assertEqual(self.processes, [])
        self.assertEqual(self.controller.handle({
            "action": "status", "recipe": None, "sha256": None, "expected": None,
        })["active"], "classic")

    def test_live_switch_updates_both_optional_apps_and_restores_on_rollback(self):
        from types import SimpleNamespace

        (self.menu_dir / ".ricebowl-managed").touch(mode=0o600)
        profile = riceprofile.ProfileSession.prepare(
            self.menu_dir, self.env, recipes.load("classic"),
            which=lambda name: name, run=lambda *args, **kwargs: SimpleNamespace(returncode=0))
        self.controller.profile = profile
        before = {client: (self.menu_dir / client.filename).read_bytes() for client in profile.clients}
        self.assertEqual(self.change("status", expected=None)["applications"],
                         {"taskotto": "managed", "ricefield": "managed"})
        self.change("apply", "chrome", staging._hash("chrome"))
        for client in profile.clients:
            self.assertNotEqual((self.menu_dir / client.filename).read_bytes(), before[client])
        self.change("restore", expected="chrome")
        for client in profile.clients:
            self.assertEqual((self.menu_dir / client.filename).read_bytes(), before[client])

    def test_persist_failure_restores_both_client_profiles(self):
        from types import SimpleNamespace

        (self.menu_dir / ".ricebowl-managed").touch(mode=0o600)
        profile = riceprofile.ProfileSession.prepare(
            self.menu_dir, self.env, recipes.load("classic"),
            which=lambda name: name, run=lambda *args, **kwargs: SimpleNamespace(returncode=0))
        self.controller.profile = profile
        before = {client: (self.menu_dir / client.filename).read_bytes() for client in profile.clients}
        old_menu = self.menu.read_bytes()
        with mock.patch("macrice.de.recipes.change_selection",
                        side_effect=recipes.SelectionConflict("concurrent update")):
            with self.assertRaises(live.LiveError) as caught:
                self.change("apply", "chrome", staging._hash("chrome"))
        self.assertEqual(caught.exception.code, "selection_conflict")
        self.assertEqual(self.menu.read_bytes(), old_menu)
        for client in profile.clients:
            self.assertEqual((self.menu_dir / client.filename).read_bytes(), before[client])
        self.assertFalse(self.initial_panel.terminated)
        self.assertIsNone(live_recovery.read())

    def test_selection_durability_failure_recovers_exact_previous_state(self):
        from types import SimpleNamespace

        (self.menu_dir / ".ricebowl-managed").touch(mode=0o600)
        profile = riceprofile.ProfileSession.prepare(
            self.menu_dir, self.env, recipes.load("classic"),
            which=lambda name: name, run=lambda *args, **kwargs: SimpleNamespace(returncode=0))
        self.controller.profile = profile
        before_profiles = {client: (self.menu_dir / client.filename).read_bytes()
                           for client in profile.clients}
        before_menu = self.menu.read_bytes()
        real = recipes.change_selection

        def committed_but_not_durable(*args, **kwargs):
            real(*args, **kwargs)
            raise OSError("simulated fsync failure after replacing selection")

        with mock.patch.object(recipes, "change_selection", side_effect=committed_but_not_durable):
            with self.assertRaises(live.LiveError) as caught:
                self.change("apply", "chrome", staging._hash("chrome"))
        self.assertEqual(caught.exception.code, "component_failed")
        self.assertEqual(recipes.current_selection(), ("classic", None))
        self.assertIsNone(recipes._selection_snapshot())
        self.assertEqual(self.menu.read_bytes(), before_menu)
        self.assertEqual({client: (self.menu_dir / client.filename).read_bytes()
                          for client in profile.clients}, before_profiles)
        self.assertFalse(self.initial_panel.terminated)
        self.assertFalse(self.initial_wallpaper.terminated)

    def test_selection_recovery_preserves_existing_undo_history(self):
        # First establish a pinned two-entry login history, then simulate a
        # post-replace failure during another live switch.
        self.change("apply", "chrome", staging._hash("chrome"))
        original = recipes._selection_snapshot()
        real = recipes.change_selection

        def committed_but_not_durable(*args, **kwargs):
            real(*args, **kwargs)
            raise OSError("simulated late durability failure")

        with mock.patch.object(recipes, "change_selection", side_effect=committed_but_not_durable):
            with self.assertRaises(live.LiveError):
                self.change("apply", "classic", staging._hash("classic"), expected="chrome")
        self.assertEqual(recipes._selection_snapshot(), original)
        self.assertEqual(self.controller.active, "chrome")

    def test_shutdown_after_selection_write_recovers_previous_state(self):
        stopping = False
        self.controller.stopping = lambda: stopping
        real = recipes.change_selection

        def commit_before_shutdown(*args, **kwargs):
            nonlocal stopping
            result = real(*args, **kwargs)
            stopping = True
            return result

        with mock.patch.object(recipes, "change_selection", side_effect=commit_before_shutdown):
            with self.assertRaises(live.LiveError) as caught:
                self.change("apply", "chrome", staging._hash("chrome"))
        self.assertEqual(caught.exception.code, "session_stopping")
        self.assertIsNone(recipes._selection_snapshot())
        self.assertEqual(self.controller.active, "classic")
        self.assertFalse(self.initial_panel.terminated)
        self.assertTrue(all(process.poll() is not None for _, _, process in self.processes))

    def test_live_panel_crash_has_bounded_waybar_rescue(self):
        self.initial_panel.exit_code = 7
        self.controller.rescue_panel()
        self.assertEqual(self.controller.status()["panel"], "waybar-fallback")
        self.assertEqual(self.controller.status()["active"], "classic")
        self.assertEqual(self.processes[-1][0][0], "/usr/bin/waybar")
        self.assertEqual(recipes.current_selection(), ("classic", None))
        self.assertIsNot(self.controller.panel, self.initial_panel)

    def test_live_rescue_rejects_recipe_changed_since_activation(self):
        with mock.patch.object(staging, "_hash", return_value="0" * 64):
            with self.assertRaises(live.LiveError) as caught:
                self.controller.rescue_panel()
        self.assertEqual(caught.exception.code, "recipe_changed")
        self.assertFalse(self.processes)

    def test_recovery_refuses_to_overwrite_concurrent_selection(self):
        real = recipes.change_selection

        def concurrent_update(*args, **kwargs):
            real(*args, **kwargs)
            real("classic", expected_active="chrome")  # Simulate another Creator writer.
            raise OSError("simulated durability failure")

        with mock.patch.object(recipes, "change_selection", side_effect=concurrent_update):
            with self.assertRaises(live.LiveError) as caught:
                self.change("apply", "chrome", staging._hash("chrome"))
        self.assertEqual(caught.exception.code, "rollback_failed")
        self.assertEqual(recipes.current_selection()[0], "classic")
        self.assertEqual(self.controller.active, "classic")
        self.assertIsNotNone(live_recovery.read())

    def test_profile_rollback_failure_does_not_skip_menu_recovery(self):
        from types import SimpleNamespace

        (self.menu_dir / ".ricebowl-managed").touch(mode=0o600)
        profile = riceprofile.ProfileSession.prepare(
            self.menu_dir, self.env, recipes.load("classic"),
            which=lambda name: name, run=lambda *args, **kwargs: SimpleNamespace(returncode=0))
        self.controller.profile = profile
        before_menu = self.menu.read_bytes()
        with mock.patch.object(recipes, "change_selection",
                               side_effect=recipes.SelectionConflict("concurrent update")), \
             mock.patch.object(profile, "restore", side_effect=riceprofile.ProfileError("I/O error")):
            with self.assertRaises(live.LiveError) as caught:
                self.change("apply", "chrome", staging._hash("chrome"))
        self.assertEqual(caught.exception.code, "rollback_failed")
        self.assertEqual(self.menu.read_bytes(), before_menu)
        self.assertFalse(self.initial_panel.terminated)

    def test_failed_new_panel_keeps_live_and_saved_selection(self):
        before = self.menu.read_text()
        self.failed_next = True
        with self.assertRaises(live.LiveError) as caught:
            self.change("apply", "chrome", staging._hash("chrome"))
        self.assertEqual(caught.exception.code, "component_failed")
        self.assertEqual(self.controller.active, "classic")
        self.assertFalse(self.initial_panel.terminated)
        self.assertFalse(self.initial_wallpaper.terminated)
        self.assertTrue(all(process.poll() is not None for _, _, process in self.processes))
        self.assertEqual(self.menu.read_text(), before)
        self.assertEqual(recipes.current_selection(), ("classic", None))

    def test_selection_commit_failure_restores_private_menu_and_old_processes(self):
        source = self.config.parent / "custom.json"
        recipes.create_from_template(source="chrome", destination=source,
                                     recipe_id="composable", name="Composable", schema_version=4)
        recipes.import_recipe(source)
        previous_menu = self.menu.read_text()
        with mock.patch("macrice.de.recipes.change_selection",
                        side_effect=recipes.SelectionConflict("concurrent stage")):
            with self.assertRaises(live.LiveError) as caught:
                self.change("apply", "composable", staging._hash("composable"))
        self.assertEqual(caught.exception.code, "selection_conflict")
        self.assertEqual(self.menu.read_text(), previous_menu)
        self.assertFalse(self.initial_panel.terminated)
        self.assertEqual(recipes.current_selection(), ("classic", None))

    def test_custom_menu_is_switched_and_restored_without_touching_global_config(self):
        source = self.config.parent / "custom.json"
        recipes.create_from_template(source="chrome", destination=source,
                                     recipe_id="composable", name="Composable", schema_version=4)
        recipes.import_recipe(source)
        original = self.menu.read_text()
        changed = self.change("apply", "composable", staging._hash("composable"))
        self.assertEqual(changed["active"], "composable")
        self.assertIn('id="root-menu"', self.menu.read_text())
        self.assertEqual(recipes.current_selection()[0], "composable")
        self.change("restore", expected="composable")
        self.assertEqual(self.menu.read_text(), original)

    def test_concurrent_next_login_stage_rejects_live_apply(self):
        staging.stage("chrome", staging._hash("chrome"))
        with self.assertRaises(live.LiveError) as caught:
            self.change("apply", "chrome", staging._hash("chrome"))
        self.assertEqual(caught.exception.code, "selection_conflict")
        self.assertEqual(self.processes, [])
        self.assertEqual(recipes.current_selection()[0], "chrome")
        self.assertEqual(self.controller.active, "classic")

    def test_concurrent_stage_with_same_active_id_preserves_new_undo_history(self):
        # A parallel Creator can stage A -> B -> A during live preflight.
        # Checking only the active ID would silently destroy its new history.
        original_change = recipes.change_selection
        before_menu = self.menu.read_bytes()
        chrome_sha, classic_sha = staging._hash("chrome"), staging._hash("classic")

        def staged_during_switch(*args, **kwargs):
            original_change("chrome", expected_active="classic",
                            expected_semantic_sha256=chrome_sha)
            original_change("classic", expected_active="chrome",
                            expected_semantic_sha256=classic_sha)
            return original_change(*args, **kwargs)

        with mock.patch.object(recipes, "change_selection", side_effect=staged_during_switch):
            with self.assertRaises(live.LiveError) as caught:
                self.change("apply", "chrome", chrome_sha)
        self.assertEqual(caught.exception.code, "selection_conflict")
        self.assertEqual(recipes.current_selection(), ("classic", "chrome"))
        self.assertEqual(self.controller.active, "classic")
        self.assertEqual(self.menu.read_bytes(), before_menu)
        self.assertFalse(self.initial_panel.terminated)
        self.assertFalse(self.initial_wallpaper.terminated)
        self.assertTrue(all(process.poll() is not None for _, _, process in self.processes))
        self.assertIsNone(live_recovery.read())

    def test_restart_supervisor_still_serves_classic_when_selection_is_corrupt(self):
        selected = recipes._private_recipe_dir(create=True) / ".active-recipe"
        selected.write_bytes(b"{broken-selection\n")
        selected.chmod(0o600)
        original = selected.read_bytes()
        # The login resolver already selects classic for a corrupt selection.
        # The supervisor must not crash while starting that safe fallback.
        controller = _LiveSwitch(
            env=self.env, mode="native", which=self.tools.get,
            spawn=lambda command, **kw: FakeProcess(), cleanup=self.cleanup_stack,
            initial_panel=FakeProcess(), initial_wallpaper=FakeProcess(),
            background=[])
        self.assertEqual(controller.status()["active"], "classic")
        with self.assertRaises(live.LiveError) as caught:
            controller.handle({"action": "apply", "recipe": "chrome",
                               "sha256": staging._hash("chrome"), "expected": "classic"})
        self.assertEqual(caught.exception.code, "invalid_recipe")
        self.assertEqual(selected.read_bytes(), original)
        self.assertIsNone(live_recovery.read())

    def test_nested_preview_switch_never_persists_login_selection(self):
        self.controller.nested = True
        result = self.change("apply", "chrome", staging._hash("chrome"))
        self.assertEqual(result["active"], "chrome")
        self.assertFalse(result["next_login_persisted"])
        self.assertEqual(recipes.current_selection(), ("classic", None))
        self.assertIsNone(live_recovery.read())
        self.change("restore", expected="chrome")
        self.assertEqual(recipes.current_selection(), ("classic", None))

    def test_invalid_review_or_active_guard_rejects_before_spawn(self):
        for token, digest, expected, code in (
            ("chrome", "0" * 64, "classic", "recipe_changed"),
            ("chrome", staging._hash("chrome"), "unknown", "selection_conflict"),
            ("../unsafe", staging._hash("chrome"), "classic", "invalid_live_request"),
        ):
            with self.subTest(code=code), self.assertRaises(live.LiveError) as caught:
                self.change("apply", token, digest, expected)
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.processes, [])

    def test_private_socket_roundtrip_and_cleanup(self):
        path = live.socket_path(self.env)
        try:
            context = live.listen(self.env)
            listener = context.__enter__()
        except PermissionError:
            self.skipTest("AF_UNIX socket creation is forbidden by this CI sandbox")
        try:
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            worker = threading.Thread(target=live.serve_once,
                                      args=(listener, self.controller.handle))
            worker.start()
            result = live.request("status", environment=self.env)
            worker.join(timeout=4)
            self.assertEqual(result["active"], "classic")
            self.assertFalse(worker.is_alive())
            with self.assertRaises(live.LiveError):
                with live.listen(self.env):
                    pass
        finally:
            context.__exit__(None, None, None)
        self.assertFalse(path.exists())

    def test_socket_rejects_invalid_display_and_symlink(self):
        with self.assertRaises(live.LiveError):
            live.socket_path({**self.env, "WAYLAND_DISPLAY": "../../wayland-0"})
        path = live.socket_path(self.env)
        path.symlink_to(self.menu)
        with self.assertRaises(live.LiveError):
            with live.listen(self.env):
                pass
        self.assertTrue(path.is_symlink())

    def test_creator_contract_and_cli_outside_session(self):
        catalog = creator_contract.describe_creator_api()
        commands = {entry["command"] for entry in catalog["commands"]}
        self.assertTrue({"creator-live-apply", "creator-live-restore",
                         "creator-live-status", "display-refresh"} <= commands)
        self.assertEqual(catalog["live"]["live_version"], 1)
        self.assertIn("display-refresh", catalog["live"]["commands"])
        with mock.patch.dict(os.environ, self.env), mock.patch("builtins.print") as printed:
            self.assertEqual(cli(["de", "creator-live-status", "--json"]), 2)
        response = json.loads(printed.call_args.args[0])
        self.assertEqual(response["error"]["code"], "live_unavailable")

    def test_display_refresh_cli_calls_only_owner_session_without_recipe_options(self):
        response = {"version": 1, "ok": True, "active": "classic",
                    "previous": None, "changed": True}
        with mock.patch("macrice.de.live.request", return_value=response) as request, \
                mock.patch("builtins.print") as printed:
            self.assertEqual(cli(["de", "display-refresh", "--json"]), 0)
        request.assert_called_once_with("refresh-outputs", recipe=None, sha256=None,
                                        expected=None)
        self.assertEqual(json.loads(printed.call_args.args[0]), response)
        with mock.patch("macrice.de.live.request") as request:
            self.assertEqual(cli(["de", "display-refresh", "--recipe", "chrome"]), 1)
            request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
