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


def verify_payload(stream: BinaryIO) -> int:
    count = 0
    total_file_bytes = 0
    seen_paths: set[PurePosixPath] = set()
    try:
        with tarfile.open(fileobj=stream, mode="r|") as archive:
            for item in archive:
                count += 1
                if count > MAX_PAYLOAD_ENTRIES:
                    raise UnsafePayload("Too many package archive entries")
                name = item.name
                path = PurePosixPath(name)
                if not name or path.is_absolute() or ".." in path.parts:
                    raise UnsafePayload(f"Unsafe package archive path: {name!r}")
                # A tar can spell the same destination with or without "./".
                # Reject every second entry, including file/directory swaps:
                # dpkg's last-write-wins behavior must not mask earlier data.
                if path in seen_paths:
                    raise UnsafePayload(f"Duplicate package archive path: {name!r}")
                seen_paths.add(path)
                # Debian packages are installed by root. A forged archive must
                # not create files owned by arbitrary numeric users/groups.
                if item.uid != 0 or item.gid != 0:
                    raise UnsafePayload(f"Non-root package payload owner: {name!r}")
                # Explicitly reject hardlinks too: an extracted hardlink can
                # alias another file despite a seemingly permitted path.
                if not (item.isfile() or item.isdir()):
                    raise UnsafePayload(f"Unsafe package payload entry type: {name!r}")
                if item.isdir() and item.size:
                    raise UnsafePayload(f"Directory entry has payload bytes: {name!r}")
                if item.isfile():
                    total_file_bytes += item.size
                    if item.size < 0 or total_file_bytes > MAX_PAYLOAD_BYTES:
                        raise UnsafePayload("Package archive exceeds uncompressed size limit")
                # No group/world write or setuid/setgid/sticky bits, including
                # on directories. These are never needed in RiceBowl's bundle.
                if item.mode & 0o7022:
                    raise UnsafePayload(f"Unsafe package payload permissions: {name!r}")
    except (tarfile.TarError, EOFError, OSError) as exc:
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
