"""The Wayland RicePop bridge only invokes freshly verified active actions."""

import json
import os
import subprocess
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest import mock

from macrice.cli import main
from macrice.de import notifications, session, settings
from macrice.de.creator_contract import describe_creator_api


def _legacy_busctl(records):
    """Ubuntu 24.04 Mako 1.8's typed busctl JSON response."""
    fields = {"id": "u", "summary": "s", "body": "s", "app_name": "s",
              "urgency": "y", "actions": "a{ss}"}
    return json.dumps({"type": "aa{sv}", "data": [[{
        ("app-name" if key == "app_name" else key):
        {"type": fields[key], "data": value}
        for key, value in entry.items()
    } for entry in records]]}).encode()


class WaylandRicePopReadTests(unittest.TestCase):
    @staticmethod
    def _bind_inbox_open(page):
        """Give widget mocks the real explicit-open callback and view state."""
        page.page = "notifications"
        page.closed = False
        page.busy = False
        page._ricepop_open_pending = False
        page._open_ricepop_inbox = lambda: (
            settings.RiceSpiceWindow._open_ricepop_inbox(page))

    def setUp(self):
        # Unit tests inject the verified D-Bus owner rather than contacting
        # the developer's real user session. Negative ownership tests below
        # override this verifier and require fail-closed behavior.
        def owned():
            command = notifications.shutil.which("makoctl")
            if command is None:
                raise notifications.NotificationBridgeError("Mako is missing")
            return (command, 7)

        patcher = mock.patch.object(notifications, "_mutation_host", side_effect=owned)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_mako_json_duplicate_keys_fail_closed_before_action_selection(self):
        # A last-key-wins JSON parser could silently retarget a displayed
        # notification ID or replace its action label. Both Mako transports
        # must reject duplicate keys at every object nesting level.
        data = [
            (notifications._records,
             b'[{"id":12,"id":13,"summary":"hello"}]'),
            (notifications._records,
             b'[{"id":12,"actions":{"open":"Open","open":"Other"}}]'),
            (notifications._busctl_records,
             b'{"type":"aa{sv}","type":"a{sv}","data":[[]]}'),
            (notifications._busctl_records,
             b'{"type":"aa{sv}","data":[[{"id":{"type":"u","data":12},'
             b'"id":{"type":"u","data":13}}]]}'),
            (notifications._busctl_records,
             b'{"type":"aa{sv}","data":[[{"id":{"type":"u","data":12},'
             b'"actions":{"type":"a{ss}","data":{"open":"Open","open":"Other"}}}]]}'),
        ]
        for parser, raw in data:
            with self.subTest(parser=parser.__name__, raw=raw[:45]):
                with self.assertRaises(notifications.NotificationBridgeError) as caught:
                    parser(raw, include_actions=True)
                self.assertEqual(caught.exception.code, "invalid_notification_response")

        # Normal legacy busctl and modern mako JSON remain accepted.
        row = {"id": 12, "summary": "Ready", "body": "Completed",
               "app_name": "Files", "urgency": "normal",
               "actions": {"open": "Open"}}
        modern, limited = notifications._records(
            json.dumps([row]).encode(), include_actions=True)
        self.assertFalse(limited)
        self.assertEqual(modern[0]["id"], 12)
        legacy, limited = notifications._busctl_records(
            _legacy_busctl([{**row, "urgency": 1}]), include_actions=True)
        self.assertFalse(limited)
        self.assertEqual(legacy[0]["actions"], [{"key": "open", "label": "Open"}])

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
        # RiceSpice now finishes dynamic view insertion via a bounded
        # viewport relayout helper; the fake must model that UI contract.
        page._show_content = page.content.show_all
        page.show_page = lambda name: statuses.append("page:" + name)

        def button(title, callback, **_options):
            controls[title] = callback

        page._button = button
        page._notification_appearance = lambda: None
        self._bind_inbox_open(page)

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

    def test_owner_verified_inbox_fail_closed_on_foreign_or_restarted_bus(self):
        active = [{"id": 2, "summary": "Private", "body": "Never log this",
                   "app_name": "Mail", "actions": []}]
        history = [{"id": 1, "summary": "Done", "app_name": "Mail"}]
        with mock.patch.object(notifications, "_mutation_host",
                               return_value=("makoctl", 7)) as owner, \
             mock.patch.object(notifications, "_read_mako", side_effect=[
                 (active, False), (history, False)]) as read:
            snapshot = notifications.inspect_owned()
            self.assertEqual(snapshot["active"], active)
            self.assertEqual(snapshot["history"], history)
            self.assertEqual(snapshot["owner_pid"], 7)
            self.assertEqual(owner.call_count, 2)
            self.assertEqual(read.call_count, 2)
            self.assertTrue(snapshot["read_only"])
        with mock.patch.object(notifications, "_mutation_host",
                               side_effect=[("makoctl", 7), ("makoctl", 8)]), \
             mock.patch.object(notifications, "_read_mako", side_effect=[
                 (active, False), (history, False)]):
            with self.assertRaises(notifications.NotificationBridgeError) as error:
                notifications.inspect_owned()
            self.assertEqual(error.exception.code, "notification_host_changed")
        with mock.patch.object(notifications, "_mutation_host", side_effect=
                               notifications.NotificationBridgeError(
                                   "Not this session", "notification_host_unverified")), \
             mock.patch.object(notifications, "_read_mako") as read:
            with self.assertRaises(notifications.NotificationBridgeError):
                notifications.inspect_owned()
            read.assert_not_called()

    def test_ricespice_inbox_actions_are_explicit_accessible_and_history_read_only(self):
        texts, buttons, pages = [], {}, []
        page = SimpleNamespace()
        page._text = lambda message, **_kw: texts.append(message)
        page._button = lambda label, callback, **_kw: buttons.setdefault(label, callback)
        page._show_content = lambda: pages.append("relayout")
        page._background = lambda work, done: done(work())
        page.show_page = pages.append
        page._render_notification_inbox = (
            lambda snap: settings.RiceSpiceWindow._render_notification_inbox(page, snap))
        page._ricepop_owner_epoch = 0
        page._request_ricepop_inbox = (
            lambda: settings.RiceSpiceWindow._request_ricepop_inbox(page))
        self._bind_inbox_open(page)
        snapshot = {
            "active": [{"id": 12, "app_name": "Files", "summary": "Upload done",
                        "body": "Uploaded safely", "actions": [
                            {"key": "open", "label": "Open file"}]}],
            "history": [{"id": 9, "app_name": "Mail", "summary": "Old message",
                         "body": "Not actionable"}], "truncated": False,
            "owner_pid": 7,
        }
        settings.RiceSpiceWindow._render_notification_inbox(page, snapshot)
        self.assertIn("Active notifications (1)", texts)
        self.assertIn("Previous notifications (1)", texts)
        self.assertIn("Mail · Old message", texts)
        self.assertIn("Dismiss · Files · #12", buttons)
        self.assertIn("Open file · Files · #12", buttons)
        self.assertNotIn("Dismiss · Mail · #9", buttons)
        self.assertNotIn("Open file · Mail · #9", buttons)
        self.assertIn("relayout", pages)
        with mock.patch.object(notifications, "dismiss", return_value={"ok": True}) as dismiss, \
             mock.patch.object(notifications, "invoke", return_value={"ok": True}) as invoke, \
             mock.patch.object(notifications, "inspect_owned",
                               return_value=snapshot) as refresh:
            buttons["Dismiss · Files · #12"]()
            buttons["Open file · Files · #12"]()
            dismiss.assert_called_once_with(12, expected=snapshot["active"][0],
                                            expected_owner_pid=7)
            invoke.assert_called_once_with(12, "open", expected=snapshot["active"][0],
                                           expected_owner_pid=7)
            self.assertEqual(refresh.call_count, 2)
        self.assertEqual(pages.count("notifications"), 0)
        self.assertGreaterEqual(pages.count("relayout"), 3)

    def test_manual_inbox_refresh_replaces_widgets_not_private_history(self):
        # This is a mock GTK container, not a second notification service.
        class Widget:
            def __init__(self, parent, text):
                self.parent, self.text, self.destroyed = parent, text, False
                parent.children.append(self)

            def destroy(self):
                self.destroyed = True
                self.parent.children.remove(self)

        container = SimpleNamespace(children=[])
        container.get_children = lambda: list(container.children)
        controls = {}
        page = SimpleNamespace(content=container)
        page._text = lambda message, **_kw: Widget(container, message)
        page._button = lambda label, callback, **_kw: (
            controls.__setitem__(label, callback), Widget(container, label))[1]
        page._show_content = lambda: None
        page._background = lambda work, done: done(work())
        page._render_notification_inbox = (
            lambda value: settings.RiceSpiceWindow._render_notification_inbox(page, value))
        page._ricepop_owner_epoch = 0
        page._request_ricepop_inbox = (
            lambda: settings.RiceSpiceWindow._request_ricepop_inbox(page))
        self._bind_inbox_open(page)
        first = {"active": [{"id": 12, "app_name": "Mail", "summary": "Before",
                             "body": "Old private text", "urgency": "normal",
                             "actions": []}],
                 "history": [], "owner_pid": 7, "truncated": False}
        second = {"active": [{"id": 13, "app_name": "Mail", "summary": "After",
                              "body": "New private text", "urgency": "normal",
                              "actions": []}],
                  "history": [], "owner_pid": 7, "truncated": False}
        with mock.patch.object(notifications, "inspect_owned",
                               return_value=second) as read:
            page._render_notification_inbox(first)
            read.assert_not_called()
            old = tuple(container.children)
            self.assertIn("Dismiss · Mail · #12", controls)
            controls["Refresh RicePop inbox"]()
            read.assert_called_once_with()
        self.assertTrue(all(widget.destroyed for widget in old))
        self.assertFalse(any("Old private text" in widget.text
                             for widget in container.children))
        self.assertTrue(any("New private text" in widget.text
                            for widget in container.children))
        self.assertEqual(sum(widget.text == "Refresh RicePop inbox"
                             for widget in container.children), 1)
        self.assertFalse(any(widget.text == "Dismiss · Mail · #12"
                             for widget in container.children))
        self.assertTrue(any(widget.text == "Dismiss · Mail · #13"
                            for widget in container.children))
        self.assertEqual(len(page._ricepop_inbox_widgets), len(container.children))

    def test_inbox_refresh_preserves_only_verified_keyboard_focus(self):
        # A real GTK Button exposes is_focus/grab_focus. Model the complete
        # transient container lifecycle without a display server.
        class Widget:
            def __init__(self, parent, text):
                self.parent, self.text = parent, text
                self.focused = self.destroyed = False
                parent.children.append(self)

            def is_focus(self):
                return self.focused

            def grab_focus(self):
                for item in self.parent.children:
                    item.focused = False
                self.focused = True

            def destroy(self):
                self.destroyed = True
                self.parent.children.remove(self)

        container = SimpleNamespace(children=[])
        container.get_children = lambda: list(container.children)
        page = SimpleNamespace(content=container, page="notifications")
        page._text = lambda message, **_kw: Widget(container, message)
        page._button = lambda label, _cb, **_kw: Widget(container, label)
        page._show_content = lambda: None
        page._request_ricepop_inbox = lambda: None
        self._bind_inbox_open(page)
        page._render_notification_inbox = (
            lambda value: settings.RiceSpiceWindow._render_notification_inbox(page, value))

        original = {"owner_pid": 18, "truncated": False, "history": [], "active": [{
            "id": 12, "summary": "Original", "body": "Private A",
            "app_name": "Mail", "urgency": "normal",
            "actions": [{"key": "open", "label": "Open"}],
        }]}
        def button(label):
            return next(item for item in container.children if item.text == label)

        page._render_notification_inbox(original)
        first = button("Open · Mail · #12")
        first.grab_focus()
        page._render_notification_inbox(original)
        second = button("Open · Mail · #12")
        self.assertTrue(first.destroyed)
        self.assertIsNot(first, second)
        self.assertTrue(second.focused, "same verified action keeps keyboard focus")

        # The same ID/key/text cannot carry focus onto a newly advertised
        # action with different user-visible meaning.
        second.grab_focus()
        relabeled = {**original, "active": [{**original["active"][0], "actions": [
            {"key": "open", "label": "Delete"}]}]}
        page._render_notification_inbox(relabeled)
        self.assertFalse(button("Delete · Mail · #12").focused)
        self.assertTrue(button("Refresh RicePop inbox").focused)

        # Even the same ID and action label cannot transfer focus if the
        # notification body changed: it could be a different message.
        button("Delete · Mail · #12").grab_focus()
        changed = {**relabeled, "active": [{**relabeled["active"][0], "body": "Private B"}]}
        page._render_notification_inbox(changed)
        self.assertFalse(button("Delete · Mail · #12").focused)
        self.assertTrue(button("Refresh RicePop inbox").focused)

        # A newly verified host must not inherit old action focus even when
        # its notification ID and visible text happen to match.
        current = button("Dismiss · Mail · #12")
        current.grab_focus()
        different_owner = {**changed, "owner_pid": 19}
        page._render_notification_inbox(different_owner)
        self.assertFalse(button("Dismiss · Mail · #12").focused)
        self.assertTrue(button("Refresh RicePop inbox").focused)

        page._ricepop_signals = None
        page._ricepop_dirty = True
        settings.RiceSpiceWindow._stop_ricepop_signals(page)
        self.assertEqual(page._ricepop_focus_buttons, {})

    def test_ricespice_inbox_is_not_read_until_user_requests_it(self):
        controls, seen = {}, []
        page = SimpleNamespace()
        page._text = lambda *_args, **_kwargs: None
        page._state = lambda *_args: None
        page._button = lambda label, cb, **_kwargs: controls.setdefault(label, cb)
        page._show_content = lambda: None
        page._notification_appearance = lambda: None
        page._render_notification_inbox = seen.append
        page._ricepop_owner_epoch = 0
        page._request_ricepop_inbox = (
            lambda: settings.RiceSpiceWindow._request_ricepop_inbox(page))
        self._bind_inbox_open(page)
        page._background = lambda work, done: done(work())
        page.show_page = lambda *_args: None
        with mock.patch.object(notifications, "dnd_status",
                               return_value={"do_not_disturb": False}), \
             mock.patch.object(notifications, "inspect_owned",
                               return_value={"active": [], "history": [],
                                             "truncated": False}) as read:
            settings.RiceSpiceWindow._notifications(page)
            read.assert_not_called()
            self.assertEqual(seen, [])
            controls["Show RicePop inbox"]()
            read.assert_called_once_with()
            self.assertEqual(len(seen), 1)

    def test_reads_mako_live_and_history_without_replaying_actions(self):
        active = [{"id": 12, "summary": "Download", "body": "Finished",
                   "app_name": "Files", "urgency": 1,
                   "actions": {"dangerous": "Delete file"}}]
        finished = [{"id": 13, "summary": "Mail", "body": "Private message",
                     "app_name": "Mail", "urgency": 0}]
        def fake_run(args, **options):
            self.assertEqual(args[:4], ["/usr/bin/busctl", "--user", "--json=short", "call"])
            self.assertEqual(args[4:7], ["org.freedesktop.Notifications",
                                         "/fr/emersion/Mako", "fr.emersion.Mako"])
            self.assertTrue(options["capture_output"])
            return subprocess.CompletedProcess(args, 0,
                   _legacy_busctl(active if args[-1] == "ListNotifications" else finished), b"")
        with mock.patch("macrice.de.notifications.shutil.which", return_value="/usr/bin/busctl"), \
             mock.patch("macrice.de.notifications.subprocess.run", side_effect=fake_run):
            result = notifications.inspect()
        self.assertTrue(result["read_only"])
        self.assertFalse(result["mutates_active_desktop"])
        self.assertFalse(result["actions_replayed"])
        self.assertEqual(result["active"][0]["summary"], "Download")
        self.assertEqual(result["active"][0]["urgency"], "normal")
        self.assertEqual(result["active"][0]["actions"],
                         [{"key": "dangerous", "label": "Delete file"}])
        self.assertNotIn("actions", result["history"][0])
        self.assertEqual(result["history"][0]["id"], 13)

    def test_real_mako_unknown_urgency_is_not_falsely_critical_or_unavailable(self):
        # Mako 1.11 stores a notification without an urgency hint as -1;
        # its aa{sv} D-Bus wire type is byte, hence value 255. A regular
        # application can legitimately omit the hint; it must not make the
        # entire private inbox disappear or be labeled critical.
        row = {"id": 31, "summary": "Unspecified urgency", "urgency": 255,
               "actions": {"open": "Open"}}
        entries, limited = notifications._busctl_records(
            _legacy_busctl([row]), include_actions=True)
        self.assertFalse(limited)
        self.assertEqual(entries[0]["urgency"], "unknown")
        self.assertEqual(entries[0]["actions"], [{"key": "open", "label": "Open"}])
        # Never accept arbitrary out-of-contract byte values as normal.
        for invalid in (3, 9, 254, -1, "255", True):
            with self.subTest(invalid=invalid):
                with self.assertRaises(notifications.NotificationBridgeError):
                    notifications._busctl_records(
                        _legacy_busctl([{**row, "urgency": invalid}]),
                        include_actions=True)

    def test_legacy_busctl_inventory_refuses_typed_schema_confusion(self):
        good = [{"id": 3, "summary": "A", "urgency": 2,
                 "actions": {"reply": "Reply"}}]
        items, truncated = notifications._busctl_records(_legacy_busctl(good),
                                                          include_actions=True)
        self.assertFalse(truncated)
        self.assertEqual(items[0]["urgency"], "critical")
        self.assertEqual(items[0]["actions"], [{"key": "reply", "label": "Reply"}])
        for bad in (
                {}, {"type": "aa{sv}", "data": []},
                {"type": "aa{sv}", "data": [{"id": {"type": "u", "data": 3}}]},
                {"type": "aa{sv}", "data": [[{"id": {"type": "s", "data": "3"}}]]},
                {"type": "aa{sv}", "data": [[{"id": {"type": "u", "data": True}}]]},
                {"type": "aa{sv}", "data": [[{"id": {"type": "u", "data": 3},
                                                "urgency": {"type": "y", "data": 9}}]]},
                {"type": "aa{sv}", "data": [[{"id": {"type": "u", "data": 3},
                                                "actions": {"type": "a{ss}", "data": []}}]]},
        ):
            with self.subTest(bad=bad), self.assertRaises(notifications.NotificationBridgeError):
                notifications._busctl_records(json.dumps(bad).encode())
        with self.assertRaises(notifications.NotificationBridgeError):
            notifications._busctl_records(b"x" * (128 * 1024 + 1))

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

    def test_nested_private_bus_smoke_keeps_literal_shell_payload(self):
        path = Path(__file__).resolve().parents[1] / "scripts/smoke_wayland_session.sh"
        content = path.read_text(encoding="utf-8")
        embedded = content.split("-- sh -eu -c '", 1)[1].split(
            "' sh \"$project_root\"", 1)[0]
        # A literal apostrophe terminates the enclosing shell argument,
        # even inside a comment; real Wayland smoke must remain executable.
        self.assertNotIn("'", embedded)
        self.assertIn("RICEBOWL_DE_PRIVATE_BUS=1", embedded)
        self.assertIn("RICEBOWL_DE_NESTED=1 XDG_SESSION_DESKTOP=ricebowl", embedded)

    def test_notification_mutations_reject_inherited_bus_and_verify_private_owner(self):
        config = str(session.resources() / "mako.conf")
        for env in (
            {"XDG_SESSION_DESKTOP": "XFCE", "WAYLAND_DISPLAY": "wayland-0"},
            {"XDG_SESSION_DESKTOP": "ricebowl", "RICEBOWL_DE_NESTED": "1",
             "WAYLAND_DISPLAY": "wayland-0"},
            {"XDG_SESSION_DESKTOP": "ricebowl", "RICEBOWL_DE_NESTED": "1",
             "RICEBOWL_DE_PRIVATE_BUS": "0", "WAYLAND_DISPLAY": "wayland-0"},
        ):
            with self.subTest(env=env), mock.patch.dict(os.environ, env, clear=True), \
                 mock.patch.object(notifications.subprocess, "run") as run:
                with self.assertRaises(notifications.NotificationBridgeError):
                    notifications._owned_mako(allow_private_nested=True)
                run.assert_not_called()
        # A genuinely isolated nested D-Bus host may dismiss only its own
        # notifications. DND remains restricted to a full RiceBowl login.
        env = {"XDG_SESSION_DESKTOP": "ricebowl", "RICEBOWL_DE_NESTED": "1",
               "RICEBOWL_DE_PRIVATE_BUS": "1", "WAYLAND_DISPLAY": "wayland-0"}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(notifications.shutil, "which", side_effect=lambda x: x), \
             mock.patch.object(notifications.subprocess, "run", return_value=
                subprocess.CompletedProcess([], 0, b"PID=1245\n", b"")), \
             mock.patch("builtins.open", mock.mock_open(
                 read_data=("/usr/bin/mako\0--config\0" + config + "\0").encode())):
            with self.assertRaises(notifications.NotificationBridgeError):
                notifications._owned_mako()  # DND still rejects nested
            self.assertEqual(
                notifications._owned_mako(allow_private_nested=True), ("makoctl", 1245))

    def test_ricepop_host_must_not_change_between_active_inventory_and_mutation(self):
        active = [{"id": 12, "actions": [{"key": "open", "label": "Open"}]}]
        for kind in ("dismiss", "invoke"):
            with self.subTest(kind=kind), \
                 mock.patch.object(notifications, "_mutation_host",
                                   side_effect=[("makoctl", 42), ("makoctl", 43)]), \
                 mock.patch.object(notifications, "_read_mako",
                                   return_value=(active, False)) as read, \
                 mock.patch.object(notifications.subprocess, "run") as run:
                with self.assertRaises(notifications.NotificationBridgeError) as error:
                    if kind == "dismiss":
                        notifications.dismiss(12)
                    else:
                        notifications.invoke(12, "open")
                self.assertEqual(error.exception.code, "notification_host_changed")
                read.assert_called_once()
                run.assert_not_called()

        with mock.patch.object(notifications, "_mutation_host", side_effect=
                               notifications.NotificationBridgeError("host unavailable")), \
             mock.patch.object(notifications, "_read_mako") as read, \
             mock.patch.object(notifications.subprocess, "run") as run:
            for operation in (lambda: notifications.dismiss(12),
                              lambda: notifications.invoke(12, "open")):
                with self.assertRaises(notifications.NotificationBridgeError):
                    operation()
            read.assert_not_called()
            run.assert_not_called()

    def test_inbox_actions_reject_recycled_id_after_notification_replacement(self):
        # Even when a new notification reuses the same active numeric ID and
        # advertised action, a stale RiceSpice button must never mutate it.
        shown = {"id": 12, "summary": "Original", "body": "Private A",
                 "app_name": "Mail", "urgency": "normal",
                 "actions": [{"key": "open", "label": "Open"}]}
        replaced = {**shown, "body": "Private B"}
        for operation in ("dismiss", "invoke"):
            with self.subTest(operation=operation), \
                 mock.patch.object(notifications, "_mutation_host",
                                   return_value=("makoctl", 22)), \
                 mock.patch.object(notifications, "_read_mako",
                                   return_value=([replaced], False)) as read, \
                 mock.patch.object(notifications.subprocess, "run") as run:
                with self.assertRaises(notifications.NotificationBridgeError) as error:
                    if operation == "dismiss":
                        notifications.dismiss(12, expected=shown, expected_owner_pid=22)
                    else:
                        notifications.invoke(12, "open", expected=shown, expected_owner_pid=22)
                self.assertEqual(error.exception.code, "stale_notification_snapshot")
                read.assert_called_once()
                run.assert_not_called()

    def test_inbox_buttons_reject_mako_restart_before_reading_private_messages(self):
        shown = {"id": 12, "summary": "Original", "body": "",
                 "app_name": "Files", "urgency": "normal"}
        for operation in ("dismiss", "invoke"):
            with self.subTest(operation=operation), \
                 mock.patch.object(notifications, "_mutation_host",
                                   return_value=("makoctl", 34)), \
                 mock.patch.object(notifications, "_read_mako") as read, \
                 mock.patch.object(notifications.subprocess, "run") as run:
                with self.assertRaises(notifications.NotificationBridgeError) as error:
                    if operation == "dismiss":
                        notifications.dismiss(12, expected=shown, expected_owner_pid=33)
                    else:
                        notifications.invoke(12, "open", expected=shown, expected_owner_pid=33)
                self.assertEqual(error.exception.code, "notification_host_changed")
                read.assert_not_called()
                run.assert_not_called()

    def test_current_inbox_action_and_original_cli_contract_remain_functional(self):
        shown = {"id": 12, "summary": "Original", "body": "",
                 "app_name": "Files", "urgency": "normal",
                 "actions": [{"key": "open", "label": "Open"}]}
        with mock.patch.object(notifications, "_mutation_host",
                               return_value=("makoctl", 22)), \
             mock.patch.object(notifications, "_read_mako",
                               return_value=([shown], False)), \
             mock.patch.object(notifications.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0, b"", b"")) as run:
            self.assertTrue(notifications.dismiss(
                12, expected=shown, expected_owner_pid=22)["dismissed"])
            self.assertTrue(notifications.invoke(
                12, "open", expected=shown, expected_owner_pid=22)["invoked"])
            # The legacy explicit CLI-style action remains independently safe.
            self.assertTrue(notifications.dismiss(12)["dismissed"])
            self.assertEqual(run.call_count, 3)
            with self.assertRaises(notifications.NotificationBridgeError) as error:
                notifications.dismiss(12, expected={"id": 12}, expected_owner_pid=22)
            self.assertEqual(error.exception.code, "invalid_notification_snapshot")
            self.assertEqual(run.call_count, 3)

    def test_invoke_rejects_reused_id_and_key_with_changed_action_meaning(self):
        shown = {"id": 12, "summary": "Done", "body": "Finished",
                 "app_name": "Files", "urgency": "normal",
                 "actions": [{"key": "open", "label": "Open"}]}
        changed = {**shown, "actions": [{"key": "open", "label": "Delete"}]}
        with (mock.patch.object(notifications, "_mutation_host",
                                return_value=("makoctl", 22)),
              mock.patch.object(notifications, "_read_mako",
                                return_value=([changed], False)),
              mock.patch.object(notifications.subprocess, "run") as run):
            with self.assertRaises(notifications.NotificationBridgeError) as error:
                notifications.invoke(12, "open", expected=shown, expected_owner_pid=22)
            self.assertEqual(error.exception.code, "stale_notification_snapshot")
            run.assert_not_called()

        # Existing explicit callers that do not supply a GUI action snapshot
        # retain the historical contract: only currently advertised keys work.
        legacy = {key: value for key, value in shown.items() if key != "actions"}
        with (mock.patch.object(notifications, "_mutation_host",
                                return_value=("makoctl", 22)),
              mock.patch.object(notifications, "_read_mako",
                                return_value=([changed], False)),
              mock.patch.object(notifications.subprocess, "run", return_value=
                                subprocess.CompletedProcess([], 0, b"", b"")) as run):
            self.assertTrue(notifications.invoke(
                12, "open", expected=legacy, expected_owner_pid=22)["invoked"])
            run.assert_called_once()

    def test_explicit_dismiss_is_id_scoped_and_never_invokes_actions(self):
        calls = []
        def fake_run(args, **options):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, b"", b"")
        with mock.patch("macrice.de.notifications.shutil.which", return_value="/usr/bin/makoctl"), \
             mock.patch.object(notifications, "_read_mako", return_value=([{"id": 12}], False)) as read, \
             mock.patch("macrice.de.notifications.subprocess.run", side_effect=fake_run):
            result = notifications.dismiss(12)
        self.assertTrue(result["dismissed"])
        self.assertTrue(result["mutates_active_desktop"])
        self.assertFalse(result["actions_replayed"])
        read.assert_called_once_with("ListNotifications", include_actions=False)
        self.assertEqual(calls, [["/usr/bin/makoctl", "dismiss", "-n", "12"]])

    def test_dismiss_rejects_ids_not_currently_visible_and_all_invalid_values(self):
        for value in (True, False, -1, 0, 2**32, "12", None):
            with self.subTest(value=value):
                with self.assertRaises(notifications.NotificationBridgeError):
                    notifications.dismiss(value)
        with mock.patch("macrice.de.notifications.shutil.which", return_value="makoctl"), \
             mock.patch.object(notifications, "_read_mako", return_value=([{"id": 12}], False)) as read:
            with self.assertRaises(notifications.NotificationBridgeError) as ctx:
                notifications.dismiss(13)
        self.assertEqual(ctx.exception.code, "notification_not_found")
        read.assert_called_once()

    def test_dismiss_fails_closed_on_truncation_backend_error_and_timeout(self):
        with mock.patch("macrice.de.notifications.shutil.which", return_value="makoctl"), \
             mock.patch.object(notifications, "_read_mako", return_value=([{"id": 5}], True)) as read:
            with self.assertRaises(notifications.NotificationBridgeError) as ctx:
                notifications.dismiss(5)
        self.assertEqual(ctx.exception.code, "ambiguous_notification_id")
        read.assert_called_once()
        with mock.patch("macrice.de.notifications.shutil.which", return_value="makoctl"), \
             mock.patch.object(notifications, "_read_mako",
                               side_effect=notifications.NotificationBridgeError("timeout")):
            with self.assertRaises(notifications.NotificationBridgeError):
                notifications.dismiss(5)

    def test_invoke_requires_fresh_exact_action_from_active_entry(self):
        calls = []
        active = [{"id": 12, "summary": "Install", "actions": {
            "default": "Open", "reply": "Reply"}}]

        def fake_run(args, **options):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, b"", b"")

        with mock.patch("macrice.de.notifications.shutil.which", return_value="makoctl"), \
             mock.patch.object(notifications, "_read_mako", return_value=(
                 [{"id": 12, "actions": [{"key": "default", "label": "Open"},
                                          {"key": "reply", "label": "Reply"}]}], False)) as read, \
             mock.patch("macrice.de.notifications.subprocess.run", side_effect=fake_run):
            result = notifications.invoke(12, "reply")
            self.assertTrue(result["invoked"])
            self.assertTrue(result["mutates_active_desktop"])
            self.assertEqual(calls, [["makoctl", "invoke", "-n", "12", "--", "reply"]])
            read.assert_called_once_with("ListNotifications", include_actions=True)
            calls.clear()
            with self.assertRaises(notifications.NotificationBridgeError) as ctx:
                notifications.invoke(12, "hidden-action")
            self.assertEqual(ctx.exception.code, "notification_action_not_found")
            self.assertEqual(len(calls), 0)

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
             mock.patch.object(notifications, "_read_mako", return_value=([
                 {"id": 7, "actions": [{"key": "reply", "label": "Reply"}]},
                 {"id": 7, "actions": [{"key": "reply", "label": "Reply"}]}], False)):
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
