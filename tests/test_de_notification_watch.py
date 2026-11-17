"""Disposable D-Bus and RiceSpice tests for the opt-in RicePop live inbox."""

import unittest
from types import SimpleNamespace

from macrice.de import notification_watch, notifications, settings


class FakeConnection:
    def __init__(self, fail_at=None):
        self.handlers = {}
        self.unsubscribed = []
        self.fail_at = fail_at

    def signal_subscribe(self, sender, interface, member, path, arg0, flags,
                         callback, user_data):
        next_id = len(self.handlers) + 1
        if next_id == self.fail_at:
            raise RuntimeError("unavailable D-Bus subscription")
        self.handlers[next_id] = (sender, interface, member, path, arg0, callback)
        return next_id

    def signal_unsubscribe(self, ident):
        self.unsubscribed.append(ident)
        self.handlers.pop(ident, None)

    def emit(self, interface, member, payload):
        params = SimpleNamespace(unpack=lambda: payload)
        for _sender, actual_interface, actual_member, path, _arg0, callback in list(
                self.handlers.values()):
            if interface == actual_interface and member == actual_member:
                callback(self, "org.freedesktop.Notifications", path, interface,
                         member, params, None)


def gio(connection):
    return SimpleNamespace(
        BusType=SimpleNamespace(SESSION=3),
        DBusSignalFlags=SimpleNamespace(NONE=0),
        bus_get_sync=lambda _kind, _cancel: connection)


