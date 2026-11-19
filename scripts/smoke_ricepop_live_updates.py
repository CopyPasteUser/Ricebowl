#!/usr/bin/env python3
"""Real Mako 1.11/labwc RicePop live GTK/AT-SPI integration acceptance.

Runs only in an opt-in disposable RiceBowl compositor and private D-Bus.
Uses the real freedesktop Notify/replace-ID protocol, the real RiceSpice GTK
inbox and a separate AT-SPI client. Nothing is stored or sent to host services.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from macrice.de import notifications
from macrice.de.settings import RiceSpiceWindow, _gtk_modules

APP = "RiceBowl SG3 private CI"
FIRST = "RicePop live first"
SECOND = "RicePop live second"
UPDATED = "RicePop live first updated"
THIRD = "RicePop live third"
BODY = "Synthetic CI-only text: no persistent inbox"


def require_private() -> None:
    markers = {
        "RICEBOWL_DE_PRIVATE_BUS": "1",
        "RICEBOWL_DE_NESTED": "1",
        "RICEBOWL_SMOKE_MAKO_MODERN": "1",
        "RICEBOWL_SMOKE_LIVE": "1",
        "XDG_SESSION_DESKTOP": "ricebowl",
    }
    if any(os.environ.get(key) != value for key, value in markers.items()):
        raise RuntimeError("SG3 live smoke refuses a non-disposable session")
    if not os.environ.get("WAYLAND_DISPLAY") or not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        raise RuntimeError("SG3 live smoke requires private Wayland and D-Bus")


def pump(GLib) -> None:
    context = GLib.MainContext.default()
    while context.pending():
        context.iteration(False)


def until(GLib, predicate, description: str, timeout: float = 7):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        pump(GLib)
        if predicate():
            return
        time.sleep(0.02)
    raise RuntimeError("Timed out waiting for real RicePop " + description)


def dismiss_buttons(view, pid: int) -> dict:
    return {key: button for key, button in view._ricepop_focus_buttons.items()
            if key[0] == "dismiss" and key[1] == pid}


def button_for(view, pid: int, summary: str):
    matches = [(key, button) for key, button in dismiss_buttons(view, pid).items()
               if key[4] == summary]
    return matches[0][1] if len(matches) == 1 else None


def observed_row(pid: int, summary: str):
    result = notifications.inspect_owned()
    if result.get("owner_pid") != pid:
        raise RuntimeError("Mako owner changed during real live test")
    rows = [row for row in result["active"] if row["summary"] == summary]
    if len(rows) != 1:
        raise RuntimeError("Expected one live Mako row: " + summary)
    return rows[0]


def atspi_buttons(GLib, names: list[str]) -> None:
    if len(names) != 2 or len(set(names)) != 2 or any(not name for name in names):
        raise RuntimeError("Real GTK buttons lack distinct accessible names")
    client = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts/smoke_ricepop_atspi_client.py"), *names],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + 9
    try:
        while client.poll() is None and time.monotonic() < deadline:
            pump(GLib)
            time.sleep(0.02)
        if client.poll() is None:
            raise RuntimeError("External real RicePop AT-SPI inspection timed out")
        stdout, stderr = client.communicate(timeout=1)
        if client.returncode:
            raise RuntimeError("External AT-SPI did not find mapped RiceSpice controls: "
                               + stderr[:240])
        if "two distinct RicePop GTK buttons" not in stdout:
            raise RuntimeError("External AT-SPI result did not confirm both controls")
    finally:
        if client.poll() is None:
            client.kill()
            client.wait(timeout=2)


def main() -> None:
    require_private()
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    Gtk, Gdk, _ = _gtk_modules()
    Gtk.init([])
    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    if connection is None:
        raise RuntimeError("No private session bus")
    pid = notifications._owned_mako(allow_private_nested=True)[1]

    def post(summary: str, replace: int = 0):
        reply = connection.call_sync(
            "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
            "org.freedesktop.Notifications", "Notify",
            GLib.Variant("(susssasa{sv}i)",
                         (APP, replace, "", summary, BODY,
                          ["open", "Open synthetic test"], {}, 30000)),
            GLib.VariantType.new("(u)"), Gio.DBusCallFlags.NONE, 5000, None)
        notification_id = reply.unpack()[0]
        if type(notification_id) is not int or notification_id <= 0:
            raise RuntimeError("Real Mako returned an invalid notification ID")
        return notification_id

    first_id = post(FIRST)
    second_id = post(SECOND)
    if first_id == second_id:
        raise RuntimeError("Mako reused an active ID before replacement")

    view = RiceSpiceWindow(Gtk, Gdk, GLib, page="notifications")
    try:
        until(GLib, lambda: not view.busy, "initial GUI status")
        view._open_ricepop_inbox()
        try:
            until(GLib, lambda: button_for(view, pid, FIRST) is not None
                  and button_for(view, pid, SECOND) is not None
                  and view._ricepop_signals is not None,
                  "two real notifications in the mapped GTK inbox")
        except RuntimeError as exc:
            # Counts/IDs only: never print notification text or action bodies.
            actual = notifications.inspect_owned()
            keys = [(key[0], key[1], key[2]) for key in
                    view._ricepop_focus_buttons if len(key) >= 3]
            raise RuntimeError(
                f"{exc}; owner={actual.get('owner_pid') == pid}, "
                f"active_ids={[row['id'] for row in actual['active']]}, "
                f"gui_keys={keys[:8]}, busy={view.busy}, "
                f"watching={view._ricepop_signals is not None}") from exc
        old_record = observed_row(pid, FIRST)
        old_button = button_for(view, pid, FIRST)
        old_button.grab_focus()
        until(GLib, old_button.is_focus, "first GUI action keyboard focus")

        new_id = post(UPDATED, replace=first_id)
        if new_id != first_id:
            raise RuntimeError("Mako replaced a notification with a different ID")
        until(GLib, lambda: button_for(view, pid, UPDATED) is not None
              and button_for(view, pid, FIRST) is None,
              "live same-ID replacement via real Mako PropertiesChanged")
        updated = observed_row(pid, UPDATED)
        if old_button.get_parent() is not None:
            raise RuntimeError("Old GTK action survived same-ID content replacement")
        focus = view._ricepop_focus_buttons.get(("refresh",))
        if focus is None or not focus.is_focus():
            raise RuntimeError("Replaced private action incorrectly retained keyboard focus")
        try:
            notifications.dismiss(first_id, expected=old_record, expected_owner_pid=pid)
        except notifications.NotificationBridgeError:
            pass
        else:
            raise RuntimeError("Stale same-ID action dismissed updated real notification")
        if observed_row(pid, UPDATED)["id"] != updated["id"]:
            raise RuntimeError("Stale action affected the new Mako content")

        third_id = post(THIRD)
        until(GLib, lambda: button_for(view, pid, THIRD) is not None,
              "real Mako addition reflected in the mapped inbox")
        # Different summaries must map to different *actual mapped* GTK
        # accessible actions, discoverable by an external AT-SPI process.
        one = button_for(view, pid, UPDATED)
        three = button_for(view, pid, THIRD)
        atspi_buttons(GLib, [one.get_accessible().get_name(),
                             three.get_accessible().get_name()])

        # Use a real GtkButton signal connected by RiceSpice, not the backend
        # API directly. The live event must invalidate the exact second row.
        dismiss_second = button_for(view, pid, SECOND)
        dismiss_second.clicked()
        until(GLib, lambda: not view.busy
              and button_for(view, pid, SECOND) is None,
              "GTK dismiss signal and Mako close/readback")
        current = notifications.inspect_owned()
        if any(row["id"] == second_id for row in current["active"]):
            raise RuntimeError("GUI dismissal did not remove real Mako notification")
        if not any(row["id"] == third_id for row in current["active"]):
            raise RuntimeError("GUI dismissal removed an unrelated notification")

        # Leaving the inbox revokes private callbacks and renders another page
        # without caching private row widgets or a resident data poller.
        view.show_page("network")
        if view._ricepop_signals is not None or view._ricepop_focus_buttons:
            raise RuntimeError("RicePop retained private GUI actions after navigation")
        print("SG3 real Mako 1.11/labwc: add -> replace same ID -> GTK focus "
              "revocation -> stale action refusal -> external AT-SPI -> GUI "
              "dismiss -> live close -> private navigation cleanup: PASS")
    finally:
        view._stop_ricepop_signals()
        view.executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Only synthetic fixture labels may be printed, never arbitrary Mako
        # bodies or owner-supplied private notification payloads.
        print("SG3 private real Mako live smoke failed: "
              + type(exc).__name__ + ": " + str(exc)[:200], file=sys.stderr)
        raise SystemExit(1)
