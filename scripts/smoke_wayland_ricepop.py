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
    dismissed = _command(*LAUNCHER, "notification-dismiss", "--notification-id",
                         str(notification_id), "--json")
    if dismissed.returncode:
        raise RuntimeError(f"RicePop could not dismiss its test notification: {dismissed.stderr[:400]}")
    if json.loads(dismissed.stdout).get("notification_id") != notification_id:
        raise RuntimeError("RicePop dismissed an unexpected notification")
    if any(item["id"] == notification_id for item in _inventory()["active"]):
        raise RuntimeError("Dismissed RicePop notification remained active")
    print("RicePop sent, listed and dismissed a real Mako notification over isolated D-Bus")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print(f"RicePop Wayland smoke failed: {exc}", file=sys.stderr)
        sys.exit(1)
