"""User-local XP Start favorites and bounded recently launched applications."""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from .aero_pins import ID_PATTERN

START_FAVORITE_LIMIT = 4


@dataclass
class StartState:
    # None = the classic built-in Internet/mail defaults; () = user chose none.
    favorites: tuple[str, ...] | None = None
    launches: dict[str, tuple[int, int]] = field(default_factory=dict)


def state_path() -> Path:
    return (Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") /
            "ricehub" / "winxp-start.json")


def _validate(state: StartState):
    if state.favorites is not None:
        if (not isinstance(state.favorites, tuple) or
                len(state.favorites) > START_FAVORITE_LIMIT or
                len(set(state.favorites)) != len(state.favorites)):
            raise ValueError("Invalid XP Start favorites")
        if any(not isinstance(item, str) or not ID_PATTERN.fullmatch(item)
               for item in state.favorites):
            raise ValueError("Invalid desktop favorite")
    if not isinstance(state.launches, dict):
        raise ValueError("Invalid XP Start history")
    if len(state.launches) > 128:
        raise ValueError("XP Start history is too large")
    for identifier, entry in state.launches.items():
        if (not isinstance(identifier, str) or not ID_PATTERN.fullmatch(identifier)
                or not isinstance(entry, tuple)
                or len(entry) != 2 or any(type(value) is not int or value < 0
                                       for value in entry)):
            raise ValueError("Invalid XP Start history")


def load_start_state(path: Path | None = None) -> StartState:
    path = path or state_path()
    if path.is_symlink():
        raise ValueError("Refusing symlinked Start configuration")
    if not path.exists():
        return StartState()
    if not path.is_file() or path.stat().st_size > 32768:
        raise ValueError("Invalid Start configuration file")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema") != 1:
            raise ValueError("Unsupported Start configuration")
        raw_favorites = data.get("favorites")
        if raw_favorites is not None and not isinstance(raw_favorites, list):
            raise ValueError("Invalid favorites payload")
        favorites = None if raw_favorites is None else tuple(raw_favorites)
        raw_launches = data.get("launches", {})
        if not isinstance(raw_launches, dict):
            raise ValueError("Invalid history payload")
        launches = {}
        for identifier, entry in raw_launches.items():
            if not isinstance(entry, list):
                raise ValueError("Invalid history entry")
            launches[identifier] = tuple(entry)
        state = StartState(favorites, launches)
        _validate(state)
        return state
    except (OSError, UnicodeError, TypeError, ValueError, KeyError, AttributeError,
            json.JSONDecodeError) as exc:
        raise ValueError("Cannot read Start menu preferences") from exc


def save_start_state(state: StartState, path: Path | None = None) -> None:
    path = path or state_path()
    _validate(state)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Refusing symlinked Start configuration")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists() and not path.is_file():
        raise ValueError("Start configuration is not a regular file")
    payload = {"schema": 1, "favorites": state.favorites,
               "launches": {key: list(value) for key, value in state.launches.items()}}
    fd, temp = tempfile.mkstemp(prefix=".winxp-start-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def record_launch(state: StartState, identifier: str, *, now: int | None = None):
    """Record successful launches only, pruning stale entries to 80."""
    if not ID_PATTERN.fullmatch(identifier or ""):
        return
    timestamp = int(time.time()) if now is None else max(0, int(now))
    previous_count, previous_time = state.launches.get(identifier, (0, 0))
    # A backwards wall clock must not make a freshly launched app look older.
    timestamp = max(timestamp, previous_time)
    count = previous_count + 1
    state.launches[identifier] = min(1000000, count), timestamp
    if len(state.launches) > 80:
        ranked = sorted(state.launches.items(), key=lambda pair: pair[1][1], reverse=True)
        state.launches = dict(ranked[:80])


def clear_recent_programs(state: StartState) -> bool:
    """Forget recent-use history only; never erase the user's Start favorites."""
    if not state.launches:
        return False
    state.launches.clear()
    return True


def change_favorite(state: StartState, identifier: str, action: str,
                    defaults: tuple[str, ...] = ()) -> bool:
    """Add/remove/reorder pinned Start entries without altering taskbar pins."""
    if not ID_PATTERN.fullmatch(identifier or ""):
        return False
    pinned = list(defaults if state.favorites is None else state.favorites)
    if action == "pin" and identifier not in pinned and len(pinned) < START_FAVORITE_LIMIT:
        pinned.append(identifier)
    elif action == "unpin" and identifier in pinned:
        pinned.remove(identifier)
    elif action in ("up", "down") and identifier in pinned:
        old = pinned.index(identifier)
        new = old + (-1 if action == "up" else 1)
        if 0 <= new < len(pinned):
            pinned[old], pinned[new] = pinned[new], pinned[old]
        else:
            return False
    else:
        return False
    state.favorites = tuple(pinned)
    return True
