"""The Wayland RicePop bridge only invokes freshly verified active actions."""

import json
import os
import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

from macrice.cli import main
from macrice.de import notifications, session, settings
from macrice.de.creator_contract import describe_creator_api


class WaylandRicePopReadTests(unittest.TestCase):
    def test_dnd_only_controls_one_mode_with_explicit_previous_state(self):
        calls = []
        modes = ["default"]

        def run(args, **_kwargs):
            calls.append(args)
            if len(args) == 2:
                return subprocess.CompletedProcess(args, 0,
                                                   ("\n".join(modes) + "\n").encode(), b"")
            if args[2] == "-a":
                modes.append(notifications._DND_MODE)
            elif args[2] == "-r":
                modes.remove(notifications._DND_MODE)
            return subprocess.CompletedProcess(args, 0, b"", b"")

        with mock.patch.object(notifications, "_owned_mako", return_value=("makoctl", 7)), \
             mock.patch.object(notifications.subprocess, "run", side_effect=run):
            self.assertFalse(notifications.dnd_status()["do_not_disturb"])
            self.assertTrue(notifications.set_dnd(True, expected=False)["changed"])
            self.assertTrue(notifications.dnd_status()["do_not_disturb"])
            with self.assertRaises(notifications.NotificationBridgeError) as stale:
                notifications.set_dnd(False, expected=False)
            self.assertEqual(stale.exception.code, "stale_dnd_state")
            self.assertTrue(notifications.set_dnd(False, expected=True)["changed"])
            self.assertFalse(notifications.set_dnd(False, expected=False)["changed"])
        self.assertEqual([call for call in calls if len(call) == 4],
                         [["makoctl", "mode", "-a", notifications._DND_MODE],
                          ["makoctl", "mode", "-r", notifications._DND_MODE]])

    def test_dnd_owner_must_match_ricebowl_config_and_active_bus_pid(self):
        config = str(session.resources() / "mako.conf")
        env = {"XDG_SESSION_DESKTOP": "ricebowl", "RICEBOWL_DE_NESTED": "0",
               "WAYLAND_DISPLAY": "wayland-1"}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(notifications.shutil, "which", side_effect=lambda x: x), \
             mock.patch.object(notifications.subprocess, "run", return_value=
                               subprocess.CompletedProcess([], 0, b"  PID=1245\n", b"")), \
             mock.patch("builtins.open", mock.mock_open(
                 read_data=("/usr/bin/mako\0--config\0" + config + "\0").encode())):
            self.assertEqual(notifications._owned_mako(), ("makoctl", 1245))
        for data in (b"/usr/bin/xfce4-notifyd\0", b"/usr/bin/mako\0", b"", b"a" * 5000):
            with self.subTest(data=data[:30]), \
                 mock.patch.dict(os.environ, env, clear=True), \
                 mock.patch.object(notifications.shutil, "which", side_effect=lambda x: x), \
                 mock.patch.object(notifications.subprocess, "run", return_value=
                                   subprocess.CompletedProcess([], 0, b"PID=1245\n", b"")), \
                 mock.patch("builtins.open", mock.mock_open(read_data=data)):
                with self.assertRaises(notifications.NotificationBridgeError) as error:
                    notifications._owned_mako()
                self.assertEqual(error.exception.code, "dnd_host_unverified")

    def test_dnd_never_touches_other_sessions_or_bad_inventory(self):
        with mock.patch.dict(os.environ, {"XDG_SESSION_DESKTOP": "XFCE",
                                              "WAYLAND_DISPLAY": "wayland-1"}, clear=True), \
             mock.patch.object(notifications.subprocess, "run") as run:
            with self.assertRaises(notifications.NotificationBridgeError) as error:
                notifications.set_dnd(True)
            self.assertEqual(error.exception.code, "dnd_session_unavailable")
            run.assert_not_called()
        with mock.patch.object(notifications, "_owned_mako", return_value=("makoctl", 7)), \
             mock.patch.object(notifications.subprocess, "run", return_value=
                               subprocess.CompletedProcess([], 0, b"default\ndefault\n", b"")):
            with self.assertRaises(notifications.NotificationBridgeError):
                notifications.dnd_status()
        for requested in ("on", 1, None):
            with self.subTest(requested=requested):
                with self.assertRaises(notifications.NotificationBridgeError):
                    notifications.set_dnd(requested)

    def test_dnd_cli_contract_and_ricespice_navigation(self):
        self.assertIn("notifications", [item[0] for item in settings.SECTIONS])
        with mock.patch("builtins.print") as printed:
            self.assertEqual(main(["de", "notification-dnd", "--dnd", "on", "--json"]), 1)
            self.assertEqual(main(["de", "notifications", "--dnd", "on", "--json"]), 1)
        with mock.patch.object(notifications, "dnd_status", return_value={
                "ok": True, "do_not_disturb": False}), mock.patch("builtins.print") as printed:
            self.assertEqual(main(["de", "notification-dnd", "--json"]), 0)
            self.assertFalse(json.loads(printed.call_args.args[0])["do_not_disturb"])
        with mock.patch.object(notifications, "set_dnd", return_value={
                "ok": True, "do_not_disturb": True}) as setter, \
             mock.patch("builtins.print"):
            self.assertEqual(main(["de", "notification-dnd", "--dnd", "on",
                                   "--expect-dnd", "off", "--json"]), 0)
            setter.assert_called_once_with(True, expected=False)

    def test_ricespice_dnd_page_only_offers_verified_explicit_toggle(self):
        controls = {}
        statuses = []
        page = SimpleNamespace()
        page._text = lambda *_a, **_k: None
        page._state = statuses.append
        page.content = SimpleNamespace(show_all=lambda: None)
        page.show_page = lambda name: statuses.append("page:" + name)

        def button(title, callback, **_options):
            controls[title] = callback

        page._button = button

        def background(work, done):
            done(work())

        page._background = background
        with mock.patch.object(notifications, "dnd_status", return_value={
                "do_not_disturb": False}), \
             mock.patch.object(notifications, "set_dnd", return_value={
                 "do_not_disturb": True}) as setter:
            settings.RiceSpiceWindow._notifications(page)
            self.assertIn("Do Not Disturb: off", statuses)
            controls["Turn on Do Not Disturb"]()
            setter.assert_called_once_with(True, expected=False)
            self.assertIn("page:notifications", statuses)

    def test_reads_mako_live_and_history_without_replaying_actions(self):
        active = [{"id": 12, "summary": "Download", "body": "Finished",
                   "app_name": "Files", "urgency": "normal",
                   "actions": {"dangerous": "Delete file"}}]
        finished = [{"id": 13, "summary": "Mail", "body": "Private message",
                     "app_name": "Mail", "urgency": "low"}]
        def fake_run(args, **options):
            self.assertEqual(args[0], "/usr/bin/makoctl")
            self.assertEqual(args[-1], "-j")
            self.assertTrue(options["capture_output"])
            return subprocess.CompletedProcess(args, 0,
                   json.dumps(active if args[1] == "list" else finished).encode(), b"")
        with mock.patch("macrice.de.notifications.shutil.which", return_value="/usr/bin/makoctl"), \
             mock.patch("macrice.de.notifications.subprocess.run", side_effect=fake_run):
            result = notifications.inspect()
        self.assertTrue(result["read_only"])
        self.assertFalse(result["mutates_active_desktop"])
        self.assertFalse(result["actions_replayed"])
        self.assertEqual(result["active"][0]["summary"], "Download")
        self.assertEqual(result["active"][0]["actions"],
                         [{"key": "dangerous", "label": "Delete file"}])
        self.assertNotIn("actions", result["history"][0])
        self.assertEqual(result["history"][0]["id"], 13)

    def test_missing_backend_invalid_reply_and_overlong_history_fail_closed(self):
        with mock.patch("macrice.de.notifications.shutil.which", return_value=None):
            with self.assertRaises(notifications.NotificationBridgeError):
                notifications.inspect()
        for payload in (b"[]junk", b'{}', b'[{"id": true}]', b'x' * (128 * 1024 + 1)):
            with self.subTest(payload=payload[:20]):
                with self.assertRaises(notifications.NotificationBridgeError):
                    notifications._records(payload)
        limited, truncated = notifications._records(json.dumps([
            {"id": x + 1, "summary": "abc"} for x in range(80)]).encode())
        self.assertEqual(len(limited), 64)
        self.assertTrue(truncated)

    def test_machine_cli_returns_error_without_printing_private_paths(self):
        with mock.patch("macrice.de.notifications.shutil.which", return_value=None), \
             mock.patch("builtins.print") as printed:
            self.assertEqual(main(["de", "notifications", "--json"]), 2)
            output = json.loads(printed.call_args.args[0])
        self.assertEqual(output["error"]["code"], "notifications_unavailable")
        self.assertFalse(output["ok"])

    def test_explicit_dismiss_is_id_scoped_and_never_invokes_actions(self):
        calls = []
        def fake_run(args, **options):
            calls.append(args)
            if args[1] == "list":
                data = [{"id": 12, "summary": "Finished", "actions": {"delete": "Delete"}}]
                return subprocess.CompletedProcess(args, 0, json.dumps(data).encode(), b"")
            return subprocess.CompletedProcess(args, 0, b"", b"")
        with mock.patch("macrice.de.notifications.shutil.which", return_value="/usr/bin/makoctl"), \
             mock.patch("macrice.de.notifications.subprocess.run", side_effect=fake_run):
            result = notifications.dismiss(12)
        self.assertTrue(result["dismissed"])
        self.assertTrue(result["mutates_active_desktop"])
        self.assertFalse(result["actions_replayed"])
        self.assertEqual(calls, [["/usr/bin/makoctl", "list", "-j"],
                                 ["/usr/bin/makoctl", "dismiss", "-n", "12"]])

    def test_dismiss_rejects_ids_not_currently_visible_and_all_invalid_values(self):
        for value in (True, False, -1, 0, 2**32, "12", None):
            with self.subTest(value=value):
                with self.assertRaises(notifications.NotificationBridgeError):
                    notifications.dismiss(value)
        active = b'[{"id": 12, "summary": "one"}]'
        with mock.patch("macrice.de.notifications.shutil.which", return_value="makoctl"), \
             mock.patch("macrice.de.notifications.subprocess.run",
                        return_value=subprocess.CompletedProcess([], 0, active, b"")) as run:
            with self.assertRaises(notifications.NotificationBridgeError) as ctx:
                notifications.dismiss(13)
        self.assertEqual(ctx.exception.code, "notification_not_found")
        run.assert_called_once()

    def test_dismiss_fails_closed_on_truncation_backend_error_and_timeout(self):
        many = json.dumps([{"id": i} for i in range(1, 70)]).encode()
        with mock.patch("macrice.de.notifications.shutil.which", return_value="makoctl"), \
             mock.patch("macrice.de.notifications.subprocess.run",
                        return_value=subprocess.CompletedProcess([], 0, many, b"")) as run:
            with self.assertRaises(notifications.NotificationBridgeError) as ctx:
                notifications.dismiss(5)
        self.assertEqual(ctx.exception.code, "ambiguous_notification_id")
        run.assert_called_once()
        with mock.patch("macrice.de.notifications.shutil.which", return_value="makoctl"), \
             mock.patch("macrice.de.notifications.subprocess.run",
                        side_effect=subprocess.TimeoutExpired("makoctl", 3)):
            with self.assertRaises(notifications.NotificationBridgeError):
                notifications.dismiss(5)

    def test_invoke_requires_fresh_exact_action_from_active_entry(self):
        calls = []
        active = [{"id": 12, "summary": "Install", "actions": {
            "default": "Open", "reply": "Reply"}}]

        def fake_run(args, **options):
            calls.append(args)
            payload = json.dumps(active).encode() if args[1] == "list" else b""
            return subprocess.CompletedProcess(args, 0, payload, b"")

        with mock.patch("macrice.de.notifications.shutil.which", return_value="makoctl"), \
             mock.patch("macrice.de.notifications.subprocess.run", side_effect=fake_run):
            result = notifications.invoke(12, "reply")
            self.assertTrue(result["invoked"])
            self.assertTrue(result["mutates_active_desktop"])
            self.assertEqual(calls, [["makoctl", "list", "-j"],
                                     ["makoctl", "invoke", "-n", "12", "--", "reply"]])
            calls.clear()
            with self.assertRaises(notifications.NotificationBridgeError) as ctx:
                notifications.invoke(12, "hidden-action")
            self.assertEqual(ctx.exception.code, "notification_action_not_found")
            self.assertEqual(len(calls), 1)

    def test_invoke_rejects_malformed_action_data_and_ambiguous_inventory(self):
        for invalid in (None, True, "", "a" * 81, "re\nply", "bad\x00value"):
            with self.subTest(value=invalid):
                with self.assertRaises(notifications.NotificationBridgeError):
                    notifications.invoke(1, invalid)
        for actions in (["reply"], {"": "Reply"}, {"x": ""},
                        {"x": "R\n"}, {str(x): "Action" for x in range(9)}):
            with self.subTest(actions=actions):
                with self.assertRaises(notifications.NotificationBridgeError):
                    notifications._records(json.dumps([{"id": 1, "actions": actions}]).encode(),
                                           include_actions=True)
        with mock.patch("macrice.de.notifications.shutil.which", return_value="makoctl"), \
             mock.patch("macrice.de.notifications.subprocess.run", return_value=
                        subprocess.CompletedProcess([], 0, json.dumps([
                            {"id": 7, "actions": {"reply": "Reply"}},
                            {"id": 7, "actions": {"reply": "Reply"}}]).encode(), b"")):
            with self.assertRaises(notifications.NotificationBridgeError) as ctx:
                notifications.invoke(7, "reply")
            self.assertEqual(ctx.exception.code, "ambiguous_notification_id")

    def test_invoke_cli_has_explicit_required_args_and_never_invokes_history(self):
        with mock.patch("builtins.print") as printed:
            self.assertEqual(main(["de", "notification-invoke", "--notification-id", "3", "--json"]), 1)
            self.assertEqual(main(["de", "notifications", "--action-key", "reply", "--json"]), 1)
        with mock.patch("macrice.de.notifications.shutil.which", return_value=None), \
             mock.patch("builtins.print") as printed:
            self.assertEqual(main(["de", "notification-invoke", "--notification-id", "3",
                                   "--action-key", "reply", "--json"]), 2)
            payload = json.loads(printed.call_args.args[0])
            self.assertFalse(payload["invoked"])

    def test_cli_dismiss_requires_explicit_id_and_json_is_honest(self):
        with mock.patch("builtins.print") as printed:
            self.assertEqual(main(["de", "notification-dismiss", "--json"]), 1)
            self.assertEqual(main(["de", "notifications", "--notification-id", "10", "--json"]), 1)
        with mock.patch("macrice.de.notifications.shutil.which", return_value=None), \
             mock.patch("builtins.print") as printed:
            self.assertEqual(main(["de", "notification-dismiss", "--notification-id", "12", "--json"]), 2)
            output = json.loads(printed.call_args.args[0])
        self.assertFalse(output["read_only"])
        self.assertFalse(output["dismissed"])

    def test_creator_inventory_declares_mutation_instead_of_silent_side_effect(self):
        contract = describe_creator_api()
        command = next(item for item in contract["commands"]
                       if item["command"] == "notification-dismiss")
        self.assertTrue(command["mutates_active_session"])
        self.assertIn("notification-dismiss", contract["active_session_mutation"])
        invoke_command = next(item for item in contract["commands"]
                              if item["command"] == "notification-invoke")
        self.assertTrue(invoke_command["mutates_active_session"])
        self.assertIn("--action-key KEY", invoke_command["cli"])


if __name__ == "__main__":
    unittest.main()
