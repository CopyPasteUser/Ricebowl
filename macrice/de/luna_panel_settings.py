"""Owner-private XP Luna taskbar options, applied by native RicePlate at login.

This is deliberately separate from the generic RiceSpice input/accessibility
schema. Saving never changes XFCE, a running panel or global system settings.
"""
from __future__ import annotations

import fcntl
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Mapping

DEFAULTS = {"clock_format": "24h"}
FORMATS = ("24h", "12h")
_MAX_BYTES = 256
_NAME = "luna-panel.json"


class LunaPanelError(ValueError):
    """Luna panel preferences are malformed, unsafe or changed concurrently."""


def _directory() -> Path:
    root = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    if not Path(root).is_absolute():
        raise LunaPanelError("XDG_CONFIG_HOME must be absolute")
    return Path(root) / "ricebowl"


def _validate(values: object) -> dict[str, str]:
    if (not isinstance(values, dict) or set(values) != {"clock_format"}
            or type(values["clock_format"]) is not str
            or values["clock_format"] not in FORMATS):
        raise LunaPanelError("Unsupported Luna clock format")
    return {"clock_format": values["clock_format"]}


def _check_directory(directory: Path, *, create: bool = False) -> None:
    if create:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        info = directory.lstat()
    except FileNotFoundError:
        return
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o022):
        raise LunaPanelError("Unsafe RiceBowl settings directory")


def _read(directory: Path) -> bytes | None:
    _check_directory(directory)
    try:
        fd = os.open(directory / _NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise LunaPanelError("Cannot read private Luna settings") from exc
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_size > _MAX_BYTES):
            raise LunaPanelError("Unsafe Luna settings file")
        data = stream.read(_MAX_BYTES + 1)
    if len(data) > _MAX_BYTES:
        raise LunaPanelError("Luna settings exceed size limit")
    return data


def _decode(raw: bytes | None) -> dict[str, str]:
    if raw is None:
        return dict(DEFAULTS)
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, ValueError) as exc:
        raise LunaPanelError("Invalid Luna settings JSON") from exc
    if not isinstance(data, dict) or data.get("version") != 1:
        raise LunaPanelError("Unsupported Luna settings version")
    if type(data["version"]) is not int:
        raise LunaPanelError("Unsupported Luna settings version")
    return _validate({k: v for k, v in data.items() if k != "version"})


def load() -> dict[str, str]:
    return _decode(_read(_directory()))


def save(values: Mapping, *, expected: Mapping) -> dict[str, str]:
    """Compare-and-swap commit, never overwrite concurrent user changes."""
    desired = _validate(dict(values))
    before = _validate(dict(expected))
    directory = _directory()
    _check_directory(directory, create=True)
    try:
        fd = os.open(directory / ".luna-panel.lock",
                     os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    except OSError as exc:
        raise LunaPanelError("Cannot open Luna preference lock") from exc
    with os.fdopen(fd, "rb") as lock:
        meta = os.fstat(lock.fileno())
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.geteuid()
                or meta.st_mode & 0o077):
            raise LunaPanelError("Unsafe Luna preference lock")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if load() != before:
            raise LunaPanelError("Luna settings changed elsewhere; refresh before saving")
        fd, temporary = tempfile.mkstemp(prefix=".luna-panel-", dir=directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                data = json.dumps({"version": 1, **desired}, sort_keys=True).encode("utf-8")
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, directory / _NAME)
            directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return desired
