#!/usr/bin/env python3
"""Exercise an actual Mako notification over the private CI Wayland bus.

Called only inside smoke_wayland_session.sh's disposable dbus-run-session.
Never touches the desktop's persistent notification configuration.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from unittest import mock
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

    # A second process must discover actual mapped Wayland GTK buttons via
    # the accessibility bus (not just GTK's local ATK object). German action
    # names must be announced distinctly without notification bodies.
    first_name = "Schließen – Benachrichtigung von Mail: Neue Nachricht"
    second_name = "Schließen – Benachrichtigung von Mail: Kalendereinladung"
    window = Gtk.Window(title="RicePop AT-SPI isolated test")
    group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    window.add(group)
    with mock.patch.dict(os.environ, {"LC_ALL": "de_DE.UTF-8"}):
        for summary in ("Neue Nachricht", "Kalendereinladung"):
            control = Gtk.Button(label="Schließen")
            _ricepop_set_accessible_name(control, "Schließen", "Mail", summary)
            group.pack_start(control, True, True, 0)
    window.show_all()
    try:
        candidate = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts/smoke_ricepop_atspi_client.py"),
             first_name, second_name],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        context = GLib.MainContext.default()
        limit = time.monotonic() + 12
        while candidate.poll() is None and time.monotonic() < limit:
            while context.pending():
                context.iteration(False)
            time.sleep(0.015)
        if candidate.poll() is None:
            candidate.kill()
            candidate.communicate(timeout=2)
            raise RuntimeError("External RicePop AT-SPI inspection timed out")
        out, err = candidate.communicate(timeout=2)
        if candidate.returncode:
            raise RuntimeError("External RicePop AT-SPI button inspection failed: "
                               + err[:300])
        print(out.strip())
    finally:
        window.destroy()

    reasons: list[str] = []
    watcher = InboxSignals(Gio, reasons.append)
    try:
        # Process the main context so GDBus subscriptions can be installed
        # before the separate makoctl/CLI client closes this notification.
        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)

        modern_id = None
        if os.environ.get("RICEBOWL_SMOKE_MAKO_MODERN") == "1":
            # This query is against the actual Mako v1.11 process launched
            # by the session supervisor, not a fabricated test-bus peer.
            prop = _command("busctl", "--user", "get-property",
                            "org.freedesktop.Notifications",
                            "/fr/emersion/Mako", "fr.emersion.Mako",
                            "Notifications")
            if prop.returncode:
                raise RuntimeError("Real Mako host does not expose Notifications")
            # The watcher was subscribed before this *new* notification.
            # No close/owner-change has happened yet, so a 'changed' result
            # is proof of the daemon's live arrival PropertiesChanged signal.
            modern_summary = MARKER + " live arrival"
            posted = _command("notify-send", "--expire-time=30000",
                              modern_summary, "Real Mako 1.11 arrival event")
            if posted.returncode:
                raise RuntimeError("Real Mako 1.11 notification delivery failed")
            deadline = time.monotonic() + 4
            while "changed" not in reasons and time.monotonic() < deadline:
                while context.pending():
                    context.iteration(False)
                if "changed" not in reasons:
                    time.sleep(0.02)
            if "changed" not in reasons:
                raise RuntimeError("Real Mako 1.11 did not announce arrival via GDBus")
            received = [row for row in _inventory()["active"]
                        if row["summary"] == modern_summary]
            if len(received) != 1:
                raise RuntimeError("Real Mako 1.11 arrival not visible in RicePop")
            modern_id = received[0]["id"]
            if modern_id == notification_id:
                raise RuntimeError("Mako recycled an active notification ID")
            reasons.clear()

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
    if modern_id is not None:
        # Keep the second source-owned notification scoped to this disposable
        # bus, and require RicePop's existing guarded mutation to remove it.
        second = _command(*LAUNCHER, "notification-dismiss", "--notification-id",
                          str(modern_id), "--json")
        if second.returncode:
            raise RuntimeError("Real Mako 1.11 RicePop cleanup failed")
        if any(item["id"] == modern_id for item in _inventory()["active"]):
            raise RuntimeError("Real Mako 1.11 retained a dismissed notification")
        print("RicePop real Mako 1.11 arrival, inbox and close signals: pass")
    else:
        print("RicePop real Mako 1.8 close signal: pass")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print(f"RicePop Wayland smoke failed: {exc}", file=sys.stderr)
        sys.exit(1)
