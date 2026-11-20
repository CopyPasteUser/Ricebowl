#!/usr/bin/env python3
"""Fail-closed contract for display-manager entries inside the Wayland .deb.

The package set verifier already checks ownership, archive metadata and
installed paths. Presence alone is insufficient: a repacked session package
could keep all source stamps while redirecting the display manager's Exec.
This verifier runs on extracted, untrusted package data without executing it.
"""
from __future__ import annotations

import configparser
import sys
from pathlib import Path


ALLOWED_KEYS = frozenset(
    {"Name", "Comment", "Exec", "TryExec", "Type", "DesktopNames"}
)
SESSION_EXEC = "/usr/bin/ricebowl-wayland-session"
NATIVE_EXEC = "/usr/bin/riceplate-native"
DESKTOP_NAMES = "RiceBowl;labwc;wlroots;"


class UnsafeSessionEntry(ValueError):
    """A packaged login choice deviates from the reviewed entrypoint."""


def verify_session_entry(path: Path, *, native: bool) -> None:
    # Disable interpolation and preserve key case. strict=True rejects
    # duplicate Exec/TryExec entries instead of silently using the last one.
    parser = configparser.ConfigParser(
        interpolation=None, strict=True, default_section="__no_defaults__"
    )
    parser.optionxform = str
    with path.open("r", encoding="utf-8") as source:
        parser.read_file(source)

    if parser.sections() != ["Desktop Entry"]:
        raise UnsafeSessionEntry("expected exactly one [Desktop Entry] group")

    fields = parser["Desktop Entry"]
    if set(fields) != ALLOWED_KEYS:
        raise UnsafeSessionEntry(
            f"unexpected or missing desktop keys: {sorted(set(fields) ^ ALLOWED_KEYS)}"
        )
    expected = {
        "Exec": f"{SESSION_EXEC} --native" if native else SESSION_EXEC,
        "TryExec": NATIVE_EXEC if native else SESSION_EXEC,
        "Type": "Application",
        "DesktopNames": DESKTOP_NAMES,
    }
    for key, value in expected.items():
        if fields[key] != value:
            raise UnsafeSessionEntry(f"{key} must be {value!r}")
    for key in ("Name", "Comment"):
        if not fields[key].strip():
            raise UnsafeSessionEntry(f"{key} must not be empty")


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"Usage: {argv[0]} REGULAR.desktop NATIVE.desktop", file=sys.stderr)
        return 2
    try:
        verify_session_entry(Path(argv[1]), native=False)
        verify_session_entry(Path(argv[2]), native=True)
    except (OSError, UnicodeError, configparser.Error, UnsafeSessionEntry) as exc:
        print(f"Unsafe Wayland session entry: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
