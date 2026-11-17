"""Disposable D-Bus and RiceSpice tests for the opt-in RicePop live inbox."""

import threading
import unittest
from concurrent.futures import Future
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
        # Modern Mako 1.11+ uses the same D-Bus PropertiesChanged
        # contract for additions, replacements and invalidations.
        self.assertEqual(detect("org.freedesktop.DBus.Properties",
                                "PropertiesChanged",
                                ("fr.emersion.Mako",
                                 {"Notifications": "synthetic"}, [])), "changed")
        self.assertIsNone(detect("org.freedesktop.Notifications",
                                 "NotificationClosed", (0, 2)))
        self.assertIsNone(detect("org.freedesktop.Notifications",
                                 "NotificationClosed", (12, 99)))
        self.assertIsNone(detect("org.freedesktop.DBus",
                                 "NameOwnerChanged",
                                 ("org.freedesktop.Notifications", ":1.2", ":1.2")))
        self.assertIsNone(detect("org.freedesktop.DBus",
                                 "NameOwnerChanged",
                                 ("org.freedesktop.Notifications", "malformed", ":1.4")))

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
        # A queued callback from the old GTK view must be harmless after
        # owner handoff, navigation or explicit window destruction.
        before = tuple(reasons)
        watch._received(None, "org.freedesktop.Notifications", "/fr/emersion/Mako",
                        "org.freedesktop.DBus.Properties", "PropertiesChanged",
                        SimpleNamespace(unpack=lambda: (
                            "fr.emersion.Mako", {"Notifications": object()}, [])), None)
        self.assertEqual(tuple(reasons), before)

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
                                  "truncated": False, "owner_pid": None,
                                   "unavailable": True}])
        self.assertTrue(any("host changed" in text for text in states))
        page.page = "audio"
        settings.RiceSpiceWindow._ricepop_changed(page, "changed")
        self.assertEqual(len(launches), 2)
        page.closed = True
        settings.RiceSpiceWindow._ricepop_changed(page, "changed")
        self.assertEqual(len(launches), 2)


    def _busy_ricepop_window(self):
        """Exercise the real GTK worker completion path with controlled futures."""
        futures, submitted, idle, rendered, statuses = [], [], [], [], []

        def submit(work):
            submitted.append(work)
            result = Future()
            futures.append(result)
            return result

        page = SimpleNamespace(
            page="notifications", closed=False, busy=False, generation=0,
            _ricepop_signals=None, _ricepop_dirty=False,
            _ricepop_open_pending=False, _ricepop_owner_epoch=0,
            _ricepop_focus_buttons={}, worker_slots=threading.BoundedSemaphore(2),
            executor=SimpleNamespace(submit=submit),
            GLib=SimpleNamespace(idle_add=lambda callback: idle.append(callback)),
            _state=statuses.append, _render_notification_inbox=rendered.append,
        )
        page._background = lambda work, done: settings.RiceSpiceWindow._background(
            page, work, done)
        page._request_ricepop_inbox = lambda: (
            settings.RiceSpiceWindow._request_ricepop_inbox(page))
        page._open_ricepop_inbox = lambda: (
            settings.RiceSpiceWindow._open_ricepop_inbox(page))
        return page, futures, submitted, idle, rendered, statuses

    def test_explicit_inbox_click_while_dnd_read_busy_is_not_lost(self):
        page, futures, submitted, idle, rendered, statuses = self._busy_ricepop_window()
        page._background(lambda: "dnd", lambda result: statuses.append(result))
        self.assertEqual(len(submitted), 1)
        self.assertIsNot(submitted[0], notifications.inspect_owned)

        # Both rapid user clicks coalesce behind the initial DND worker.
        page._open_ricepop_inbox()
        page._open_ricepop_inbox()
        self.assertTrue(page._ricepop_open_pending)
        self.assertEqual(len(submitted), 1)
        self.assertTrue(any("queued" in state for state in statuses))

        futures[0].set_result("dnd")
        idle.pop(0)()
        self.assertEqual(len(submitted), 2)
        self.assertIs(submitted[1], notifications.inspect_owned)
        self.assertFalse(page._ricepop_open_pending)
        self.assertTrue(page.busy)

        private = {"owner_pid": 55, "active": [], "history": [], "truncated": False}
        futures[1].set_result(private)
        idle.pop(0)()
        self.assertEqual(rendered, [private])
        self.assertFalse(page.busy)
        self.assertFalse(idle)

    def test_pending_inbox_open_survives_failed_dnd_read_but_not_navigation(self):
        page, futures, submitted, idle, rendered, states = self._busy_ricepop_window()
        page._background(lambda: "dnd", lambda _value: None)
        page._open_ricepop_inbox()
        futures[0].set_exception(RuntimeError("DND unavailable"))
        idle.pop(0)()
        self.assertEqual(len(submitted), 2)
        self.assertIs(submitted[1], notifications.inspect_owned)
        self.assertTrue(any("DND unavailable" in state for state in states))

        # A page switch cancels the pending work's result via generation.
        page.page = "network"
        page.generation += 1
        settings.RiceSpiceWindow._stop_ricepop_signals(page)
        futures[1].set_result(
            {"owner_pid": 55, "active": [], "history": [], "truncated": False})
        idle.pop(0)()
        self.assertEqual(rendered, [])
        self.assertFalse(page._ricepop_open_pending)

    def test_queued_open_is_cleared_before_busy_worker_returns_on_navigation(self):
        page, futures, submitted, idle, rendered, _states = self._busy_ricepop_window()
        page._background(lambda: "dnd", lambda _value: None)
        page._open_ricepop_inbox()
        page.page = "network"
        page.generation += 1
        settings.RiceSpiceWindow._stop_ricepop_signals(page)
        page._open_ricepop_inbox()  # Unrelated settings never disclose the inbox.
        futures[0].set_result("dnd")
        idle.pop(0)()
        self.assertEqual(len(submitted), 1)
        self.assertEqual(rendered, [])
        self.assertFalse(page._ricepop_open_pending)


if __name__ == "__main__":
    unittest.main()
