#!/usr/bin/env python3
"""Validate actual xdg-desktop-portal interfaces over the session bus.

This probes interfaces, not user consent, PipeWire streaming or Flatpak grants.
No screenshot is requested and no files outside the disposable CI runtime are
read or changed. The per-call timeout prevents a broken service hanging CI.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import xml.etree.ElementTree as ET

DEST = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"
REQUIRED = frozenset({
    "org.freedesktop.portal.FileChooser",
    "org.freedesktop.portal.Screenshot",
    "org.freedesktop.portal.ScreenCast",
})


def parse_interfaces(xml: str) -> set[str]:
    root = ET.fromstring(xml)
    if root.tag != "node":
        raise ValueError("D-Bus introspection returned no object node")
    return {item.attrib["name"] for item in root.findall("interface")
            if "name" in item.attrib}


def check(timeout: int = 12) -> set[str]:
    process = subprocess.run(
        ["gdbus", "introspect", "--session", "--dest", DEST,
         "--object-path", PATH, "--xml"],
        capture_output=True, text=True, timeout=timeout, check=False)
    if process.returncode:
        raise RuntimeError(
            "Desktop portal D-Bus activation/introspection failed: " +
            process.stderr.strip()[:600])
    found = parse_interfaces(process.stdout)
    missing = REQUIRED - found
    if missing:
        raise RuntimeError("Missing exported desktop portal interfaces: " +
                           ", ".join(sorted(missing)))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=12)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 30:
        parser.error("timeout must be 1..30 seconds")
    try:
        found = check(timeout=args.timeout)
    except (OSError, subprocess.TimeoutExpired, ET.ParseError,
            ValueError, RuntimeError) as exc:
        print(f"PORTAL_FAIL: {exc}", file=sys.stderr)
        return 1
    for interface in sorted(REQUIRED):
        assert interface in found
        print(f"PORTAL_OK: {interface}")
    print("PORTAL_LIMIT: Interfaces only; no actual user-consented capture or file dialog.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
