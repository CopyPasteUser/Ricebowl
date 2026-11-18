#!/usr/bin/env python3
"""Read-only validation of a data-only RiceBowl preview Debian control.tar.

The four opt-in Wayland packages must contain no maintainer scripts, aliases,
links, special files or extended attributes. This verifier does not extract.
"""
from __future__ import annotations

import sys
import tarfile
from pathlib import PurePosixPath
from typing import BinaryIO

MAX_CONTROL_BYTES = 1024 * 1024
MAX_CONTROL_ENTRIES = 3  # optional root, required control, optional md5sums
MAX_CONTROL_PATH_BYTES = 4096
MAX_CONTROL_COMPONENT_BYTES = 255


class UnsafeControl(ValueError):
    """An untrusted control archive violates the data-only package contract."""


def verify_control(stream: BinaryIO) -> int:
    seen: set[PurePosixPath] = set()
    total = 0
    try:
        with tarfile.open(fileobj=stream, mode="r|") as archive:
            for item in archive:
                # Normalize aliases only after bounding their raw representation.
                # Repeated './' segments can otherwise produce a multi-megabyte
                # GNU longname which still resolves to the allowed 'control'.
                if len(item.name.encode("utf-8", "surrogateescape")) > MAX_CONTROL_PATH_BYTES:
                    raise UnsafeControl("Oversized control archive path")
                path = PurePosixPath(item.name)
                if any(len(part.encode("utf-8", "surrogateescape")) > MAX_CONTROL_COMPONENT_BYTES
                       for part in path.parts):
                    raise UnsafeControl("Oversized control archive path component")
                if (not item.name or path.is_absolute() or ".." in path.parts
                        or any(ord(c) < 32 or ord(c) == 127 for c in item.name)):
                    raise UnsafeControl("Unsafe control archive path")
                if path in seen:
                    raise UnsafeControl("Duplicate control archive destination")
                seen.add(path)
                # Detect a forbidden maintainer script before the entry-count
                # cap: real dpkg control tarballs may contain root, control
                # and md5sums before an injected postinst. The error must
                # identify the security violation, never mask it as size.
                if path not in (PurePosixPath("."), PurePosixPath("control"),
                                PurePosixPath("md5sums")):
                    raise UnsafeControl("Refusing maintainer scripts or unexpected control archive entries")
                if len(seen) > MAX_CONTROL_ENTRIES:
                    raise UnsafeControl("Too many control archive entries")
                if (item.uid != 0 or item.gid != 0 or item.uname not in ("", "root")
                        or item.gname not in ("", "root") or item.pax_headers
                        or item.sparse is not None or item.linkname):
                    raise UnsafeControl("Unsafe control archive metadata")
                if path == PurePosixPath("."):
                    if not item.isdir() or item.size or item.mode not in (0o700, 0o755):
                        raise UnsafeControl("Unsafe control root directory")
                    continue
                if not item.isfile() or item.mode not in (0o600, 0o644) or item.size < 0:
                    raise UnsafeControl("Unsafe control archive file")
                total += item.size
                if total > MAX_CONTROL_BYTES:
                    raise UnsafeControl("Control archive exceeds uncompressed size cap")
    except (tarfile.TarError, EOFError, OSError, UnicodeError) as exc:
        raise UnsafeControl("Malformed control archive") from exc
    if PurePosixPath("control") not in seen:
        raise UnsafeControl("Missing Debian control metadata")
    return len(seen)


def main() -> int:
    try:
        count = verify_control(sys.stdin.buffer)
    except UnsafeControl as exc:
        print(f"RiceBowl control archive: BLOCKED — {exc}", file=sys.stderr)
        return 1
    print(f"Verified {count} data-only Debian control entries", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
