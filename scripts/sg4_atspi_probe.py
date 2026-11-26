#!/usr/bin/env python3
"""Black-box AT-SPI client for the riceplate-native application (public bus only).

  sg4_atspi_probe.py dump
      one line per node: DEPTH ROLE NAME [actions=N] [focused]
  sg4_atspi_probe.py has ROLE NAME [SECONDS]      exit 0 once exactly one node matches
  sg4_atspi_probe.py none ROLE NAME [SECONDS]     exit 0 once three samples show none
  sg4_atspi_probe.py noaction ROLE NAME [SECONDS] exactly one match that exposes 0 actions
  sg4_atspi_probe.py act ROLE NAME [SECONDS]      doAction(0) on the one matching node
  sg4_atspi_probe.py focused ROLE NAME [SECONDS]  the matching node has focus
  sg4_atspi_probe.py names ROLE                   print every accessible name of that role

NAME matches the accessible name exactly, or as a prefix when it ends in `*`.
A role is the pyatspi role name ("push button", "menu", "page tab", "dialog",
...) or `*`.
The probe never injects input and never falls back: a missing node, a node
without an action or a refused doAction is a failure.
"""
from __future__ import annotations

import os
import sys
import time

import pyatspi

# The application whose tree is probed; SG4_ATSPI_APP=* probes every application
# (the GTK Creator registers under its program name).
APP = os.environ.get("SG4_ATSPI_APP", "riceplate-native")


def _children(node, limit=300):
    for index in range(min(node.childCount, limit)):
        try:
            child = node.getChildAtIndex(index)
        except (LookupError, RuntimeError):
            continue
        if child is not None:
            yield child


def nodes(maximum=16):
    desktop = pyatspi.Registry.getDesktop(0)
    for app in _children(desktop, 60):
        try:
            if APP != "*" and app.name != APP:
                continue
        except (LookupError, RuntimeError):
            continue
        stack = [(app, 0)]
        visited = 0
        while stack and visited < 8000:
            node, depth = stack.pop()
            visited += 1
            yield node, depth
            if depth < maximum:
                stack.extend((child, depth + 1) for child in _children(node))


def describe(node):
    try:
        action = node.queryAction().nActions
    except (NotImplementedError, LookupError, RuntimeError):
        action = 0
    try:
        focused = node.getState().contains(pyatspi.STATE_FOCUSED)
    except (LookupError, RuntimeError):
        focused = False
    return action, focused


def matching(role, name):
    prefix = name.endswith("*")
    if prefix:
        name = name[:-1]
    found = []
    for node, _ in nodes():
        try:
            if role != "*" and node.getRoleName() != role:
                continue
            title = node.name
        except (LookupError, RuntimeError):
            continue
        if (title.startswith(name) if prefix else title == name):
            found.append(node)
    return found


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    mode = sys.argv[1]
    if mode == "dump":
        count = 0
        for node, depth in sorted_nodes():
            action, focused = describe(node)
            print("  " * depth + f"{node.getRoleName()} {node.name!r}"
                  + (f" actions={action}" if action else "")
                  + (" focused" if focused else ""))
            count += 1
        return 0 if count else 1
    if mode == "names" and len(sys.argv) == 3:
        for node, _ in nodes():
            try:
                if sys.argv[2] == "*" or node.getRoleName() == sys.argv[2]:
                    print(node.name)
            except (LookupError, RuntimeError):
                continue
        return 0
    if mode not in ("has", "none", "noaction", "act", "focused") or len(sys.argv) < 4:
        print(__doc__, file=sys.stderr)
        return 2
    role, name = sys.argv[2], sys.argv[3]
    deadline = time.monotonic() + float(sys.argv[4] if len(sys.argv) > 4 else 6)
    clear = 0
    last = "no sample"
    while time.monotonic() < deadline:
        try:
            found = matching(role, name)
            if mode == "none":
                clear = clear + 1 if not found else 0
                last = f"still present: {len(found)}"
                if clear >= 3:
                    print(f"PASS: no {role} {name!r}")
                    return 0
            elif len(found) == 1:
                action, focused = describe(found[0])
                if mode == "has":
                    print(f"PASS: {role} {found[0].name!r}")
                    return 0
                if mode == "focused":
                    last = f"{role} {name!r} found, focused={focused}"
                    if focused:
                        print(f"PASS: {role} {name!r} has focus")
                        return 0
                elif mode == "noaction":
                    last = f"{role} {name!r} exposes {action} action(s)"
                    if action == 0:
                        print(f"PASS: {role} {name!r} exposes no action")
                        return 0
                elif mode == "act":
                    if action < 1:
                        print(f"FAIL: {role} {name!r} exposes no action", file=sys.stderr)
                        return 1
                    if found[0].queryAction().doAction(0):
                        print(f"PASS: doAction on {role} {name!r}")
                        return 0
                    last = f"doAction refused for {role} {name!r}"
            else:
                last = f"{len(found)} nodes match {role} {name!r}"
        except (LookupError, RuntimeError, NotImplementedError) as error:
            last = "transient AT-SPI error: " + type(error).__name__
        time.sleep(0.15)
    print(f"FAIL: {last}", file=sys.stderr)
    return 1


def sorted_nodes():
    # Depth-first in tree order for readable dumps.
    desktop = pyatspi.Registry.getDesktop(0)
    for app in _children(desktop, 60):
        try:
            if APP != "*" and app.name != APP:
                continue
        except (LookupError, RuntimeError):
            continue

        def walk(node, depth):
            yield node, depth
            if depth < 16:
                for child in _children(node):
                    yield from walk(child, depth + 1)
        yield from walk(app, 0)


if __name__ == "__main__":
    raise SystemExit(main())
