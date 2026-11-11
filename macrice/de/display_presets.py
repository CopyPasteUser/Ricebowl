"""Private Wayland output snapshot with opt-in, guarded next-login trial."""

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


def _read() -> tuple[list[dict], bool]:
    raw = preferences._checked_file(preferences._directory() / _FILE)
    if raw is None:
        return [], False
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Invalid saved monitor JSON") from exc
    if type(data) is not dict or type(data.get("version")) is not int:
        raise ValueError("Unsupported saved monitor format")
    if data["version"] == 1 and set(data) == {"version", "outputs"}:
        return _validated(data["outputs"]), False
    if (data["version"] != 2 or set(data) != {"version", "outputs", "auto_trial"}
            or type(data["auto_trial"]) is not bool):
        raise ValueError("Unsupported saved monitor format")
    return _validated(data["outputs"]), data["auto_trial"]


def load() -> list[dict]:
    return _read()[0]


def auto_trial_enabled() -> bool:
    """No login changes unless the explicit v2 opt-in exists and is valid."""
    entries, enabled = _read()
    return bool(entries) and enabled


def from_outputs(outputs: Iterable[wayland_displays.Output]) -> list[dict]:
    return _validated([{"name": item.name, "mode": item.current_mode,
                        "scale": item.scale, "x": item.position[0], "y": item.position[1]}
                       for item in outputs])


def _directory_lock():
    directory = preferences._directory()
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    metadata = directory.lstat()
    if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid()
            or metadata.st_mode & 0o022):
        raise ValueError("Unsafe RiceBowl configuration directory")
    return directory, os.open(directory / ".ricespice-displays.lock",
                              os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)


def _write(directory: Path, entries: list[dict], enabled: bool) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".ricespice-displays-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(json.dumps({"version": 2, "outputs": entries, "auto_trial": enabled},
                                    sort_keys=True).encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, directory / _FILE)
    finally:
        Path(temporary).unlink(missing_ok=True)


def save(entries: list[dict], *, expected: list[dict]) -> list[dict]:
    """Replace the preset under a lock; changed layouts disable old auto-trust."""
    candidate, old = _validated(entries), _validated(expected)
    directory, lock_fd = _directory_lock()
    with os.fdopen(lock_fd, "rb") as lock:
        metadata = os.fstat(lock.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                or metadata.st_mode & 0o077):
            raise ValueError("Unsafe monitor preset lock")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        current, auto = _read()
        if current != old:
            raise ValueError("Saved monitor layout changed; refresh before replacing")
        _write(directory, candidate, auto if candidate == current else False)
    return candidate


def set_auto_trial(enabled: bool, *, expected: bool) -> bool:
    """Opt in/out only through an explicit, stale-safe RiceSpice action."""
    if type(enabled) is not bool or type(expected) is not bool:
        raise ValueError("Invalid automatic monitor trial state")
    directory, lock_fd = _directory_lock()
    with os.fdopen(lock_fd, "rb") as lock:
        metadata = os.fstat(lock.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                or metadata.st_mode & 0o077):
            raise ValueError("Unsafe monitor preset lock")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        entries, previous = _read()
        if not entries:
            raise ValueError("Save a monitor layout before enabling login restoration")
        if previous != expected:
            raise ValueError("Automatic monitor trial setting changed; refresh first")
        _write(directory, entries, enabled)
    return enabled
