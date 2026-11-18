"""SG3: notification appearance saves require directory durability."""
from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macrice.de import notification_prefs


class RicePopAppearanceDurabilityTests(unittest.TestCase):
    def test_persisted_save_syncs_data_and_directory_in_order(self):
        with tempfile.TemporaryDirectory() as config, mock.patch.dict(
                os.environ, {"XDG_CONFIG_HOME": config}):
            original = os.fsync
            synced = []

            def track(fd: int) -> None:
                synced.append("directory" if stat.S_ISDIR(os.fstat(fd).st_mode)
                              else "file")
                original(fd)

            updated = {**notification_prefs.DEFAULTS, "font_size": 14}
            with mock.patch.object(notification_prefs.os, "fsync", side_effect=track):
                self.assertEqual(notification_prefs.save(
                    updated, expected=notification_prefs.DEFAULTS), updated)
            self.assertEqual(synced, ["file", "directory"])
            target = Path(config) / "ricebowl" / "ricepop-appearance.json"
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(notification_prefs.load(), updated)
            self.assertEqual(list(target.parent.glob(".ricepop-*")), [])

    def test_failed_rename_preserves_last_saved_appearance(self):
        with tempfile.TemporaryDirectory() as config, mock.patch.dict(
                os.environ, {"XDG_CONFIG_HOME": config}):
            updated = {**notification_prefs.DEFAULTS, "font_size": 14}
            notification_prefs.save(updated, expected=notification_prefs.DEFAULTS)
            target = Path(config) / "ricebowl" / "ricepop-appearance.json"
            before = target.read_bytes()
            with mock.patch.object(notification_prefs.os, "replace",
                                   side_effect=OSError("injected rename failure")):
                with self.assertRaisesRegex(OSError, "rename failure"):
                    notification_prefs.save(
                        notification_prefs.DEFAULTS, expected=updated)
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(notification_prefs.load(), updated)
            self.assertEqual(list(target.parent.glob(".ricepop-*")), [])

    def test_failed_directory_sync_does_not_claim_success_or_rollback(self):
        with tempfile.TemporaryDirectory() as config, mock.patch.dict(
                os.environ, {"XDG_CONFIG_HOME": config}):
            actual_sync = os.fsync
            synced = []

            def reject_directory(fd: int) -> None:
                if stat.S_ISDIR(os.fstat(fd).st_mode):
                    synced.append("directory")
                    raise OSError("injected directory sync failure")
                synced.append("file")
                actual_sync(fd)

            updated = {**notification_prefs.DEFAULTS, "default_timeout": 7000}
            with mock.patch.object(notification_prefs.os, "fsync",
                                   side_effect=reject_directory):
                with self.assertRaisesRegex(OSError, "directory sync failure"):
                    notification_prefs.save(
                        updated, expected=notification_prefs.DEFAULTS)
            self.assertEqual(synced, ["file", "directory"])
            # The rename can succeed even when the durability barrier fails;
            # only fresh readback can establish the current visible value.
            self.assertEqual(notification_prefs.load(), updated)
            with self.assertRaisesRegex(ValueError, "changed"):
                notification_prefs.save(
                    notification_prefs.DEFAULTS, expected=notification_prefs.DEFAULTS)
            self.assertEqual(notification_prefs.save(
                notification_prefs.DEFAULTS, expected=updated),
                notification_prefs.DEFAULTS)
            self.assertEqual(list((Path(config) / "ricebowl").glob(".ricepop-*")), [])


if __name__ == "__main__":
    unittest.main()
