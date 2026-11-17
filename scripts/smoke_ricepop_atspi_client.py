#!/usr/bin/env python3
"""External AT-SPI client for the Wayland RicePop GTK accessibility smoke.

Invoked only by the isolated labwc smoke while its parent owns a real mapped
GTK window. Reads exposed accessible object names without private bodies.
"""

from __future__ import annotations

import sys
import time

import pyatspi


def reachable_names(root, wanted):
    result = set()
    stack = [(root, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > 8:
            continue
        try:
            if node.getRole() == pyatspi.ROLE_PUSH_BUTTON and node.name in wanted:
                result.add(node.name)
            count = min(node.childCount, 300)
            for i in range(count - 1, -1, -1):
                child = node.getChildAtIndex(i)
                if child is not None:
                    stack.append((child, depth + 1))
        except (LookupError, RuntimeError):
            continue
    return result


def main() -> int:
    wanted = set(sys.argv[1:])
    if len(wanted) != 2:
        return 2
    until = time.monotonic() + 8
    while time.monotonic() < until:
        observed = reachable_names(pyatspi.Registry.getDesktop(0), wanted)
        if observed == wanted:
            print("AT-SPI found two distinct RicePop GTK buttons")
            return 0
        time.sleep(0.15)
    print("AT-SPI could not discover the real mapped RicePop buttons",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
