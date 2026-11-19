"""Optional, view-scoped RicePop inbox updates from the existing Mako D-Bus owner.

This does not start a daemon or read notification text. RiceSpice subscribes
only after the user explicitly opens the owner-verified inbox, unsubscribes on
navigation, and always revalidates host ownership through inspect_owned().
Mako's DBus Notifications property is not emitted for all same-ID
replacements even in 1.11. One low-frequency read-only lease exists ONLY while
the user has the private inbox open, in addition to native D-Bus signals.
Close immediately cancels that lease; no background daemon or action retry.
"""

from __future__ import annotations

from collections.abc import Callable

_BUS = "org.freedesktop.Notifications"
_MAKO_PATH = "/fr/emersion/Mako"
_FDO_PATH = "/org/freedesktop/Notifications"
_DBUS_PATH = "/org/freedesktop/DBus"
# Avoid a persistent poller: only the explicitly revealed GTK inbox creates
# one timeout, and it is removed before any queued private view callback.
_PRIVATE_INBOX_REFRESH_SECONDS = 3


def _gtk_timeout_api():
    try:
        from gi.repository import GLib
    except ImportError:
        return None  # Without GTK the existing manual refresh still works.
    return GLib


def signal_reason(interface: str, member: str, payload: object) -> str | None:
    """Decode only the signal identity, never inspect notification content."""
    if type(payload) is not tuple:
        return None
    if interface == "org.freedesktop.DBus" and member == "NameOwnerChanged":
        if (len(payload) == 3 and payload[0] == _BUS
                and all(type(value) is str for value in payload)
                and payload[1] != payload[2]
                and all(not value or value.startswith(":") for value in payload[1:])):
            return "owner"
    if interface == "org.freedesktop.Notifications" and member == "NotificationClosed":
        if (len(payload) == 2 and all(
                type(value) is int for value in payload)
                and 0 < payload[0] < 2**32 and payload[1] in (1, 2, 3, 4)):
            return "changed"
    if interface == "org.freedesktop.DBus.Properties" and member == "PropertiesChanged":
        if (len(payload) == 3 and payload[0] == "fr.emersion.Mako"
                and type(payload[1]) is dict
                and type(payload[2]) in (list, tuple)
                and all(type(value) is str for value in payload[2])
                and ("Notifications" in payload[1] or "Notifications" in payload[2])):
            return "changed"
    return None


class InboxSignals:
    """View-only D-Bus subscriptions and bounded read refresh; no daemon/storage."""

    def __init__(self, Gio, on_change: Callable[[str], None]) -> None:
        self._connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        if self._connection is None:
            raise RuntimeError("No session bus for RicePop notifications")
        self._ids: list[int] = []
        self._on_change = on_change
        self._timer_api = None
        self._timer_id = 0
        subscriptions = (
            (_BUS, "org.freedesktop.Notifications", "NotificationClosed", _FDO_PATH, None),
            (_BUS, "org.freedesktop.DBus.Properties", "PropertiesChanged", _MAKO_PATH, None),
            ("org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged", _DBUS_PATH, _BUS),
        )
        try:
            for sender, interface, name, path, arg0 in subscriptions:
                ident = self._connection.signal_subscribe(
                    sender, interface, name, path, arg0,
                    Gio.DBusSignalFlags.NONE, self._received, None)
                self._ids.append(ident)
            # Signal subscriptions may miss a same-ID replacement: Mako
            # changes an existing object without inserting/removing it.
            # Only the user-opened inbox has this refresh lease. Callback
            # requests an owner-verified read and never performs a write.
            timer_api = _gtk_timeout_api()
            if timer_api is not None:
                self._timer_api = timer_api
                self._timer_id = timer_api.timeout_add_seconds(
                    _PRIVATE_INBOX_REFRESH_SECONDS, self._readback_tick)
        except Exception:
            self.close()
            raise

    def _readback_tick(self) -> bool:
        if self._connection is None:
            return False
        self._on_change("changed")
        return self._connection is not None

    def _received(self, _connection, _sender, _path, interface, member,
                  parameters, _user_data) -> None:
        try:
            reason = signal_reason(interface, member, parameters.unpack())
        except (AttributeError, TypeError, ValueError):
            return
        if reason is not None:
            self._on_change(reason)

    def close(self) -> None:
        # Revoke the UI callback FIRST. A disconnected or disposed GDBus
        # connection may reject individual unsubscribes; even a queued
        # delivery from a surviving subscription must not outlive the view.
        self._on_change = lambda _reason: None
        timer_api, self._timer_api = self._timer_api, None
        timer_id, self._timer_id = self._timer_id, 0
        if timer_id and timer_api is not None:
            try:
                timer_api.source_remove(timer_id)
            except Exception:
                # Callback lease is already revoked, even if a disposed
                # main context rejects timer removal.
                pass
        connection, self._connection = self._connection, None
        subscriptions, self._ids = self._ids, []
        if connection is None:
            return
        for ident in subscriptions:
            try:
                connection.signal_unsubscribe(ident)
            except Exception:
                # Best-effort transport cleanup: no retry loop, daemon, or
                # private notification text. The callback lease is already
                # revoked and all remaining IDs still get an unsubscribe.
                continue
