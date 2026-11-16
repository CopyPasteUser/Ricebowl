"""First XP Luna physical QA produces private evidence, never approval."""
import json
import os
import stat
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path

from scripts.qa_xp_luna_first_pass import (
    build_report, create_bundle, grab_frame, prepare_directory,
    process_memory, validate_png, write_private,
)


class FakeAcceptance:
    def __init__(self, ready=True):
        self.ready = ready

    def as_dict(self):
        return {"ready_for_manual_checks": self.ready,
                "hardware_accepted": False,
                "manual_checks": [{"key": "login", "status": "pending"}],
                "session": {"type": "wayland", "nested": False}}



def png_chunk(kind: bytes, content: bytes) -> bytes:
    return (struct.pack(">I", len(content)) + kind + content
            + struct.pack(">I", zlib.crc32(kind + content)))


def valid_frame(width: int = 64, height: int = 32) -> bytes:
    """Real decodable RGBA PNG; malformed headers must not pass QA tests."""
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    rows = (b"\x00" + b"\x00\x40\x80\xff" * width) * height
    return (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", header)
            + png_chunk(b"IDAT", zlib.compress(rows))
            + png_chunk(b"IEND", b""))


class LunaFirstPassTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.parent = Path(temp.name)

    def test_same_uid_resource_snapshot_never_reads_argv_or_other_processes(self):
        current = self.parent / "123"
        current.mkdir()
        (current / "comm").write_text("riceplate-nativ\n")
        (current / "status").write_text(f"Uid:\t{os.getuid()}\t{os.getuid()}\n")
        (current / "smaps_rollup").write_text("Rss: 100 kB\nPss: 65 kB\n")
        foreign = self.parent / "456"
        foreign.mkdir()
        (foreign / "comm").write_text("labwc\n")
        (foreign / "status").write_text(f"Uid:\t{os.getuid() + 1}\t{os.getuid() + 1}\n")
        (foreign / "smaps_rollup").write_text("Rss: 999 kB\nPss: 999 kB\n")
        secret = self.parent / "789"
        secret.mkdir()
        (secret / "comm").write_text("browser-secret\n")
        (secret / "status").write_text(f"Uid:\t{os.getuid()}\n")
        (secret / "smaps_rollup").write_text("Rss: 5000 kB\nPss: 5000 kB\n")
        self.assertEqual(process_memory(self.parent), {
            "riceplate-native": {"count": 1, "pss_kib": 65, "rss_kib": 100},
        })

    def test_new_private_bundle_is_not_a_hardware_signoff_or_implicit_screenshot(self):
        folder = self.parent / "qa-run"
        report = create_bundle(folder, acceptance=FakeAcceptance(),
                               resources={"labwc": {"count": 1, "pss_kib": 30, "rss_kib": 40}},
                               run=lambda *a, **k: self.fail("unrequested screenshot"))
        self.assertFalse(report["hardware_accepted"])
        self.assertFalse(report["physical_tests_automatically_passed"])
        self.assertEqual(report["screenshot"], {"requested": False, "captured": False})
        self.assertTrue(folder.is_dir())
        self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((folder / "report.json").stat().st_mode), 0o600)
        self.assertEqual([p.name for p in folder.iterdir()], ["report.json"])
        disk = json.loads((folder / "report.json").read_text())
        self.assertEqual(disk["session_preflight"]["manual_checks"][0]["status"], "pending")
        with self.assertRaises(FileExistsError):
            create_bundle(folder, acceptance=FakeAcceptance(), resources={})
        with self.assertRaises(FileExistsError):
            write_private(folder / "report.json", b"must not overwrite")

    def test_explicit_capture_is_private_and_has_integrity_receipt(self):
        png = valid_frame()
        def fake_grim(command, **kwargs):
            self.assertEqual(command[-1], "-")
            self.assertTrue(kwargs["capture_output"])
            self.assertLessEqual(kwargs["timeout"], 8)
            return subprocess.CompletedProcess(command, 0, png, b"")
        # Select a fake executable only in the test, never in production.
        from unittest.mock import patch
        with patch("scripts.qa_xp_luna_first_pass.shutil.which", return_value="/usr/bin/grim"):
            report = create_bundle(self.parent / "capture", capture=True,
                                   acceptance=FakeAcceptance(), resources={}, run=fake_grim)
        self.assertTrue(report["screenshot"]["captured"])
        image = self.parent / "capture" / "native-frame.png"
        self.assertEqual(image.read_bytes(), png)
        self.assertEqual(stat.S_IMODE(image.stat().st_mode), 0o600)
        self.assertEqual(len(report["screenshot"]["sha256"]), 64)

    def test_unready_session_never_captures_even_with_explicit_flag(self):
        report = create_bundle(self.parent / "not-ready", capture=True,
                               acceptance=FakeAcceptance(ready=False), resources={},
                               run=lambda *a, **kw: self.fail("forbidden capture"))
        self.assertEqual(report["screenshot"]["error"], "not-a-ready-native-session")
        self.assertFalse(report["screenshot"]["captured"])
        self.assertFalse((self.parent / "not-ready" / "native-frame.png").exists())

    def test_png_receipts_reject_header_only_truncation_crc_and_trailing_data(self):
        good = valid_frame()
        validate_png(good)
        corrupt = bytearray(good)
        # IHDR (25 bytes) ends at offset 33; IDAT payload begins at 41.
        corrupt[41] ^= 1
        malformed = (
            b"\x89PNG\r\n\x1a\n" + b"\x00" * 24,
            good[:-12],  # missing IEND, formerly accepted by header check
            good + b"unexpected tail",
            bytes(corrupt),
            valid_frame(width=0),
        )
        for frame in malformed:
            with self.subTest(frame_size=len(frame)):
                with self.assertRaises(RuntimeError):
                    validate_png(frame)

    def test_corrupt_png_and_unsafe_paths_fail_closed(self):
        with self.assertRaises(ValueError):
            prepare_directory(Path("relative"))
        bad = self.parent / "target-link"
        bad.symlink_to(self.parent / "does-not-exist")
        with self.assertRaises(FileExistsError):
            prepare_directory(bad)
        with self.assertRaises(RuntimeError):
            grab_frame(binary="/bin/grim", run=lambda cmd, **kw:
                       subprocess.CompletedProcess(cmd, 0, b"not-a-png", b""))


if __name__ == "__main__":
    unittest.main()
