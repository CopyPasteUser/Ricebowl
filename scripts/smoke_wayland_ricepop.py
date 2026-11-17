#!/usr/bin/env python3
"""Exercise an actual Mako notification over the private CI Wayland bus.

Called only inside smoke_wayland_session.sh's disposable dbus-run-session.
Never touches the desktop's persistent notification configuration.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = [sys.executable, str(ROOT / "launcher.py"), "de"]
MARKER = "RiceBowl isolated CI notification"


def _command(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, timeout=5, check=False)


def _inventory() -> dict:
    process = _command(*LAUNCHER, "notifications", "--json")
    if process.returncode:
        raise RuntimeError(f"RicePop inventory failed: {process.stderr[:400]}")
    return json.loads(process.stdout)


def main() -> int:
    for _ in range(40):
        result = _command("busctl", "--user", "status", "org.freedesktop.Notifications")
        if result.returncode == 0:
            break
        time.sleep(0.25)
    else:
        raise RuntimeError("Mako never claimed the private notification bus")

    sent = _command("notify-send", "--expire-time=30000", MARKER,
                    "Ubuntu 24.04 Mako 1.8 D-Bus compatibility smoke")
    if sent.returncode:
        raise RuntimeError(f"Unable to deliver test notification: {sent.stderr[:400]}")

    for _ in range(40):
        payload = _inventory()
        matched = [item for item in payload["active"] if item["summary"] == MARKER]
        if matched:
            break
        time.sleep(0.25)
    else:
        raise RuntimeError("Delivered notification never appeared in RicePop inventory")

    if len(matched) != 1 or payload["backend"] != "mako" or not payload["read_only"]:
        raise RuntimeError("Mako inventory returned an ambiguous notification")
    notification_id = matched[0]["id"]

    # Verify the *real* RiceSpice GDBus watcher, rather than testing only its
    # pure signal parser with a fake bus. Mako 1.8 does not announce arrivals,
    # but must deliver freedesktop NotificationClosed on a dismissal.
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gio, GLib, Gtk
    sys.path.insert(0, str(ROOT))
    from macrice.de.notification_watch import InboxSignals
    from macrice.de.settings import _ricepop_set_accessible_name

    # Assert the production GTK3->ATK method on a *real* widget attached to
    # the disposable Wayland display, not only a Python mock.
    Gtk.init([])
    button = Gtk.Button(label="Dismiss · Mail · #3")
    _ricepop_set_accessible_name(button, "Dismiss", "Mail", "Calendar invite")
    if button.get_accessible().get_name() != (
            "Dismiss notification from Mail: Calendar invite"):
        raise RuntimeError("RicePop GTK accessible action name was not applied")
    button.destroy()

    reasons: list[str] = []
    watcher = InboxSignals(Gio, reasons.append)
    try:
        # Process the main context so GDBus subscriptions can be installed
        # before the separate makoctl/CLI client closes this notification.
        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)
        dismissed = _command(*LAUNCHER, "notification-dismiss", "--notification-id",
                             str(notification_id), "--json")
        if dismissed.returncode:
            # CLI errors are structured JSON; never log notification text.
            try:
                failure = json.loads(dismissed.stdout)
                code = failure.get("error", {}).get("code", "unknown")
                if not isinstance(code, str) or len(code) > 64 or not code.isidentifier():
                    code = "invalid_error"
            except (ValueError, TypeError, AttributeError):
                code = "invalid_response"
            raise RuntimeError(
                f"RicePop could not dismiss its isolated notification ({code})")
        if json.loads(dismissed.stdout).get("notification_id") != notification_id:
            raise RuntimeError("RicePop dismissed an unexpected notification")
        deadline = time.monotonic() + 4
        while "changed" not in reasons and time.monotonic() < deadline:
            while context.pending():
                context.iteration(False)
            if "changed" not in reasons:
                time.sleep(0.02)
        if "changed" not in reasons:
            raise RuntimeError("Mako did not deliver NotificationClosed to RicePop GDBus")
    finally:
        watcher.close()

    if any(item["id"] == notification_id for item in _inventory()["active"]):
        raise RuntimeError("Dismissed RicePop notification remained active")
    print("RicePop sent, listed, dismissed and observed real Mako NotificationClosed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print(f"RicePop Wayland smoke failed: {exc}", file=sys.stderr)
        sys.exit(1)
