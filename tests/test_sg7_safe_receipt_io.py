"""Standalone, Linux-only SG7 receipt descriptor-hardening regressions."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.sg7_safe_receipt_io import ReceiptReadError, read_regular_bytes


class SG7SafeReceiptIOTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="sg7-safe-receipt-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.receipt = self.root / "sample.json"
        self.receipt.write_bytes(b'{"ok":true}')

    def test_regular_bytes_are_read_verbatim(self):
        self.assertEqual(read_regular_bytes(self.receipt, limit=1024), b'{"ok":true}')

    def test_missing_symlink_directory_and_fifo_fail_closed(self):
        alias = self.root / "alias.json"
        alias.symlink_to(self.receipt)
        fifo = self.root / "fifo.json"
        os.mkfifo(fifo)
        for candidate in (alias, fifo, self.root, self.root / "missing.json"):
            with self.subTest(candidate=candidate):
                with self.assertRaises(ReceiptReadError):
                    read_regular_bytes(candidate, limit=1024)

    def test_empty_oversized_and_invalid_limits_fail_closed(self):
        for payload, limit in ((b"", 1024), (b"1234567", 6), (b"123", 0)):
            with self.subTest(payload=payload, limit=limit):
                self.receipt.write_bytes(payload)
                with self.assertRaises(ReceiptReadError):
                    read_regular_bytes(self.receipt, limit=limit)

    def test_modification_during_read_never_produces_trusted_payload(self):
        # In-place rewrite after the pre-read fstat must invalidate the
        # measurement, even when byte count stays unchanged.
        original = os.fstat
        calls = 0

        def tamper(fd):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.receipt.write_bytes(b'{"ok":evil}')
            return original(fd)

        with patch("scripts.sg7_safe_receipt_io.os.fstat", side_effect=tamper):
            with self.assertRaisesRegex(ReceiptReadError, "changed"):
                read_regular_bytes(self.receipt, limit=1024)

    def test_atomic_path_replacement_during_read_is_rejected(self):
        # A stale file descriptor can still return well-formed old evidence
        # after rename replaced the pathname with another regular file.
        replacement = self.root / "new.json"
        replacement.write_bytes(b'{"ok":evil}')
        original = os.fstat
        calls = 0

        def replace_between_stats(fd):
            nonlocal calls
            calls += 1
            if calls == 2:
                os.replace(replacement, self.receipt)
            return original(fd)

        with patch("scripts.sg7_safe_receipt_io.os.fstat", side_effect=replace_between_stats):
            with self.assertRaisesRegex(ReceiptReadError, "changed"):
                read_regular_bytes(self.receipt, limit=1024)


if __name__ == "__main__":
    unittest.main()