class InboxSignalTests(unittest.TestCase):
    def test_signal_contract_requires_real_notification_update(self):
        detect = notification_watch.signal_reason
        self.assertEqual(detect("org.freedesktop.DBus.Properties",
                                "PropertiesChanged",
                                ("fr.emersion.Mako",
                                 {"Notifications": object()}, [])), "changed")
        self.assertEqual(detect("org.freedesktop.DBus.Properties",
                                "PropertiesChanged",
                                ("fr.emersion.Mako", {}, ["Notifications"])), "changed")
        self.assertIsNone(detect("org.freedesktop.DBus.Properties",
                                 "PropertiesChanged",
                                 ("fr.emersion.Mako", {"Modes": object()}, [])))
        self.assertIsNone(detect("org.freedesktop.DBus.Properties",
                                 "PropertiesChanged",
                                 ("org.other.Host", {"Notifications": object()}, [])))
        self.assertEqual(detect("org.freedesktop.Notifications",
                                "NotificationClosed", (22, 2)), "changed")
        self.assertIsNone(detect("org.freedesktop.Notifications",
                                 "NotificationClosed", (True, 2)))
        self.assertEqual(detect("org.freedesktop.DBus",
                                "NameOwnerChanged",
                                ("org.freedesktop.Notifications", ":1.2", ":1.3")),
                         "owner")
        self.assertIsNone(detect("org.freedesktop.DBus",
                                 "NameOwnerChanged", ("org.unrelated", "", ":1.4")))
        self.assertIsNone(detect("org.freedesktop.DBus",
                                 "NameOwnerChanged", ("org.freedesktop.Notifications",)))
        self.assertIsNone(detect("org.freedesktop.DBus", "NameOwnerChanged",
                                 {"name": "org.freedesktop.Notifications"}))

    def test_subscriptions_are_view_scoped_and_unsubscribed(self):
        bus = FakeConnection()
        reasons = []
        watch = notification_watch.InboxSignals(gio(bus), reasons.append)
        self.assertEqual(len(bus.handlers), 3)
        bus.emit("org.freedesktop.DBus.Properties", "PropertiesChanged",
                 ("fr.emersion.Mako", {"Notifications": object()}, []))
        bus.emit("org.freedesktop.Notifications", "NotificationClosed", (7, 1))
        bus.emit("org.freedesktop.DBus", "NameOwnerChanged",
                 ("org.freedesktop.Notifications", ":1.1", ":1.2"))
        self.assertEqual(reasons, ["changed", "changed", "owner"])
        watch.close()
        watch.close()  # Clean teardown after page switch and window destroy.
        self.assertEqual(bus.unsubscribed, [1, 2, 3])
        self.assertEqual(bus.handlers, {})

    def test_partial_subscribe_failure_unwinds_private_bus_watch(self):
        bus = FakeConnection(fail_at=2)
        with self.assertRaises(RuntimeError):
            notification_watch.InboxSignals(gio(bus), lambda _reason: None)
        self.assertEqual(bus.unsubscribed, [1])
        self.assertEqual(bus.handlers, {})

    def test_owner_handoff_discards_inflight_verified_private_snapshot(self):
        """Late worker replies must never resurrect messages after Mako restart."""
        callbacks, rendered, cleared, statuses = [], [], [], []
        page = SimpleNamespace(
            closed=False, page="notifications", busy=False,
            _ricepop_signals=object(), _ricepop_dirty=False,
            _ricepop_owner_epoch=0, _ricepop_inbox_widgets=(),
            _state=statuses.append,
        )
        page._render_notification_inbox = lambda value: (
            rendered.append(value) if value.get("owner_pid") else cleared.append(value))
        def background(work, done):
            self.assertIs(work, notifications.inspect_owned)
            callbacks.append(done)
            page.busy = True
        page._background = background
        page._request_ricepop_inbox = lambda: (
            settings.RiceSpiceWindow._request_ricepop_inbox(page))
        page._ricepop_try_refresh = lambda: (
            settings.RiceSpiceWindow._ricepop_try_refresh(page))

        old = {"owner_pid": 47, "active": [{"summary": "Old private alert"}],
               "history": [], "truncated": False}
        new = {"owner_pid": 48, "active": [{"summary": "New alert"}],
               "history": [], "truncated": False}
        page._request_ricepop_inbox()
        self.assertEqual(len(callbacks), 1)
        settings.RiceSpiceWindow._ricepop_changed(page, "owner")
        self.assertEqual(page._ricepop_owner_epoch, 1)
        self.assertEqual(rendered, [])
        self.assertEqual(len(cleared), 1)
        self.assertTrue(page._ricepop_dirty)
        # GTK dispatches the old callback after the owner-changed signal.
        callbacks[0](old)
        self.assertEqual(rendered, [], "old owner's private data was repainted")
        page.busy = False
        page._ricepop_try_refresh()
        self.assertEqual(len(callbacks), 2)
        callbacks[1](new)
        self.assertEqual(rendered, [new])
        self.assertFalse(page._ricepop_dirty)

    def test_normal_owner_epoch_allows_explicit_snapshot_and_changes_drop_it(self):
        callbacks, shown = [], []
        page = SimpleNamespace(_ricepop_owner_epoch=2)
        page._background = lambda work, done: callbacks.append(done)
        page._render_notification_inbox = shown.append
        settings.RiceSpiceWindow._request_ricepop_inbox(page)
        callbacks[0]({"owner_pid": 10, "active": []})
        self.assertEqual(len(shown), 1)
        settings.RiceSpiceWindow._request_ricepop_inbox(page)
        page._ricepop_owner_epoch += 1
        callbacks[1]({"owner_pid": 10, "active": []})
        self.assertEqual(len(shown), 1)

    def test_live_inbox_events_coalesce_while_worker_busy(self):
        launches = []
        states = []
        blank = []
        page = SimpleNamespace(
            closed=False, page="notifications", busy=False,
            _ricepop_signals=object(), _ricepop_dirty=False,
            _ricepop_owner_epoch=0,
            _ricepop_inbox_widgets=("private-old",),
            _render_notification_inbox=blank.append,
            _state=states.append,
        )
        def background(work, done):
            self.assertIs(work, notifications.inspect_owned)
            launches.append((work, done))
            page.busy = True
        page._background = background
        page._request_ricepop_inbox = lambda: (
            settings.RiceSpiceWindow._request_ricepop_inbox(page))
        page._ricepop_try_refresh = lambda: (
            settings.RiceSpiceWindow._ricepop_try_refresh(page))
        settings.RiceSpiceWindow._ricepop_changed(page, "changed")
        self.assertEqual(len(launches), 1)
        settings.RiceSpiceWindow._ricepop_changed(page, "changed")
        self.assertTrue(page._ricepop_dirty)
        self.assertEqual(len(launches), 1)
        page.busy = False
        page._ricepop_try_refresh()
        self.assertEqual(len(launches), 2)
        self.assertFalse(page._ricepop_dirty)
        settings.RiceSpiceWindow._ricepop_changed(page, "owner")
        self.assertEqual(blank, [{"active": [], "history": [],
                                  "truncated": False, "owner_pid": None}])
        self.assertTrue(any("host changed" in text for text in states))
        page.page = "audio"
        settings.RiceSpiceWindow._ricepop_changed(page, "changed")
        self.assertEqual(len(launches), 2)
        page.closed = True
        settings.RiceSpiceWindow._ricepop_changed(page, "changed")
        self.assertEqual(len(launches), 2)


if __name__ == "__main__":
    unittest.main()
