"""SG2 monitor preset persistence must survive completed atomic renames."""
from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macrice.de import display_presets


class MonitorPresetDurabilityTests(unittest.TestCase):
    def test_preset_commit_syncs_both_regular_file_and_parent_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            original_sync = os.fsync
            synced = []

            def track_sync(fd: int) -> None:
                mode = os.fstat(fd).st_mode
                synced.append("dir" if stat.S_ISDIR(mode) else "file")
                original_sync(fd)

            with mock.patch.object(display_presets.os, "fsync", side_effect=track_sync):
                display_presets._write(directory, [], False)

            self.assertEqual(synced, ["file", "dir"],
                             "renamed file AND containing directory must be durable")
            stored = json.loads((directory / "ricespice-displays.json").read_text())
            self.assertEqual(stored, {"version": 2, "outputs": [], "auto_trial": False})
            self.assertFalse(list(directory.glob(".ricespice-displays-*")))

    def test_failed_rename_keeps_existing_private_preset_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            display_presets._write(directory, [], False)
            before = (directory / "ricespice-displays.json").read_bytes()
            with mock.patch.object(display_presets.os, "replace",
                                   side_effect=OSError("injected rename failure")):
                with self.assertRaises(OSError):
                    display_presets._write(directory, [], True)
            self.assertEqual((directory / "ricespice-displays.json").read_bytes(), before)
            self.assertFalse(list(directory.glob(".ricespice-displays-*")))

    def test_directory_sync_failure_is_not_claimed_as_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            real_sync = os.fsync
            calls = []

            def fail_directory_sync(fd: int) -> None:
                if stat.S_ISDIR(os.fstat(fd).st_mode):
                    calls.append("directory")
                    raise OSError("injected directory fsync failure")
                calls.append("file")
                real_sync(fd)

            with mock.patch.object(display_presets.os, "fsync",
                                   side_effect=fail_directory_sync):
                with self.assertRaisesRegex(OSError, "directory fsync failure"):
                    display_presets._write(directory, [], True)
            self.assertEqual(calls, ["file", "directory"])
            # A successful rename before the failed durability barrier may
            # already change the visible value: callers must refresh/recheck.
            self.assertTrue((directory / "ricespice-displays.json").exists())
            self.assertFalse(list(directory.glob(".ricespice-displays-*")))


if __name__ == "__main__":
    unittest.main()
