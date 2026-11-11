"""Optional, owner-private next-login RicePop banner preferences.

The active notification host is never reconfigured from this module; the
Wayland session supervisor renders a small disposable Mako config at login.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Mapping

from . import preferences


DEFAULTS = {"font_family": "Sans", "font_size": 12,
            "default_timeout": 0, "max_visible": 5}
_FAMILY = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}\Z")
_SIZES = (10, 12, 14, 16)
_TIMEOUTS = (0, 4000, 7000, 12000)
_COUNTS = (2, 3, 5, 8)
_FILE = "ricepop-appearance.json"


def validate(values: Mapping) -> dict:
    if not isinstance(values, Mapping) or set(values) != set(DEFAULTS):
        raise ValueError("Unsupported RicePop appearance fields")
    value = dict(values)
    if (type(value["font_family"]) is not str
            or not _FAMILY.fullmatch(value["font_family"])
            or type(value["font_size"]) is not int or value["font_size"] not in _SIZES
            or type(value["default_timeout"]) is not int
            or value["default_timeout"] not in _TIMEOUTS
            or type(value["max_visible"]) is not int
            or value["max_visible"] not in _COUNTS):
        raise ValueError("Unsupported RicePop font or notification duration")
    return value


def load_optional() -> dict | None:
    raw = preferences._checked_file(preferences._directory() / _FILE)
    if raw is None:
        return None
    if len(raw) > 2048:
        raise ValueError("RicePop settings are oversized")
    try:
        obj = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("RicePop settings are invalid JSON") from exc
    if (type(obj) is not dict or type(obj.get("version")) is not int
            or obj["version"] != 1):
        raise ValueError("Unsupported RicePop settings version")
    return validate({key: value for key, value in obj.items() if key != "version"})


def load() -> dict:
    return load_optional() or dict(DEFAULTS)


def save(values: Mapping, *, expected: Mapping) -> dict:
    """Compare-and-set; no effect on another session or active Mako process."""
    candidate, old = validate(values), validate(expected)
    directory = preferences._directory()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o022):
        raise ValueError("RiceBowl configuration directory is not private")
    descriptor = os.open(directory / ".ricepop.lock", os.O_CREAT | os.O_RDWR |
                         os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(descriptor, "rb") as lock:
        info = os.fstat(lock.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077):
            raise ValueError("Unsafe RicePop preference lock")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if load() != old:
            raise ValueError("RicePop settings changed; refresh before applying")
        fd, temporary = tempfile.mkstemp(prefix=".ricepop-", dir=directory)
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(json.dumps({"version": 1, **candidate},
                                      sort_keys=True).encode("utf-8"))
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, directory / _FILE)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return candidate


def render(values: Mapping) -> str:
    """Only a small vetted subset of Mako's upstream configuration language."""
    value = validate(values)
    return ("# RiceBowl Wayland RicePop: private per-login notification host\n"
            f"font={value['font_family']} {value['font_size']}\n"
            f"default-timeout={value['default_timeout']}\n"
            f"max-visible={value['max_visible']}\n"
            "[mode=ricebowl-do-not-disturb]\n"
            "invisible=1\n")
