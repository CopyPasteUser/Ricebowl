"""Deterministic unit tests for the untrusted packaged login entry parser."""
from __future__ import annotations

import configparser
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.verify_wayland_session_entries import (
    UnsafeSessionEntry,
    verify_session_entry,
)


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "packaging" / "wayland"
CHECKER = ROOT / "scripts" / "verify_wayland_session_entries.py"


class WaylandSessionEntryTests(unittest.TestCase):
    def test_packaged_templates_have_reviewed_entrypoints(self):
        verify_session_entry(TEMPLATES / "ricebowl.desktop", native=False)
        verify_session_entry(TEMPLATES / "ricebowl-native.desktop", native=True)

    def test_parser_rejects_drift_and_ambiguous_desktop_commands(self):
        regular = (TEMPLATES / "ricebowl.desktop").read_text(encoding="utf-8")
        native = (TEMPLATES / "ricebowl-native.desktop").read_text(encoding="utf-8")
        cases = (
            ("shell execution", regular.replace(
                "Exec=/usr/bin/ricebowl-wayland-session",
                "Exec=/bin/sh -c arbitrary"), False),
            ("duplicate Exec", regular + "Exec=/bin/true\\n", False),
            ("spaced duplicate Exec", regular + " Exec = /bin/true\\n", False),
            ("redirect native TryExec", native.replace(
                "TryExec=/usr/bin/riceplate-native", "TryExec=/usr/bin/true"), True),
            ("redirect native Exec", native.replace(
                "Exec=/usr/bin/ricebowl-wayland-session --native",
                "Exec=/usr/bin/ricebowl-wayland-session"), True),
            ("wrong desktop names", regular.replace(
                "DesktopNames=RiceBowl;labwc;wlroots;",
                "DesktopNames=XFCE;"), False),
            ("non-application type", regular.replace(
                "Type=Application", "Type=Link"), False),
            ("unsupported activation", regular + "DBusActivatable=true\\n", False),
            ("hidden session", regular + "Hidden=true\\n", False),
            ("second section", regular + "[Desktop Action Inject]\\nExec=/bin/true\\n", False),
            ("missing Exec", regular.replace(
                "Exec=/usr/bin/ricebowl-wayland-session\\n", ""), False),
        )
        with tempfile.TemporaryDirectory() as tmp:
            entry = Path(tmp) / "session.desktop"
            for label, candidate, native_mode in cases:
                with self.subTest(case=label):
                    entry.write_text(candidate, encoding="utf-8")
                    with self.assertRaises((UnsafeSessionEntry, configparser.Error)):
                        verify_session_entry(entry, native=native_mode)

    def test_cli_fails_closed_before_reporting_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            regular = Path(tmp) / "regular.desktop"
            regular.write_text(
                (TEMPLATES / "ricebowl.desktop").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            native = TEMPLATES / "ricebowl-native.desktop"
            passed = subprocess.run(
                [sys.executable, str(CHECKER), str(regular), str(native)],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(passed.returncode, 0, passed.stderr)
            regular.write_text(
                regular.read_text(encoding="utf-8").replace(
                    "Exec=/usr/bin/ricebowl-wayland-session",
                    "Exec=/bin/sh -c arbitrary",
                ),
                encoding="utf-8",
            )
            failed = subprocess.run(
                [sys.executable, str(CHECKER), str(regular), str(native)],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(failed.returncode, 1)
            self.assertIn("Unsafe Wayland session entry", failed.stderr)


if __name__ == "__main__":
    unittest.main()
