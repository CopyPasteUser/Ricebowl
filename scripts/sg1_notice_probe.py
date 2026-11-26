#!/usr/bin/env python3
"""Black-box AT-SPI probe for RicePlate's transient failure notice.

Public accessibility bus only. The notice is exposed as an Alert (AT-SPI
Notification role) while it is painted and must disappear when it clears.

  sg1_notice_probe.py present "Application: Could not start" [seconds]
  sg1_notice_probe.py absent  [seconds]

`present` exits 0 once exactly one alert with that exact accessible name
exists, 1 on timeout. `absent` exits 0 once three consecutive samples show no
alert at all. Never prints anything but fixed generic notice text.
"""
from __future__ import annotations

import sys
import time

import pyatspi


def alerts() -> list[str]:
    """Names of every Notification-role node, bounded and strict."""
    root = pyatspi.Registry.getDesktop(0)
    found: list[str] = []
    stack = [(root, 0)]
    visited = 0
    while stack and visited < 900:
        node, depth = stack.pop()
        visited += 1
        try:
            if node.getRole() == pyatspi.ROLE_NOTIFICATION:
                found.append(node.name)
            if depth >= 6:
                continue
            for index in range(min(node.childCount, 200)):
                child = node.getChildAtIndex(index)
                if child is not None:
                    stack.append((child, depth + 1))
        except (LookupError, RuntimeError):
            continue
    return found


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "present" and len(sys.argv) >= 3:
        wanted = sys.argv[2]
        deadline = time.monotonic() + float(sys.argv[3] if len(sys.argv) > 3 else 6)
        seen: list[str] = []
        while time.monotonic() < deadline:
            seen = alerts()
            if seen == [wanted]:
                print(f"PASS: AT-SPI alert {wanted!r}")
                return 0
            time.sleep(0.15)
        print(f"FAIL: wanted alert {wanted!r}, saw {seen!r}", file=sys.stderr)
        return 1
    if mode == "absent":
        deadline = time.monotonic() + float(sys.argv[2] if len(sys.argv) > 2 else 8)
        clear = 0
        seen = []
        while time.monotonic() < deadline:
            seen = alerts()
            clear = clear + 1 if not seen else 0
            if clear >= 3:
                print("PASS: no AT-SPI alert")
                return 0
            time.sleep(0.2)
        print(f"FAIL: alert still exposed: {seen!r}", file=sys.stderr)
        return 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
