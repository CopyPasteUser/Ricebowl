#!/usr/bin/env python3
"""Read-only safety gate for the filesystem tar stream inside an opt-in .deb.

The shell bundle verifier checks allowed destinations and dependencies. This
gate checks metadata *before* the package is considered safe to install.
No extraction, privilege escalation, or host package modification occurs here.
"""
from __future__ import annotations

import sys
import tarfile
from pathlib import PurePosixPath
from typing import BinaryIO


class UnsafePayload(ValueError):
    """A package would install unsafe filesystem entries or metadata."""


# These are intentionally much larger than the current four-package preview,
# but rule out tiny compressed archives claiming unbounded install work.
MAX_PAYLOAD_ENTRIES = 100_000
MAX_PAYLOAD_BYTES = 512 * 1024 * 1024
MAX_PATH_BYTES = 4096
MAX_COMPONENT_BYTES = 255


def _canonical_path(item: tarfile.TarInfo) -> PurePosixPath:
    name = item.name
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or ".." in path.parts
            or any(ord(char) < 32 or ord(char) == 127 for char in name)):
        raise UnsafePayload(f"Unsafe package archive path: {name!r}")
    # A bounded POSIX-relative name protects the metadata verifier itself
    # from pathological archive headers and non-portable install paths.
    if (len(name.encode("utf-8", "surrogateescape")) > MAX_PATH_BYTES
            or any(len(part.encode("utf-8", "surrogateescape")) > MAX_COMPONENT_BYTES
                   for part in path.parts)):
        raise UnsafePayload(f"Oversized package archive path: {name!r}")
    if path == PurePosixPath(".") and not item.isdir():
        raise UnsafePayload("Package root cannot be a regular file")
    return path


def verify_payload(stream: BinaryIO) -> int:
    count = 0
    total_file_bytes = 0
    seen_paths: set[PurePosixPath] = set()
    file_paths: set[PurePosixPath] = set()
    required_directories: set[PurePosixPath] = set()
    try:
        with tarfile.open(fileobj=stream, mode="r|") as archive:
            for item in archive:
                count += 1
                if count > MAX_PAYLOAD_ENTRIES:
                    raise UnsafePayload("Too many package archive entries")

                path = _canonical_path(item)
                # Canonical paths collapse ./, repeated separators and
                # trailing slashes. Reject all duplicate file/dir aliases.
                if path in seen_paths:
                    raise UnsafePayload(f"Duplicate package archive path: {item.name!r}")
                seen_paths.add(path)
                # Order-independent hierarchy check. A regular file must not
                # be the parent of another entry or replace a parent that an
                # earlier entry already needs as a directory.
                parents = tuple(parent for parent in path.parents
                                if parent != PurePosixPath("."))
                if any(parent in file_paths for parent in parents):
                    raise UnsafePayload(f"File is an archive directory ancestor: {item.name!r}")
                if item.isfile() and path in required_directories:
                    raise UnsafePayload(f"File replaces an archive directory: {item.name!r}")
                required_directories.update(parents)
                # Numeric UID/GID are authoritative. Non-root name aliases,
                # PAX extended attributes and GNU sparse files are unnecessary
                # for the immutable preview bundle and ambiguous to verify.
                if (item.uid != 0 or item.gid != 0
                        or item.uname not in ("", "root")
                        or item.gname not in ("", "root")):
                    raise UnsafePayload(f"Non-root package payload owner: {item.name!r}")
                if item.pax_headers or item.sparse is not None:
                    raise UnsafePayload(f"Unsupported extended package metadata: {item.name!r}")
                # Explicitly reject symlinks, hardlinks, special entries and
                # unexpected link targets on otherwise normal file entries.
                if not (item.isfile() or item.isdir()) or item.linkname:
                    raise UnsafePayload(f"Unsafe package payload entry type: {item.name!r}")
                if item.isdir() and item.size:
                    raise UnsafePayload(f"Directory entry has payload bytes: {item.name!r}")
                if item.isfile():
                    total_file_bytes += item.size
                    if item.size < 0 or total_file_bytes > MAX_PAYLOAD_BYTES:
                        raise UnsafePayload("Package archive exceeds uncompressed size limit")
                    file_paths.add(path)
                # No group/world write or setuid/setgid/sticky bits; out-of-
                # range mode bits are likewise invalid for these packages.
                if item.mode < 0 or item.mode > 0o7777 or item.mode & 0o7022:
                    raise UnsafePayload(f"Unsafe package payload permissions: {item.name!r}")
    except (tarfile.TarError, EOFError, OSError, UnicodeError) as exc:
        raise UnsafePayload("Malformed package filesystem tar stream") from exc
    if not count:
        raise UnsafePayload("Empty package filesystem tar stream")
    return count


def main() -> int:
    try:
        count = verify_payload(sys.stdin.buffer)
    except UnsafePayload as exc:
        print(f"RiceBowl package payload: BLOCKED — {exc}", file=sys.stderr)
        return 1
    print(f"Verified {count} package filesystem entries", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
