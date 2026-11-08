"""Private, manually applied Wayland output layout snapshot (never auto-applied)."""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Iterable

from . import preferences, wayland_displays


_FILE = "ricespice-displays.json"
_STORED_MODE = re.compile(r"[0-9]{3,5}x[0-9]{3,5}@[0-9]{1,3}(?:\.[0-9]{1,8})?Hz\Z")


def _validated(entries: object) -> list[dict]:
    if type(entries) is not list or len(entries) > 8:
        raise ValueError("Invalid saved monitor count")
    checked = []
    used = set()
    for value in entries:
        if type(value) is not dict or set(value) != {"name", "mode", "scale", "x", "y"}:
            raise ValueError("Invalid saved monitor entry")
        name, mode, scale = value["name"], value["mode"], value["scale"]
        if (type(name) is not str or not wayland_displays._SAFE_NAME.fullmatch(name)
                or name in used or type(mode) is not str
                or not _STORED_MODE.fullmatch(mode)):
            raise ValueError("Invalid saved monitor identity/mode")
        if (type(scale) not in (float, int) or not 0.5 <= scale <= 4
                or any(type(value[key]) is not int or abs(value[key]) > 16384
                       for key in ("x", "y"))):
            raise ValueError("Invalid saved monitor scale/position")
        used.add(name)
        checked.append({"name": name, "mode": mode, "scale": float(scale),
                        "x": value["x"], "y": value["y"]})
    return checked


def load() -> list[dict]:
    raw = preferences._checked_file(preferences._directory() / _FILE)
    if raw is None:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Invalid saved monitor JSON") from exc
    if (type(data) is not dict or set(data) != {"version", "outputs"}
            or type(data["version"]) is not int or data["version"] != 1):
        raise ValueError("Unsupported saved monitor format")
    return _validated(data["outputs"])


def from_outputs(outputs: Iterable[wayland_displays.Output]) -> list[dict]:
    return _validated([{"name": item.name, "mode": item.current_mode,
                        "scale": item.scale, "x": item.position[0], "y": item.position[1]}
                       for item in outputs])


def save(entries: list[dict], *, expected: list[dict]) -> list[dict]:
    """Atomically replace a single private preset only after checking its version."""
    candidate = _validated(entries)
    old = _validated(expected)
    directory = preferences._directory()
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    metadata = directory.lstat()
    if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid()
            or metadata.st_mode & 0o022):
        raise ValueError("Unsafe RiceBowl configuration directory")
    lock_fd = os.open(directory / ".ricespice-displays.lock",
                      os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(lock_fd, "rb") as lock:
        metadata = os.fstat(lock.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                or metadata.st_mode & 0o077):
            raise ValueError("Unsafe monitor preset lock")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if load() != old:
            raise ValueError("Saved monitor layout changed; refresh before replacing")
        fd, temporary = tempfile.mkstemp(prefix=".ricespice-displays-", dir=directory)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(json.dumps({"version": 1, "outputs": candidate},
                                        sort_keys=True).encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, directory / _FILE)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return candidate
