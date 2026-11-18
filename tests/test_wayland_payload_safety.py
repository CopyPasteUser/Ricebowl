"""Negative tests for the read-only Debian payload metadata gate."""
from __future__ import annotations

import io
import subprocess
import sys
import tarfile
import unittest
from unittest.mock import patch
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

    def test_reject_duplicate_and_aliased_install_destinations(self):
        # One canonical path must map to exactly one archive entry. Tar
        # permits duplicate members, but dpkg can overwrite earlier bytes.
        cases = [
            ("same file twice", [
                ("./usr/bin/riceplate-native", 0o755, 0, 0, tarfile.REGTYPE, None),
                ("./usr/bin/riceplate-native", 0o755, 0, 0, tarfile.REGTYPE, None),
            ]),
            ("dot-prefix alias", [
                ("./usr/bin/riceplate-native", 0o755, 0, 0, tarfile.REGTYPE, None),
                ("usr/bin/riceplate-native", 0o755, 0, 0, tarfile.REGTYPE, None),
            ]),
            ("directory replaced by file", [
                ("./usr/share", 0o755, 0, 0, tarfile.DIRTYPE, None),
                ("usr/share", 0o644, 0, 0, tarfile.REGTYPE, None),
            ]),
            ("file replaced by directory", [
                ("./usr/share", 0o644, 0, 0, tarfile.REGTYPE, None),
                ("usr/share", 0o755, 0, 0, tarfile.DIRTYPE, None),
            ]),
            ("root directory duplicated", [
                ("./", 0o755, 0, 0, tarfile.DIRTYPE, None),
                (".", 0o755, 0, 0, tarfile.DIRTYPE, None),
            ]),
        ]
        for label, entries in cases:
            with self.subTest(label=label):
                with self.assertRaisesRegex(UnsafePayload, "Duplicate package archive path"):
                    verify_payload(io.BytesIO(make_archive(*entries)))


    def test_reject_file_directory_hierarchy_collisions_in_either_order(self):
        # Canonical path uniqueness is insufficient: file usr/lib and
        # usr/lib/data are distinct names but cannot coexist on disk.
        cases = [
            ("file before child", [
                ("./usr/lib", 0o644, 0, 0, tarfile.REGTYPE, None),
                ("./usr/lib/data", 0o644, 0, 0, tarfile.REGTYPE, None),
            ], "ancestor"),
            ("child before file", [
                ("./usr/lib/data", 0o644, 0, 0, tarfile.REGTYPE, None),
                ("./usr/lib", 0o644, 0, 0, tarfile.REGTYPE, None),
            ], "replaces"),
            ("deep nested child", [
                ("./usr", 0o644, 0, 0, tarfile.REGTYPE, None),
                ("./usr/lib/ricebowl/tool", 0o644, 0, 0, tarfile.REGTYPE, None),
            ], "ancestor"),
        ]
        for label, entries, diagnostic in cases:
            with self.subTest(label=label), self.assertRaisesRegex(UnsafePayload, diagnostic):
                verify_payload(io.BytesIO(make_archive(*entries)))
        # An implicit parent may subsequently become an explicit directory.
        safe = make_archive(
            ("./usr/lib/ricebowl/tool", 0o644, 0, 0, tarfile.REGTYPE, None),
            ("./usr/lib/", 0o755, 0, 0, tarfile.DIRTYPE, None),
            ("./usr/", 0o755, 0, 0, tarfile.DIRTYPE, None),
        )
        self.assertEqual(verify_payload(io.BytesIO(safe)), 3)

    def test_reject_root_file_control_characters_and_oversized_name(self):
        for label, name, diagnostic in (
            ("root regular file", "./", "root"),
            ("linebreak path", "./usr/bin/evil\nname", "Unsafe"),
            ("overlong filename component", "./usr/bin/" + "x" * 256, "Oversized"),
        ):
            with self.subTest(label=label), self.assertRaisesRegex(UnsafePayload, diagnostic):
                verify_payload(io.BytesIO(make_archive(
                    (name, 0o644, 0, 0, tarfile.REGTYPE, None))))
        # Untrusted tar numeric owner 0 must not carry another user/group name.
        for field in ("uname", "gname"):
            obj = tarfile.TarInfo("./usr/bin/riceplate-native")
            obj.mode = 0o755
            obj.size = 1
            setattr(obj, field, "unprivileged")
            sink = io.BytesIO()
            with tarfile.open(fileobj=sink, mode="w") as archive:
                archive.addfile(obj, io.BytesIO(b"x"))
            with self.subTest(field=field), self.assertRaisesRegex(UnsafePayload, "Non-root"):
                verify_payload(io.BytesIO(sink.getvalue()))

    def test_reject_pax_extended_attributes_in_debian_payload(self):
        member = tarfile.TarInfo("./usr/bin/riceplate-native")
        member.mode, member.uid, member.gid = 0o755, 0, 0
        member.size = 1
        # No xattrs/capability metadata are part of RiceBowl's immutable
        # Debian bundle. Reject them before extraction, regardless of whether
        # a particular dpkg/tar version would later honor those fields.
        member.pax_headers = {"SCHILY.xattr.security.capability": "unreviewed"}
        sink = io.BytesIO()
        with tarfile.open(fileobj=sink, mode="w", format=tarfile.PAX_FORMAT) as archive:
            archive.addfile(member, io.BytesIO(b"x"))
        with self.assertRaisesRegex(UnsafePayload, "extended package metadata"):
            verify_payload(io.BytesIO(sink.getvalue()))

    def test_cli_rejects_duplicate_destinations(self):
        crafted = make_archive(
            ("./usr/bin/riceplate-native", 0o755, 0, 0, tarfile.REGTYPE, None),
            ("usr/bin/riceplate-native", 0o755, 0, 0, tarfile.REGTYPE, None),
        )
        result = subprocess.run([sys.executable, str(CHECKER)], input=crafted,
                                capture_output=True, timeout=5, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"Duplicate package archive path", result.stderr)

    def test_reject_compressed_archive_bomb_limits(self):
        entries = [
            (f"./usr/share/file-{index}", 0o644, 0, 0, tarfile.REGTYPE, None)
            for index in range(3)
        ]
        archive = make_archive(*entries)
        with patch("scripts.verify_wayland_payload.MAX_PAYLOAD_ENTRIES", 2):
            with self.assertRaisesRegex(UnsafePayload, "Too many package archive entries"):
                verify_payload(io.BytesIO(archive))
        # Two valid 8-byte regular files exceed a small injected byte cap.
        # The production cap remains 512 MiB; no giant fixture is needed.
        with patch("scripts.verify_wayland_payload.MAX_PAYLOAD_BYTES", 12):
            with self.assertRaisesRegex(UnsafePayload, "uncompressed size limit"):
                verify_payload(io.BytesIO(archive))

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
