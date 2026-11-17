"""Optional, view-scoped RicePop inbox updates from the existing Mako D-Bus owner.

This does not start a daemon or read notification text. RiceSpice subscribes
only after the user explicitly opens the owner-verified inbox, unsubscribes on
navigation, and always revalidates host ownership through inspect_owned().
Older Mako versions lack the Notifications property: manual refresh remains
available for additions, while the standard NotificationClosed signal works.
"""

from __future__ import annotations

from collections.abc import Callable

_BUS = "org.freedesktop.Notifications"
_MAKO_PATH = "/fr/emersion/Mako"
_FDO_PATH = "/org/freedesktop/Notifications"
_DBUS_PATH = "/org/freedesktop/DBus"


def signal_reason(interface: str, member: str, payload: object) -> str | None:
    """Decode only the signal identity, never inspect notification content."""
    if type(payload) is not tuple:
        return None
    if interface == "org.freedesktop.DBus" and member == "NameOwnerChanged":
        if (len(payload) == 3 and payload[0] == _BUS
                and all(type(value) is str for value in payload)):
            return "owner"
    if interface == "org.freedesktop.Notifications" and member == "NotificationClosed":
        if len(payload) == 2 and all(
                type(value) is int and 0 <= value < 2**32 for value in payload):
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
    """GTK-main-context subscriptions; no threads, timers, polling or storage."""

    def __init__(self, Gio, on_change: Callable[[str], None]) -> None:
        self._connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        if self._connection is None:
            raise RuntimeError("No session bus for RicePop notifications")
        self._ids: list[int] = []
        self._on_change = on_change
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
        except Exception:
            self.close()
            raise

    def _received(self, _connection, _sender, _path, interface, member,
                  parameters, _user_data) -> None:
        try:
            reason = signal_reason(interface, member, parameters.unpack())
        except (AttributeError, TypeError, ValueError):
            return
        if reason is not None:
            self._on_change(reason)

    def close(self) -> None:
        connection, self._connection = self._connection, None
        if connection is not None:
            for ident in self._ids:
                connection.signal_unsubscribe(ident)
        self._ids.clear()
        self._on_change = lambda _reason: None
