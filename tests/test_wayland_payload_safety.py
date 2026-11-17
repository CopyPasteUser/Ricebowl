"""Negative tests for the read-only Debian payload metadata gate."""
from __future__ import annotations

import io
import subprocess
import sys
import tarfile
import unittest
from pathlib import Path

from scripts.verify_wayland_payload import UnsafePayload, verify_payload

CHECKER = Path(__file__).resolve().parents[1] / "scripts/verify_wayland_payload.py"


def make_archive(*entries: tuple[str, int, int, int, bytes, bytes | None]) -> bytes:
    """Entry: path, mode, uid, gid, type, optional link target."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, mode, uid, gid, kind, target in entries:
            member = tarfile.TarInfo(name)
            member.mode, member.uid, member.gid, member.type = mode, uid, gid, kind
            if kind == tarfile.REGTYPE:
                data = b"verified"
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
            else:
                if target is not None:
                    member.linkname = target.decode("utf-8")
                archive.addfile(member)
    return buffer.getvalue()


class DebianPayloadGuardTests(unittest.TestCase):
    def test_safe_root_owned_files_and_directories_pass(self):
        archive = make_archive(
            ("./", 0o755, 0, 0, tarfile.DIRTYPE, None),
            ("./usr/", 0o755, 0, 0, tarfile.DIRTYPE, None),
            ("./usr/bin/riceplate-native", 0o755, 0, 0, tarfile.REGTYPE, None),
            ("./usr/share/readme", 0o644, 0, 0, tarfile.REGTYPE, None),
        )
        self.assertEqual(verify_payload(io.BytesIO(archive)), 4)

    def test_reject_unsafe_owner_permissions_links_and_paths(self):
        bad_cases = [
            ("user-owned file", ("./usr/bin/riceplate-native", 0o755, 1000, 0,
                                  tarfile.REGTYPE, None), "Non-root"),
            ("group-owned file", ("./usr/bin/riceplate-native", 0o755, 0, 1000,
                                   tarfile.REGTYPE, None), "Non-root"),
            ("world writable", ("./usr/bin/riceplate-native", 0o777, 0, 0,
                                 tarfile.REGTYPE, None), "permissions"),
            ("group writable", ("./usr/bin/riceplate-native", 0o775, 0, 0,
                                 tarfile.REGTYPE, None), "permissions"),
            ("setuid binary", ("./usr/bin/riceplate-native", 0o4755, 0, 0,
                               tarfile.REGTYPE, None), "permissions"),
            ("setgid directory", ("./usr/", 0o2755, 0, 0,
                                  tarfile.DIRTYPE, None), "permissions"),
            ("sticky directory", ("./usr/", 0o1755, 0, 0,
                                  tarfile.DIRTYPE, None), "permissions"),
            ("symlink", ("./usr/bin/riceplate-native", 0o755, 0, 0,
                         tarfile.SYMTYPE, b"/etc/shadow"), "entry type"),
            ("hardlink", ("./usr/bin/riceplate-native", 0o755, 0, 0,
                          tarfile.LNKTYPE, b"../../etc/shadow"), "entry type"),
            ("device node", ("./usr/bin/riceplate-native", 0o600, 0, 0,
                             tarfile.CHRTYPE, None), "entry type"),
            ("parent traversal", ("./usr/../etc/shadow", 0o644, 0, 0,
                                  tarfile.REGTYPE, None), "path"),
            ("absolute path", ("/etc/shadow", 0o644, 0, 0,
                               tarfile.REGTYPE, None), "path"),
        ]
        for label, entry, diagnostic in bad_cases:
            with self.subTest(label=label):
                with self.assertRaisesRegex(UnsafePayload, diagnostic):
                    verify_payload(io.BytesIO(make_archive(entry)))

    def test_truncated_and_empty_archives_fail_closed(self):
        for data in (b"", b"not a tar archive", bytes(1024)):
            with self.subTest(length=len(data)), self.assertRaises(UnsafePayload):
                verify_payload(io.BytesIO(data))

    def test_release_bundle_verifier_checks_raw_metadata_before_extraction(self):
        verifier = (CHECKER.parent / "verify_wayland_package_set.sh").read_text()
        self.assertIn('dpkg-deb --fsys-tarfile "$package"', verifier)
        self.assertIn('verify_wayland_payload.py', verifier)
        self.assertLess(verifier.index('verify_wayland_payload.py'),
                        verifier.index('dpkg-deb -x "$package" "$extracted"'))

    def test_cli_rejects_forged_archive_without_extracting(self):
        crafted = make_archive(("./usr/bin/riceplate-native", 0o4755, 0, 0,
                                tarfile.REGTYPE, None))
        result = subprocess.run([sys.executable, str(CHECKER)], input=crafted,
                                capture_output=True, timeout=5, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"Unsafe package payload permissions", result.stderr)


if __name__ == "__main__":
    unittest.main()
