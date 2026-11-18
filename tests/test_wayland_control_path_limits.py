"""Raw-name length limits on opt-in Debian control archives.

A GNU longname containing thousands of harmless-looking './' segments used
to normalize to 'control' and bypass the control archive's size policy.
"""
from __future__ import annotations

import io
import subprocess
import sys
import tarfile
import unittest
from pathlib import Path

from scripts.verify_wayland_control import UnsafeControl, verify_control

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "scripts" / "verify_wayland_control.py"


def control_archive(*names: str) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.GNU_FORMAT) as archive:
        for name in names:
            member = tarfile.TarInfo(name)
            member.uid = member.gid = 0
            member.mode = 0o644
            member.size = 7
            archive.addfile(member, io.BytesIO(b"control"))
    return buffer.getvalue()


class ControlArchivePathBoundsTests(unittest.TestCase):
    def test_normal_debian_control_names_remain_supported(self):
        for name in ("control", "./control"):
            with self.subTest(name=name):
                self.assertEqual(verify_control(io.BytesIO(control_archive(name))), 1)

    def test_oversized_raw_alias_of_control_is_rejected(self):
        # PurePosixPath turns this long GNU name into precisely 'control'.
        # The unpatched verifier therefore accepted the 5,007-byte path.
        name = "./" * 2500 + "control"
        self.assertEqual(len(name.encode()), 5007)
        with self.assertRaisesRegex(UnsafeControl, "Oversized control archive path"):
            verify_control(io.BytesIO(control_archive(name)))

    def test_oversized_raw_alias_of_md5sums_is_rejected(self):
        name = "./" * 2500 + "md5sums"
        with self.assertRaisesRegex(UnsafeControl, "Oversized control archive path"):
            verify_control(io.BytesIO(control_archive("control", name)))

    def test_cli_rejects_oversized_name_without_extraction(self):
        attack = control_archive("./" * 2500 + "control")
        completed = subprocess.run(
            [sys.executable, str(VERIFIER)],
            input=attack,
            capture_output=True,
            check=False,
            timeout=5,
        )
        self.assertEqual(completed.returncode, 1)
        self.assertIn(b"BLOCKED", completed.stderr)
        self.assertIn(b"Oversized control archive path", completed.stderr)
        self.assertEqual(completed.stdout, b"")


if __name__ == "__main__":
    unittest.main()
