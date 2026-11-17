#!/usr/bin/env python3
"""Real GTK RicePop recovery through a real Mako 1.11 kill/restart.

The caller MUST be the disposable labwc/dbus-run-session owned by RiceBowl's
headless smoke. No desktop notifications or processes outside that isolated
session may be touched. The real supervisor, actual GTK inbox callbacks and
owner-verified action bridge are exercised end to end.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from macrice.de import notifications
from macrice.de.settings import RiceSpiceWindow, _gtk_modules

MARKER = "RicePop recovery same-message identity"
BODY = "Same message, new Mako owner — no stale action"
APPLICATION = "RiceBowl recovery test"


def require_private_session() -> None:
    expected = {
        "RICEBOWL_DE_PRIVATE_BUS": "1",
        "RICEBOWL_DE_NESTED": "1",
        "RICEBOWL_SMOKE_MAKO_MODERN": "1",
        "RICEBOWL_SMOKE_RECOVERY": "1",
        "XDG_SESSION_DESKTOP": "ricebowl",
    }
    for key, value in expected.items():
        if os.environ.get(key) != value:
            raise RuntimeError("RicePop recovery requires disposable CI-only session")
    if not os.environ.get("WAYLAND_DISPLAY") or not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        raise RuntimeError("RicePop recovery cannot run without isolated Wayland/D-Bus")


def notify() -> None:
    sent = subprocess.run(
        ["notify-send", "--app-name=" + APPLICATION, "--expire-time=30000",
         MARKER, BODY],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=5, check=False)
    if sent.returncode:
        raise RuntimeError("Could not deliver private RicePop recovery test notification")


def pump(glib) -> None:
    context = glib.MainContext.default()
    while context.pending():
        context.iteration(False)


def await_state(glib, condition, message: str, seconds: float = 8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        pump(glib)
        if condition():
            return
        time.sleep(0.025)
    raise RuntimeError("RicePop recovery timeout: " + message)


def dismiss_buttons(view) -> dict:
    return {key: button for key, button in view._ricepop_focus_buttons.items()
            if key[0] == "dismiss"}


def verified_host():
    try:
        return notifications._owned_mako(allow_private_nested=True)[1]
    except notifications.NotificationBridgeError:
        return None


def read_row(pid):
    inbox = notifications.inspect_owned()
    if inbox.get("owner_pid") != pid:
        raise RuntimeError("RicePop owner mismatch during recovery")
    rows = [row for row in inbox["active"] if row["summary"] == MARKER]
    if len(rows) != 1:
        raise RuntimeError("Expected exactly one current recovery notification")
    return rows[0]


def kill_verified_mako(pid):
    if not isinstance(pid, int) or pid <= 1 or pid == os.getpid():
        raise RuntimeError("Unsafe Mako recovery victim")
    # Revalidate that the target still owns THIS disposable notification bus,
    # and is the supervisor's executable/config before sending SIGKILL.
    if verified_host() != pid:
        raise RuntimeError("Mako owner changed before controlled crash")
    os.kill(pid, signal.SIGKILL)


def visible_labels(gtk, view):
    return [item.get_text() for item in view._ricepop_inbox_widgets
            if isinstance(item, gtk.Label)]


def main() -> None:
    require_private_session()
    Gtk, Gdk, GLib = _gtk_modules()
    Gtk.init([])
    old_pid = verified_host()
    if old_pid is None:
        raise RuntimeError("No verified Mako host in private labwc")

    # A real RiceSpice GTK page, not a fake watcher or a synthetic signal peer.
    view = RiceSpiceWindow(Gtk, Gdk, GLib, page="notifications")
    rendered = []
    original = view._render_notification_inbox

    def observe(snapshot):
        original(snapshot)
        rendered.append({
            "owner": snapshot.get("owner_pid"),
            "down": snapshot.get("unavailable") is True,
            "summaries": tuple(row["summary"] for row in snapshot["active"]),
            "focus": next((key for key, button in view._ricepop_focus_buttons.items()
                           if button.is_focus()), None),
            "labels": tuple(visible_labels(Gtk, view)),
        })

    view._render_notification_inbox = observe
    try:
        await_state(GLib, lambda: not view.busy, "initial DND status")
        notify()
        view._open_ricepop_inbox()
        await_state(GLib, lambda: any(k[0] == "dismiss" and k[1] == old_pid
                        and k[4] == MARKER for k in dismiss_buttons(view)),
                    "explicit initial inbox display")
        if view._ricepop_signals is None:
            raise RuntimeError("Real GTK inbox never subscribed to Mako")
        old = read_row(old_pid)
        old_key = next(k for k in dismiss_buttons(view)
                       if k[1] == old_pid and k[4] == MARKER)
        old_button = view._ricepop_focus_buttons[old_key]
        old_button.grab_focus()
        await_state(GLib, old_button.is_focus, "focus initial private action")
        previous_epoch = view._ricepop_owner_epoch

        # A real SIGKILL should result in owner disappearance. The GUI must
        # drop old content immediately without confusing outage with empty.
        kill_verified_mako(old_pid)
        await_state(GLib, lambda: any(s["down"] for s in rendered)
                    and view._ricepop_owner_epoch > previous_epoch,
                    "actual owner loss / private row invalidation")
        down = next(s for s in rendered if s["down"])
        if (MARKER in down["summaries"]
                or any(MARKER in text for text in down["labels"])
                or not any("disconnected" in label.lower()
                           for label in down["labels"])):
            raise RuntimeError("RicePop still exposes stale or misleading inbox after crash")
        if not down["focus"] or down["focus"] != ("refresh",):
            raise RuntimeError("RicePop did not restore safe refresh focus after crash")

        await_state(GLib, lambda: verified_host() not in (None, old_pid),
                    "supervisor-owned bounded Mako restart", seconds=10)
        new_pid = verified_host()
        await_state(GLib, lambda: view._ricepop_owner_epoch >= previous_epoch + 2,
                    "real notification owner reacquisition")
        # Use the SAME notification content across PID change. It is unsafe to
        # accept a recycled ID or just compare on-screen labels.
        notify()
        await_state(GLib, lambda: any(k[0] == "dismiss" and k[1] == new_pid
                        and k[4] == MARKER for k in dismiss_buttons(view)),
                    "automatic live inbox refresh after new-owner notification")
        fresh = read_row(new_pid)
        if new_pid == old_pid or old_button.get_parent() is not None:
            raise RuntimeError("RicePop retained an obsolete GTK action after recovery")
        try:
            notifications.dismiss(old["id"], expected=old,
                                  expected_owner_pid=old_pid)
        except notifications.NotificationBridgeError as exc:
            if exc.code != "notification_host_changed":
                raise RuntimeError("Stale action rejected for wrong reason") from exc
        else:
            raise RuntimeError("Old-owner RicePop action mutated new-owner message")
        if read_row(new_pid)["id"] != fresh["id"]:
            raise RuntimeError("Stale action unexpectedly changed current notification")
        refresh = view._ricepop_focus_buttons.get(("refresh",))
        if refresh is None or not refresh.is_focus():
            raise RuntimeError("Recovered inbox restored stale action focus")

        # The existing session policy is deliberately bounded to one retry.
        # After the second crash, no phantom messages or fake 'empty' state.
        before = view._ricepop_owner_epoch
        kill_verified_mako(new_pid)
        await_state(GLib, lambda: view._ricepop_owner_epoch > before
                    and any(s["down"] and s["owner"] is None
                            for s in rendered[-3:]),
                    "second crash invalidation")
        last = rendered[-1]
        if MARKER in last["summaries"] or any(MARKER in x for x in last["labels"]):
            raise RuntimeError("Second owner loss resurrected private GTK rows")
        await_state(GLib, lambda: not view.busy, "settle failed owner verification")
        # No new daemon should appear: _OptionalService retries only once.
        stop = time.monotonic() + 1.0
        while time.monotonic() < stop:
            pump(GLib)
            if verified_host() is not None:
                raise RuntimeError("RiceBowl restarted a failed Mako more than once")
            time.sleep(0.025)
        if ("refresh",) not in view._ricepop_focus_buttons:
            raise RuntimeError("RicePop lost its manual recovery control")
        print("RicePop real Mako crash -> private GTK clear/focus -> bounded "
              "restart -> live inbox -> stale-ID rejection -> fail-closed: pass")
    finally:
        view._stop_ricepop_signals()
        view.executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"RicePop live recovery smoke failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
