#!/usr/bin/env python3
"""Real GDBus transport check for the Mako 1.11+ notification-change contract.

A disposable dbus-run-session owns a synthetic org.freedesktop.Notifications
name here. This is deliberately NOT an assertion that Ubuntu's Mako 1.8
emitted the new signal, or that real Mako 1.11 is installed. It proves that
RicePop's production subscription receives and filters the wire protocol.
The separate labwc/Mako smoke checks the actual legacy NotificationClosed.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from macrice.de.notification_watch import InboxSignals

NAME = "org.freedesktop.Notifications"
MAKO = "/fr/emersion/Mako"
DBUS = "org.freedesktop.DBus"
DBUS_PATH = "/org/freedesktop/DBus"
PROPS = "org.freedesktop.DBus.Properties"


def wait_for(predicate, *, seconds=3):
    context = GLib.MainContext.default()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        if predicate():
            return
        time.sleep(0.01)
    raise RuntimeError("RicePop did not receive expected private D-Bus signal")


def request(connection, member, flags=0):
    reply = connection.call_sync(
        DBUS, DBUS_PATH, DBUS, member, GLib.Variant("(su)", (NAME, flags))
        if member == "RequestName" else GLib.Variant("(s)", (NAME,)),
        GLib.VariantType.new("(u)"), Gio.DBusCallFlags.NONE, 5000, None)
    return reply.unpack()[0]


def main():
    address = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    if not address:
        raise RuntimeError("Run this smoke only in a private dbus-run-session")
    # Different client from the production watcher: test the actual bus
    # routing/owner mapping, not an in-process mock or direct callback.
    sender = Gio.DBusConnection.new_for_address_sync(
        address,
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
        | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
        None, None)
    try:
        if request(sender, "RequestName") != 1:
            raise RuntimeError("The isolated notification name was not acquired")
        observed = []
        watcher = InboxSignals(Gio, observed.append)
        try:
            def emit(interface="fr.emersion.Mako", changed=None, invalidated=()):
                sender.emit_signal(
                    None, MAKO, PROPS, "PropertiesChanged",
                    GLib.Variant("(sa{sv}as)",
                        (interface, changed or {}, list(invalidated))))

            # Drain GDBus owner resolution and rule registration first.
            wait_for(lambda: True)
            emit(changed={"Modes": GLib.Variant("as", ["default"])})
            # This mode-only update must never reveal/read notification data.
            for _ in range(12):
                GLib.MainContext.default().iteration(False) if (
                    GLib.MainContext.default().pending()) else time.sleep(0.01)
            if observed:
                raise RuntimeError("RicePop reacted to an unrelated property")

            emit(changed={"Notifications": GLib.Variant("s", "synthetic")})
            wait_for(lambda: observed == ["changed"])
            emit(invalidated=("Notifications",))
            wait_for(lambda: observed == ["changed", "changed"])

            # Old Mako owner is gone. The view must invalidate old private
            # content before a new owner can expose any verified snapshot.
            if request(sender, "ReleaseName") != 1:
                raise RuntimeError("Could not release the synthetic owner")
            wait_for(lambda: observed == ["changed", "changed", "owner"])
        finally:
            watcher.close()
        # A view closed after navigation must have no live subscriptions.
        before = tuple(observed)
        if request(sender, "RequestName") != 1:
            raise RuntimeError("Could not reacquire synthetic owner")
        sender.emit_signal(
            None, MAKO, PROPS, "PropertiesChanged",
            GLib.Variant("(sa{sv}as)",
                         ("fr.emersion.Mako",
                          {"Notifications": GLib.Variant("s", "synthetic")}, [])))
        for _ in range(12):
            context = GLib.MainContext.default()
            while context.pending():
                context.iteration(False)
            time.sleep(0.01)
        if tuple(observed) != before:
            raise RuntimeError("RicePop leaked its view-scoped signal subscription")
    finally:
        sender.close_sync(None)
    print("RicePop modern Mako D-Bus property / owner / teardown contract: pass")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, GLib.Error) as exc:
        print(f"RicePop isolated modern signal smoke failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
