"""Explicit, private capture of the currently running Wayland output.

Not an automatic nested-session launcher: the user must run this inside the
desired compositor, and the resulting PNG can contain sensitive screen data.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

MAX_CAPTURE_BYTES = 64 * 1024 * 1024
MAX_DIMENSION = 8192
MAX_PIXELS = 16_777_216


class CaptureError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__({
            "invalid_capture_request": "Choose a new absolute .png output path",
            "capture_unavailable": "Requires a running Wayland session and grim",
            "capture_failed": "Wayland screenshot failed or was invalid",
        }[code])


def capture(output: Path | None, *, geometry: str | None = None) -> dict[str, object]:
    """Capture on explicit invocation; never overwrite files, including symlinks."""
    if output is None or not output.is_absolute() or output.suffix.lower() != ".png":
        raise CaptureError("invalid_capture_request")
    if not output.parent.is_dir() or os.path.lexists(output):
        raise CaptureError("invalid_capture_request")
    grim = shutil.which("grim")
    if not os.environ.get("WAYLAND_DISPLAY") or not grim:
        raise CaptureError("capture_unavailable")
    # Only accept the bounded rectangle grammar emitted by slurp.
    if geometry is not None:
        match = re.fullmatch(r"(-?\d+),(-?\d+) (\d+)x(\d+)", geometry)
        if not match or not (0 < int(match[3]) <= MAX_DIMENSION
                             and 0 < int(match[4]) <= MAX_DIMENSION
                             and int(match[3]) * int(match[4]) <= MAX_PIXELS):
            raise CaptureError("invalid_capture_request")

    try:
        descriptor, temporary = tempfile.mkstemp(prefix=".ricebowl-capture-", dir=output.parent)
    except OSError as exc:
        raise CaptureError("invalid_capture_request") from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            try:
                subprocess.run([grim, *(["-g", geometry] if geometry else []), "-"],
                               stdout=stream, stderr=subprocess.DEVNULL,
                               timeout=30, check=True)
            except (OSError, subprocess.SubprocessError) as exc:
                raise CaptureError("capture_failed") from exc
        size = os.stat(temporary).st_size
        if not 57 <= size <= MAX_CAPTURE_BYTES:
            raise CaptureError("capture_failed")
        with open(temporary, "rb") as stream:
            header = stream.read(33)
            stream.seek(-12, os.SEEK_END)
            trailer = stream.read(12)
        if (header[:8] != b"\x89PNG\r\n\x1a\n"
                or header[8:16] != b"\x00\x00\x00\x0dIHDR"
                or zlib.crc32(header[12:29]) != struct.unpack(">I", header[29:33])[0]
                or trailer != b"\x00\x00\x00\x00IEND\xaeB`\x82"):
            raise CaptureError("capture_failed")
        width, height = struct.unpack(">II", header[16:24])
        if (not 1 <= width <= MAX_DIMENSION or not 1 <= height <= MAX_DIMENSION
                or width * height > MAX_PIXELS):
            raise CaptureError("capture_failed")
        digest = hashlib.sha256()
        with open(temporary, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        try:
            os.link(temporary, output, follow_symlinks=False)
        except OSError as exc:
            raise CaptureError("invalid_capture_request") from exc
        return {
            "capture_version": 1,
            "source": "current-wayland-compositor",
            "path": str(output),
            "width": width,
            "height": height,
            "bytes": size,
            "sha256": digest.hexdigest(),
            "mutates_active_desktop": False,
        }
    except OSError as exc:
        raise CaptureError("capture_failed") from exc
    finally:
        os.unlink(temporary)
