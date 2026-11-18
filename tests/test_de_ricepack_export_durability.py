"""SG4 portable RicePack publishing must not acknowledge unpersisted names."""
from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macrice.de import pack


class RicePackPublishDurabilityTests(unittest.TestCase):
    def test_file_then_directory_are_synced_without_staging_leftovers(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "export.ricepack"
            real_sync = os.fsync
            observed = []

            def track_sync(fd: int) -> None:
                observed.append("directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
                real_sync(fd)

            with mock.patch.object(pack.os, "fsync", side_effect=track_sync):
                pack._new_archive(destination, b"reproducible-test-bytes")
            self.assertEqual(observed, ["file", "directory"])
            self.assertEqual(destination.read_bytes(), b"reproducible-test-bytes")
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
            self.assertEqual(list(Path(temporary).glob(".ricebowl-pack-*")), [])

    def test_existing_export_is_never_overwritten_or_retried(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "export.ricepack"
            pack._new_archive(destination, b"original")
            with self.assertRaises(pack.PackError) as context:
                pack._new_archive(destination, b"rejected")
            self.assertEqual(context.exception.code, "output_unavailable")
            self.assertEqual(destination.read_bytes(), b"original")
            self.assertEqual(list(Path(temporary).glob(".ricebowl-pack-*")), [])

    def test_failed_directory_durability_does_not_claim_safe_rollback(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "export.ricepack"
            real_sync = os.fsync
            observed = []

            def broken_sync(fd: int) -> None:
                if stat.S_ISDIR(os.fstat(fd).st_mode):
                    observed.append("directory")
                    raise OSError("simulated power-loss durability failure")
                observed.append("file")
                real_sync(fd)

            with mock.patch.object(pack.os, "fsync", side_effect=broken_sync):
                with self.assertRaises(pack.PackError) as context:
                    pack._new_archive(destination, b"valid-archive")
            self.assertEqual(context.exception.code, "output_unverified")
            self.assertIn("verify destination", str(context.exception))
            self.assertEqual(observed, ["file", "directory"])
            # The link already exists when fsync fails; claiming it was
            # removed or blindly retrying could overwrite user data.
            self.assertEqual(destination.read_bytes(), b"valid-archive")
            self.assertEqual(list(Path(temporary).glob(".ricebowl-pack-*")), [])


if __name__ == "__main__":
    unittest.main()
