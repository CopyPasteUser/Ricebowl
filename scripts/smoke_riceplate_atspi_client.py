#!/usr/bin/env python3
"""Black-box AT-SPI probe for RicePlate's compositor-focused native Run editor.

Uses the public accessibility bus only. Does not inspect Rust state, socket
internals, command text logs, or screenshots as a substitute for semantics.
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter

import pyatspi


def run_entry():
    """Find the actual transient Run entry, bounded against broken providers."""
    root = pyatspi.Registry.getDesktop(0)
    stack = [(root, 0)]
    visited = 0
    while stack and visited < 900:
        node, depth = stack.pop()
        visited += 1
        try:
            if node.getRole() == pyatspi.ROLE_ENTRY and node.name == "Command":
                return node
            if depth >= 10:
                continue
            for index in range(min(node.childCount, 200) - 1, -1, -1):
                child = node.getChildAtIndex(index)
                if child is not None:
                    stack.append((child, depth + 1))
        except (LookupError, RuntimeError):
            # A window may disappear between enumerating its parent and child.
            continue
    return None



def diagnostic_inventory():
    """Only roles and whitelisted internal names; never user text/labels."""
    root = pyatspi.Registry.getDesktop(0)
    counts = Counter()
    app_count = root.childCount
    stack = [(root, 0)]
    seen = 0
    while stack and seen < 900:
        node, depth = stack.pop()
        seen += 1
        try:
            counts[node.getRoleName()] += 1
            name = node.name if node.name in ("RicePlate", "Run", "Command") else ""
            if name:
                print(f"AT-SPI debug depth={depth} role={node.getRoleName()} name={name}",
                      file=sys.stderr)
            if depth >= 10:
                continue
            for index in range(min(node.childCount, 200) - 1, -1, -1):
                child = node.getChildAtIndex(index)
                if child is not None:
                    stack.append((child, depth + 1))
        except (LookupError, RuntimeError):
            continue
    print(f"AT-SPI diagnostic: desktop_children={app_count} nodes={seen} "
          f"roles={dict(counts)}", file=sys.stderr)


def sample():
    node = run_entry()
    if node is None:
        return None
    states = node.getState()
    text = node.queryText()
    value = text.getText(0, text.characterCount)
    selections = []
    for index in range(min(text.getNSelections(), 4)):
        start, end = text.getSelection(index)
        if start != end:
            selections.append((start, end))
    return {
        "text": value,
        "caret": text.caretOffset,
        "focused": states.contains(pyatspi.STATE_FOCUSED),
        "selections": selections,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", default="")
    parser.add_argument("--caret", type=int, default=0)
    parser.add_argument("--selection", nargs=2, type=int)
    parser.add_argument("--absent", action="store_true")
    args = parser.parse_args()
    deadline = time.monotonic() + 10
    last = "no accessible Run entry"
    while time.monotonic() < deadline:
        try:
            state = sample()
            if args.absent:
                if state is None:
                    print("PASS: dismissed Run entry absent from AT-SPI")
                    return 0
            elif state is not None:
                wanted = [] if args.selection is None else [tuple(args.selection)]
                if (
                    state["text"] == args.text
                    and state["caret"] == args.caret
                    and state["focused"]
                    and state["selections"] == wanted
                ):
                    # Never print the editor value: it can contain a command.
                    print("PASS: live AT-SPI Run entry role/name/focus/text/caret/selection")
                    return 0
                last = (
                    "entry present but AT-SPI text, caret, focus or selection "
                    "does not match the expected fixture"
                )
        except (LookupError, RuntimeError) as error:
            last = "transient AT-SPI provider error: " + type(error).__name__
        time.sleep(0.15)
    print("FAIL: " + last, file=sys.stderr)
    diagnostic_inventory()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
