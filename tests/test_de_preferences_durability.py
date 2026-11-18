"""SG2: durable next-login RiceSpice preferences and error truthfulness."""
from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macrice.de import preferences


class RiceSpicePreferencesDurabilityTests(unittest.TestCase):
    def test_save_syncs_file_then_directory_and_preserves_private_mode(self):
        with tempfile.TemporaryDirectory() as config, mock.patch.dict(
                os.environ, {"XDG_CONFIG_HOME": config}):
            actual_sync = os.fsync
            observed = []

            def track_sync(fd: int) -> None:
                observed.append("directory" if stat.S_ISDIR(os.fstat(fd).st_mode)
                                else "file")
                actual_sync(fd)

            selected = {**preferences.DEFAULTS, "high_contrast": True}
            with mock.patch.object(preferences.os, "fsync", side_effect=track_sync):
                self.assertEqual(
                    preferences.save(selected, expected=preferences.DEFAULTS), selected)
            self.assertEqual(observed, ["file", "directory"])
            target = Path(config) / "ricebowl" / "ricespice.json"
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(preferences.load(), selected)
            self.assertEqual(list(target.parent.glob(".ricespice-*")), [])

    def test_rename_failure_keeps_old_value_without_staging_files(self):
        with tempfile.TemporaryDirectory() as config, mock.patch.dict(
                os.environ, {"XDG_CONFIG_HOME": config}):
            current = {**preferences.DEFAULTS, "high_contrast": True}
            preferences.save(current, expected=preferences.DEFAULTS)
            target = Path(config) / "ricebowl" / "ricespice.json"
            before = target.read_bytes()
            with mock.patch.object(preferences.os, "replace",
                                   side_effect=OSError("injected rename failure")):
                with self.assertRaisesRegex(OSError, "rename failure"):
                    preferences.save(preferences.DEFAULTS, expected=current)
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(preferences.load(), current)
            self.assertEqual(list(target.parent.glob(".ricespice-*")), [])

    def test_failed_directory_sync_is_not_success_or_implicit_rollback(self):
        with tempfile.TemporaryDirectory() as config, mock.patch.dict(
                os.environ, {"XDG_CONFIG_HOME": config}):
            actual_sync = os.fsync
            observed = []

            def fail_directory(fd: int) -> None:
                if stat.S_ISDIR(os.fstat(fd).st_mode):
                    observed.append("directory")
                    raise OSError("injected directory durability failure")
                observed.append("file")
                actual_sync(fd)

            selected = {**preferences.DEFAULTS, "pointer_speed": 0.5}
            with mock.patch.object(preferences.os, "fsync",
                                   side_effect=fail_directory):
                with self.assertRaisesRegex(OSError, "directory durability failure"):
                    preferences.save(selected, expected=preferences.DEFAULTS)
            self.assertEqual(observed, ["file", "directory"])
            # Rename may already be visible after a failed persistence barrier.
            # A UI must re-read before any subsequent compare-and-set operation.
            self.assertEqual(preferences.load(), selected)
            with self.assertRaises(preferences.PreferenceError):
                preferences.save(preferences.DEFAULTS, expected=preferences.DEFAULTS)
            self.assertEqual(
                preferences.save(preferences.DEFAULTS, expected=selected),
                preferences.DEFAULTS)
            self.assertEqual(list((Path(config) / "ricebowl").glob(".ricespice-*")), [])


if __name__ == "__main__":
    unittest.main()
