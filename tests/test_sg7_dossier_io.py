"""SG7 atomic dossier publication regressions; no GitHub/network required."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pathlib import Path
from unittest.mock import patch

from scripts.sg7_dossier_io import DossierWriteError, publish_dossier


class DossierIOTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="sg7-dossier-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out = self.root / "nested" / "software-matrix.json"
        self.valid = {"source_sha": "a" * 40, "ready_for_formal_review": False}

    def assert_no_temp_files(self):
        self.assertEqual(list(self.out.parent.glob(".software-matrix.json.*.tmp")), [])

    def test_private_complete_report_written_once(self):
        publish_dossier(self.out, self.valid)
        self.assertEqual(json.loads(self.out.read_text()), self.valid)
        self.assertTrue(self.out.read_text().endswith("\n"))
        self.assertEqual(self.out.stat().st_mode & 0o777, 0o600)
        self.assert_no_temp_files()

    def test_existing_file_never_overwritten(self):
        self.out.parent.mkdir(parents=True)
        self.out.write_text("existing", encoding="utf-8")
        with self.assertRaises(DossierWriteError):
            publish_dossier(self.out, self.valid)
        self.assertEqual(self.out.read_text(), "existing")
        self.assert_no_temp_files()

    def test_existing_symlink_never_followed_or_replaced(self):
        self.out.parent.mkdir(parents=True)
        target = self.root / "important.txt"
        target.write_text("keep", encoding="utf-8")
        self.out.symlink_to(target)
        with self.assertRaises(DossierWriteError):
            publish_dossier(self.out, self.valid)
        self.assertTrue(self.out.is_symlink())
        self.assertEqual(target.read_text(), "keep")
        self.assert_no_temp_files()

    def test_failed_serialization_does_not_leave_partial_report(self):
        with self.assertRaises(DossierWriteError):
            publish_dossier(self.out, {"ok": 1, "unserializable": object()})
        self.assertFalse(self.out.exists())
        self.assert_no_temp_files()

    def test_nonfinite_float_fails_closed(self):
        with self.assertRaises(DossierWriteError):
            publish_dossier(self.out, {"measurement": float("nan")})
        self.assertFalse(self.out.exists())
        self.assert_no_temp_files()

    def test_link_error_cleans_temp_and_does_not_publish(self):
        with patch("scripts.sg7_dossier_io.os.link", side_effect=OSError("failure")):
            with self.assertRaises(DossierWriteError):
                publish_dossier(self.out, self.valid)
        self.assertFalse(self.out.exists())
        self.assert_no_temp_files()

    def test_fsync_error_leaves_no_published_report(self):
        with patch("scripts.sg7_dossier_io.os.fsync", side_effect=OSError("disk sync error")):
            with self.assertRaises(DossierWriteError):
                publish_dossier(self.out, self.valid)
        self.assertFalse(self.out.exists())
        self.assert_no_temp_files()

    def test_two_real_concurrent_publishers_have_only_one_winner(self):
        barrier = Barrier(2)

        def writer(number):
            barrier.wait(timeout=15)
            try:
                publish_dossier(self.out, {"writer": number})
                return "published"
            except DossierWriteError:
                return "blocked"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(writer, (1, 2)))
        self.assertCountEqual(results, ("published", "blocked"))
        self.assertIn(json.loads(self.out.read_text())["writer"], (1, 2))
        self.assert_no_temp_files()

    def test_racing_target_creation_is_never_overwritten(self):
        original_link = os.link

        def race(src, dst):
            Path(dst).write_text("racing publisher", encoding="utf-8")
            return original_link(src, dst)

        with patch("scripts.sg7_dossier_io.os.link", side_effect=race):
            with self.assertRaises(DossierWriteError):
                publish_dossier(self.out, self.valid)
        self.assertEqual(self.out.read_text(), "racing publisher")
        self.assert_no_temp_files()


if __name__ == "__main__":
    unittest.main()
