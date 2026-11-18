"""Reject unsafe Debian control metadata before the optional package verifier extracts."""
from __future__ import annotations

import io
import subprocess
import sys
import tarfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.verify_wayland_control import UnsafeControl, verify_control

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "scripts" / "verify_wayland_control.py"


def archive(*entries, extended=False):
    """Each item is (name, kind, mode, uid, gid); no extracted host files."""
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w",
                      format=tarfile.PAX_FORMAT if extended else tarfile.GNU_FORMAT) as out:
        for name, kind, mode, uid, gid in entries:
            member = tarfile.TarInfo(name)
            member.type, member.mode = kind, mode
            member.uid, member.gid = uid, gid
            if extended:
                member.pax_headers = {"SCHILY.xattr.security.capability": "forged"}
            if kind == tarfile.REGTYPE:
                member.size = 7
                out.addfile(member, io.BytesIO(b"control"))
            else:
                out.addfile(member)
    return payload.getvalue()


DIR = tarfile.DIRTYPE
REG = tarfile.REGTYPE
ROOT_ENTRY = (".", DIR, 0o755, 0, 0)
CONTROL = ("./control", REG, 0o644, 0, 0)
MD5SUMS = ("./md5sums", REG, 0o644, 0, 0)


class ControlTarTests(unittest.TestCase):
    def test_valid_data_only_controls_without_and_with_root_directory(self):
        self.assertEqual(verify_control(io.BytesIO(archive(CONTROL))), 1)
        self.assertEqual(verify_control(
            io.BytesIO(archive(ROOT_ENTRY, CONTROL, MD5SUMS))), 3)

    def test_missing_control_and_maintainer_scripts_are_rejected(self):
        for items, diagnostic in (
            ((ROOT_ENTRY,), "Missing"),
            ((CONTROL, ("./postinst", REG, 0o755, 0, 0)), "maintainer script"),
            ((CONTROL, ("./prerm", REG, 0o755, 0, 0)), "maintainer script"),
            ((CONTROL, ("./conffiles", REG, 0o644, 0, 0)), "maintainer script"),
            # Postinst is fourth after a legitimate root/control/md5sums trio.
            # It still needs the specific maintainer-script diagnostic, not
            # a generic count-limit message.
            ((ROOT_ENTRY, CONTROL, MD5SUMS,
              ("./postinst", REG, 0o755, 0, 0)), "maintainer script"),
        ):
            with self.subTest(items=items), self.assertRaisesRegex(UnsafeControl, diagnostic):
                verify_control(io.BytesIO(archive(*items)))

    def test_aliases_and_duplicate_control_files_are_rejected(self):
        for items in ((CONTROL, CONTROL),
                      (CONTROL, ("control", REG, 0o644, 0, 0)),
                      (ROOT_ENTRY, ("./", DIR, 0o755, 0, 0), CONTROL)):
            with self.subTest(items=items), self.assertRaisesRegex(UnsafeControl, "Duplicate"):
                verify_control(io.BytesIO(archive(*items)))

    def test_reject_unsafe_types_owners_modes_and_paths(self):
        for changed, diagnostic in (
            (("./control", tarfile.SYMTYPE, 0o777, 0, 0), "file"),
            (("./control", REG, 0o4755, 0, 0), "file"),
            (("./control", REG, 0o666, 0, 0), "file"),
            (("./control", REG, 0o644, 1000, 0), "metadata"),
            (("../control", REG, 0o644, 0, 0), "path"),
            (("/control", REG, 0o644, 0, 0), "path"),
            (("./control\nspoof", REG, 0o644, 0, 0), "path"),
        ):
            with self.subTest(changed=changed), self.assertRaisesRegex(UnsafeControl, diagnostic):
                verify_control(io.BytesIO(archive(changed)))

    def test_pax_extended_metadata_and_bounded_size(self):
        with self.assertRaisesRegex(UnsafeControl, "metadata"):
            verify_control(io.BytesIO(archive(CONTROL, extended=True)))
        with patch("scripts.verify_wayland_control.MAX_CONTROL_BYTES", 6):
            with self.assertRaisesRegex(UnsafeControl, "size cap"):
                verify_control(io.BytesIO(archive(CONTROL)))

    def test_cli_fails_closed_and_sanitizes_error(self):
        forged = archive(CONTROL, ("./postinst", REG, 0o755, 0, 0))
        result = subprocess.run([sys.executable, str(VERIFIER)], input=forged,
                                capture_output=True, timeout=5, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"BLOCKED", result.stderr)
        self.assertNotIn(b"control\n", result.stdout)

    def test_four_package_gate_checks_control_before_any_extraction(self):
        script = (ROOT / "scripts" / "verify_wayland_package_set.sh").read_text()
        self.assertIn('dpkg-deb --ctrl-tarfile "$package"', script)
        self.assertIn('verify_wayland_control.py', script)
        self.assertLess(script.index('verify_wayland_control.py'),
                        script.index('dpkg-deb -x "$package" "$extracted"'))


if __name__ == "__main__":
    unittest.main()
