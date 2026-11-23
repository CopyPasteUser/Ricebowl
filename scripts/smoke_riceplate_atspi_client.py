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


def run_entry(name: str):
    """Find the actual transient editor, bounded against broken providers."""
    root = pyatspi.Registry.getDesktop(0)
    stack = [(root, 0)]
    visited = 0
    incomplete = False
    while stack and visited < 900:
        node, depth = stack.pop()
        visited += 1
        try:
            if node.getRole() == pyatspi.ROLE_ENTRY and node.name == name:
                return node
            count = node.childCount
            if type(count) is not int or count < 0:
                incomplete = True
                continue
            if depth >= 10:
                # A nested editor may be beyond the scan's depth limit.
                incomplete |= count > 0
                continue
            if count > 200:
                incomplete = True
            for index in range(min(count, 200) - 1, -1, -1):
                child = node.getChildAtIndex(index)
                if child is None:
                    incomplete = True
                else:
                    stack.append((child, depth + 1))
        except (LookupError, RuntimeError):
            # A disappearing child must not be counted as proof that its
            # editor was dismissed. Retry once the provider is stable.
            incomplete = True
    if stack or incomplete:
        raise RuntimeError("AT-SPI traversal incomplete")
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
            name = node.name if node.name in ("RicePlate", "Run", "Command", "File name") else ""
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


def sample(name: str):
    node = run_entry(name)
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
    parser.add_argument("--name", choices=("Command", "File name",
                                           "Search applications and actions",
                                           "Filter installed apps"), default="Command")
    parser.add_argument("--text", default="")
    parser.add_argument("--caret", type=int, default=0)
    parser.add_argument("--selection", nargs=2, type=int)
    parser.add_argument("--absent", action="store_true")
    args = parser.parse_args()
    deadline = time.monotonic() + 10
    last = "no accessible native editor entry"
    # A single missing AT-SPI sample can be an intermittent provider error,
    # not proof that a dismissed dialog is gone. Confirm consecutive misses.
    absent_samples = 0
    while time.monotonic() < deadline:
        try:
            state = sample(args.name)
            if args.absent:
                if state is None:
                    absent_samples += 1
                    if absent_samples >= 3:
                        print("PASS: dismissed native editor absent from AT-SPI")
                        return 0
                else:
                    absent_samples = 0
                    last = "native editor still present in AT-SPI"
            elif state is not None:
                wanted = [] if args.selection is None else [tuple(args.selection)]
                if (
                    state["text"] == args.text
                    and state["caret"] == args.caret
                    and state["focused"]
                    and state["selections"] == wanted
                ):
                    # Never print the editor value: it can contain a command.
                    print("PASS: live AT-SPI native editor role/name/focus/text/caret/selection")
                    return 0
                # Never log Run command contents. The mismatch dimensions
                # alone isolate focus, stale text, caret and selection bugs.
                last = (
                    "Native editor AT-SPI mismatch: "
                    f"chars={len(state['text'])}/{len(args.text)} "
                    f"caret={state['caret']}/{args.caret} "
                    f"focused={state['focused']}/True "
                    f"selection={state['selections']}/{wanted}"
                )
        except (LookupError, RuntimeError) as error:
            absent_samples = 0
            last = "transient AT-SPI provider error: " + type(error).__name__
        time.sleep(0.15)
    print("FAIL: " + last, file=sys.stderr)
    try:
        diagnostic_inventory()
    except (LookupError, RuntimeError) as error:
        # A failed provider must yield a clean failed test, not an uncaught
        # exception (and never echo private editor text).
        print("AT-SPI diagnostic unavailable: " + type(error).__name__,
              file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
