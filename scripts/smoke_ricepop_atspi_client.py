#!/usr/bin/env python3
"""External AT-SPI client for the Wayland RicePop GTK accessibility smoke.

Invoked only by the isolated labwc smoke while its parent owns a real mapped
GTK window. Reads exposed accessible object names without private bodies.
"""

from __future__ import annotations

import faulthandler
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
            if depth == 1:
                # Application names only (never bodies): if a later call
                # blocks, the last line says which app was being walked.
                print("DIAG walking app", node.name, file=sys.stderr, flush=True)
            if node.getRole() == pyatspi.ROLE_PUSH_BUTTON and node.name in wanted:
                result.add(node.name)
                if result == wanted:
                    return result
            count = min(node.childCount, 300)
            for i in range(count - 1, -1, -1):
                child = node.getChildAtIndex(i)
                if child is not None:
                    stack.append((child, depth + 1))
        except (LookupError, RuntimeError):
            continue
    return result


def main() -> int:
    # Diagnostic only: if a blocking AT-SPI call outlives the budget, the
    # parent smoke reports the stack instead of a bare "timed out".
    faulthandler.dump_traceback_later(8.5, exit=False)
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
