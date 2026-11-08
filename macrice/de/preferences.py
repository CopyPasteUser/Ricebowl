"""Owner-private, next-login RiceSpice preferences for the opt-in labwc session.

No setting here writes to XFCE, ~/.config/labwc, GSettings or system services.
"""

from __future__ import annotations

import fcntl
import json
import os
import stat
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Mapping


DEFAULTS = {
    "input_enabled": False,
    "accessibility_enabled": False,
    "screen_reader_enabled": False,
    "high_contrast": False,
    "pointer_speed": 0.0,
    "natural_scroll": False,
    "tap_to_click": True,
    "repeat_rate": 25,
    "repeat_delay": 600,
    "cursor_size": 24,
    "gtk_text_scale": 1.0,
}
_SPEEDS = (-1.0, -0.5, 0.0, 0.5, 1.0)
_RATES = (15, 25, 35, 50)
_DELAYS = (300, 450, 600, 800, 1000)
_CURSORS = (24, 32, 48, 64)
_TEXT_SCALES = (1.0, 1.25, 1.5)
_MAX_BYTES = 2048
_LEGACY_KEYS = set(DEFAULTS) - {"screen_reader_enabled", "high_contrast"}


class PreferenceError(ValueError):
    """RiceSpice input/preferences file is invalid, stale or unsafe."""


def _directory() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    if base is None:
        base = str(Path.home() / ".config")
    if not Path(base).is_absolute():
        raise PreferenceError("XDG_CONFIG_HOME must be absolute")
    return Path(base) / "ricebowl"


def _validate(values: object) -> dict:
    if not isinstance(values, dict) or set(values) != set(DEFAULTS):
        raise PreferenceError("Unexpected RiceSpice preference fields")
    result = dict(values)
    if (type(result["input_enabled"]) is not bool
            or type(result["accessibility_enabled"]) is not bool
            or type(result["screen_reader_enabled"]) is not bool
            or type(result["high_contrast"]) is not bool
            or type(result["pointer_speed"]) not in (int, float)
            or result["pointer_speed"] not in _SPEEDS
            or type(result["natural_scroll"]) is not bool
            or type(result["tap_to_click"]) is not bool
            or type(result["repeat_rate"]) is not int or result["repeat_rate"] not in _RATES
            or type(result["repeat_delay"]) is not int or result["repeat_delay"] not in _DELAYS
            or type(result["cursor_size"]) is not int or result["cursor_size"] not in _CURSORS
            or type(result["gtk_text_scale"]) not in (int, float)
            or result["gtk_text_scale"] not in _TEXT_SCALES):
        raise PreferenceError("Unsupported RiceSpice preference value")
    result["pointer_speed"] = float(result["pointer_speed"])
    result["gtk_text_scale"] = float(result["gtk_text_scale"])
    return result


def _checked_file(path: Path) -> bytes | None:
    parent = path.parent
    if parent.exists() or parent.is_symlink():
        info = parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o022):
            raise PreferenceError("Unsafe RiceBowl configuration directory")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise PreferenceError("Cannot read private RiceSpice preferences") from exc
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > _MAX_BYTES):
            raise PreferenceError("Unsafe RiceSpice preference file")
        return stream.read(_MAX_BYTES + 1)


def load() -> dict:
    return _decode(_checked_file(_directory() / "ricespice.json"))


def load_optional() -> dict | None:
    raw = _checked_file(_directory() / "ricespice.json")
    return None if raw is None else _decode(raw)


def _decode(raw: bytes | None) -> dict:
    if raw is None:
        return dict(DEFAULTS)
    if len(raw) > _MAX_BYTES:
        raise PreferenceError("RiceSpice preferences exceed the size limit")
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise PreferenceError("Invalid RiceSpice preference JSON") from exc
    if (not isinstance(obj, dict) or type(obj.get("version")) is not int
            or obj["version"] not in (1, 2)):
        raise PreferenceError("Unsupported RiceSpice preference version")
    data = {key: value for key, value in obj.items() if key != "version"}
    if obj["version"] == 1:
        if set(data) != _LEGACY_KEYS:
            raise PreferenceError("Invalid legacy RiceSpice preference fields")
        data.update(screen_reader_enabled=False, high_contrast=False)
    return _validate(data)


def save(values: Mapping, *, expected: Mapping) -> dict:
    """Write only after checking the snapshot the UI actually displayed."""
    new = _validate(dict(values))
    old = _validate(dict(expected))
    directory = _directory()
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = directory.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o022):
        raise PreferenceError("RiceBowl settings directory must not be group-writable")
    lock_fd = os.open(directory / ".ricespice.lock", os.O_CREAT | os.O_RDWR |
                      os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(lock_fd, "rb") as lock:
        lock_info = os.fstat(lock.fileno())
        if (not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.getuid()
                or lock_info.st_mode & 0o077):
            raise PreferenceError("Unsafe RiceSpice preference lock")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if load() != old:
            raise PreferenceError("Preferences changed elsewhere; refresh before applying")
        fd, name = tempfile.mkstemp(prefix=".ricespice-", dir=directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(json.dumps({"version": 2, **new}, sort_keys=True).encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, directory / "ricespice.json")
        finally:
            Path(name).unlink(missing_ok=True)
    return new


def configure_labwc(path: Path, values: Mapping) -> None:
    """Modify only the copied, per-session compositor XML."""
    values = _validate(dict(values))
    if not values["input_enabled"]:
        return
    root = ET.parse(path)
    keyboard = root.getroot().find("keyboard")
    if keyboard is None:
        keyboard = ET.SubElement(root.getroot(), "keyboard")
    for key, name in (("repeat_rate", "repeatRate"), ("repeat_delay", "repeatDelay")):
        ET.SubElement(keyboard, name).text = str(values[key])
    libinput = ET.SubElement(root.getroot(), "libinput")
    for category in ("default", "touchpad"):
        device = ET.SubElement(libinput, "device", category=category)
        ET.SubElement(device, "pointerSpeed").text = str(values["pointer_speed"])
        ET.SubElement(device, "naturalScroll").text = "yes" if values["natural_scroll"] else "no"
        if category == "touchpad":
            ET.SubElement(device, "tap").text = "yes" if values["tap_to_click"] else "no"
    root.write(path, encoding="utf-8", xml_declaration=True)


def apply_session_environment(env: dict[str, str], values: Mapping) -> None:
    values = _validate(dict(values))
    if values["accessibility_enabled"]:
        env["XCURSOR_SIZE"] = str(values["cursor_size"])
        env["GDK_DPI_SCALE"] = str(values["gtk_text_scale"])
        if values["high_contrast"]:
            env["GTK_THEME"] = "HighContrast"
