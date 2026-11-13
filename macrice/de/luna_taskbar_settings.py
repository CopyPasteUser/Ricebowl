"""Opt-in Luna taskbar layout settings; owner-private, atomic and CAS guarded.

Only the native Wayland Luna profile reads these at next login. This module
never changes the existing XFCE panel, labwc config or global file defaults.
"""
from __future__ import annotations

import fcntl
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Mapping

DEFAULTS = {"auto_hide": False, "quick_launch": True}
_NAME = "luna-taskbar.json"
_MAX_BYTES = 256


class TaskbarSettingsError(ValueError):
    """Preferences are invalid, unsafe or were changed by another editor."""


def _directory() -> Path:
    root = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    if not root.is_absolute():
        raise TaskbarSettingsError("XDG_CONFIG_HOME must be absolute")
    return root / "ricebowl"


def _validate(value: object) -> dict[str, bool]:
    if (not isinstance(value, dict) or set(value) != set(DEFAULTS)
            or any(type(value[k]) is not bool for k in DEFAULTS)):
        raise TaskbarSettingsError("Expected exactly two boolean taskbar settings")
    return {key: value[key] for key in DEFAULTS}


def _dir_checked(path: Path, *, create: bool = False) -> None:
    if create:
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o022):
        raise TaskbarSettingsError("Unsafe taskbar preference directory")


def load() -> dict[str, bool]:
    directory = _directory()
    _dir_checked(directory)
    try:
        fd = os.open(directory / _NAME,
                     os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return dict(DEFAULTS)
    except OSError as exc:
        raise TaskbarSettingsError("Cannot open Luna taskbar preferences") from exc
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_size > _MAX_BYTES):
            raise TaskbarSettingsError("Unsafe Luna taskbar settings file")
        raw = stream.read(_MAX_BYTES + 1)
    if len(raw) > _MAX_BYTES:
        raise TaskbarSettingsError("Taskbar settings exceed size limit")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise TaskbarSettingsError("Invalid taskbar settings JSON") from exc
    if (not isinstance(data, dict) or type(data.get("version")) is not int
            or data["version"] != 1):
        raise TaskbarSettingsError("Unsupported taskbar settings version")
    return _validate({k: v for k, v in data.items() if k != "version"})


def save(desired: Mapping, *, expected: Mapping) -> dict[str, bool]:
    values = _validate(dict(desired))
    previous = _validate(dict(expected))
    directory = _directory()
    _dir_checked(directory, create=True)
    try:
        fd = os.open(directory / ".luna-taskbar.lock",
                     os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    except OSError as exc:
        raise TaskbarSettingsError("Cannot acquire Luna taskbar lock") from exc
    with os.fdopen(fd, "rb") as lock:
        info = os.fstat(lock.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077):
            raise TaskbarSettingsError("Unsafe taskbar settings lock")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if load() != previous:
            raise TaskbarSettingsError("Taskbar settings changed elsewhere; reload")
        fd, name = tempfile.mkstemp(prefix=".luna-taskbar-", dir=directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(json.dumps({"version": 1, **values},
                                        sort_keys=True).encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, directory / _NAME)
            dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
        finally:
            Path(name).unlink(missing_ok=True)
    return values
