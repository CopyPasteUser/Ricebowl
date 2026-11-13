"""Regression tests for private, next-login XP Luna clock preferences."""
from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macrice.de import luna_panel_settings as luna


class LunaPanelPreferencesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.config = Path(self.temporary.name)
        patch = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.config)})
        patch.start()
        self.addCleanup(patch.stop)
        self.path = self.config / "ricebowl" / "luna-panel.json"

    def test_first_run_default_does_not_create_any_file(self):
        self.assertEqual(luna.load(), {"clock_format": "24h"})
        self.assertFalse(self.path.parent.exists())

    def test_save_is_owner_private_atomic_versioned_and_cas_guarded(self):
        baseline = luna.load()
        self.assertEqual(luna.save({"clock_format": "12h"}, expected=baseline),
                         {"clock_format": "12h"})
        self.assertEqual(luna.load(), {"clock_format": "12h"})
        self.assertEqual(json.loads(self.path.read_text()), {
            "version": 1, "clock_format": "12h",
        })
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertFalse(list(self.path.parent.glob(".luna-panel-*")))
        with self.assertRaisesRegex(luna.LunaPanelError, "changed elsewhere"):
            luna.save({"clock_format": "24h"}, expected=baseline)
        self.assertEqual(luna.load(), {"clock_format": "12h"})
        self.assertEqual(luna.save(baseline, expected=luna.load()), baseline)

    def test_unknown_versions_values_and_fields_are_rejected(self):
        self.path.parent.mkdir()
        for invalid in (
            {"version": 2, "clock_format": "12h"},
            {"version": True, "clock_format": "12h"},
            {"version": 1, "clock_format": "bogus"},
            {"version": 1, "clock_format": 12},
            {"version": 1, "clock_format": "24h", "auto_hide": True},
            {"version": 1},
        ):
            with self.subTest(invalid=invalid):
                self.path.write_text(json.dumps(invalid))
                self.path.chmod(0o600)
                with self.assertRaises(luna.LunaPanelError):
                    luna.load()
        with self.assertRaises(luna.LunaPanelError):
            luna.save({"clock_format": True}, expected=luna.DEFAULTS)

    def test_unsafe_symlink_permissions_and_oversize_file_fail_closed(self):
        self.path.parent.mkdir()
        external = self.config / "other.json"
        external.write_text('{"version":1,"clock_format":"12h"}')
        self.path.symlink_to(external)
        with self.assertRaises(luna.LunaPanelError):
            luna.load()
        self.path.unlink()
        self.path.write_text('{"version":1,"clock_format":"12h"}')
        self.path.chmod(0o644)
        with self.assertRaises(luna.LunaPanelError):
            luna.load()
        self.path.chmod(0o600)
        self.path.write_bytes(b"x" * 300)
        with self.assertRaises(luna.LunaPanelError):
            luna.load()

    def test_invalid_config_root_and_symlink_directory_are_rejected(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "relative/path"}):
            with self.assertRaises(luna.LunaPanelError):
                luna.load()
        destination = self.config / "real-dir"
        destination.mkdir()
        (self.config / "ricebowl").symlink_to(destination, target_is_directory=True)
        with self.assertRaises(luna.LunaPanelError):
            luna.load()
        with self.assertRaises(luna.LunaPanelError):
            luna.save({"clock_format": "12h"}, expected=luna.DEFAULTS)


if __name__ == "__main__":
    unittest.main()
