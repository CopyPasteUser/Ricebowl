"""Read SG7 evidence without following symlinks or opening special files.

These receipts are *software CI measurements*, not hardware attestation.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path


class ReceiptReadError(ValueError):
    """A receipt could not be read as one stable, bounded regular file."""


def read_regular_bytes(path: Path, *, limit: int) -> bytes:
    """Acquire exactly one bounded file descriptor; refuse races and aliases.

    O_NONBLOCK prevents a pathname swap to a FIFO from indefinitely blocking
    the verifier before fstat can reject the non-regular descriptor.
    """
    if type(limit) is not int or limit <= 0:
        raise ReceiptReadError("Invalid SG7 receipt size limit")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC |
                             os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise ReceiptReadError("Cannot safely open SG7 receipt") from exc
    try:
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
                raise ReceiptReadError("SG7 receipt is not a bounded regular file")
            payload = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
            # A producer can atomically rename a different file over this
            # pathname while the old descriptor remains perfectly readable.
            # Confirm the verified inode is still the one named by the path.
            current = os.stat(path, follow_symlinks=False)
            identity = lambda st: (st.st_dev, st.st_ino, st.st_size,
                                   st.st_mtime_ns, st.st_ctime_ns)
            if (len(payload) != before.st_size or before.st_nlink == 0
                    or after.st_nlink == 0 or identity(before) != identity(after)
                    or identity(after) != identity(current)):
                raise ReceiptReadError("SG7 receipt changed during verification")
            return payload
    except OSError as exc:
        raise ReceiptReadError("Cannot safely read SG7 receipt") from exc
