"""Crash-independent, time-limited X11 mode/position changes for Aqua.

Only a single *already active* output can change. The detached helper owns
both the xrandr write and its automatic rollback; closing/crashing the GTK
client cannot approve the change. All requests stay inside the user's private
XDG_RUNTIME_DIR and no privileged services or shells are used.
"""

from __future__ import annotations

import fcntl
import json
import os
import secrets
import stat
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

if __package__:
    from . import display_layout
else:
    # The independent rollback helper executes this very file even when
    # RiceBowl is installed as a self-contained copy without site-packages.
    import display_layout


TIMEOUT_SECONDS = 18
_MAX_FILE = 4096
_STATES = frozenset(("starting", "pending", "kept", "reverted", "failed", "revert-failed"))


def _unique_record(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject ambiguous JSON before acting on a monitor transaction."""
    record: dict[str, object] = {}
    for key, value in pairs:
        if key in record:
            raise ValueError("Duplicate display transaction field")
        record[key] = value
    return record


@dataclass(frozen=True)
class DisplayChange:
    token: str
    root: Path


def runtime_root() -> Path:
    value = os.environ.get("XDG_RUNTIME_DIR")
    if not value or not Path(value).is_absolute():
        raise RuntimeError("Private XDG_RUNTIME_DIR is required for safe display changes")
    runtime = Path(value)
    if runtime.is_symlink() or not runtime.is_dir():
        raise RuntimeError("Invalid session runtime directory")
    if runtime.stat().st_uid != os.getuid() or runtime.stat().st_mode & 0o077:
        raise RuntimeError("Session runtime directory is not private")
    root = runtime / "ricebowl-display-guard"
    if root.is_symlink():
        raise RuntimeError("Unsafe display guard directory")
    root.mkdir(mode=0o700, exist_ok=True)
    if root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
        raise RuntimeError("Display guard directory is not private")
    return root


def _request_path(change: DisplayChange) -> Path:
    if len(change.token) != 32 or any(char not in "0123456789abcdef" for char in change.token):
        raise ValueError("Invalid display change token")
    return change.root / f"{change.token}.request"


def _state_path(change: DisplayChange) -> Path:
    _request_path(change)
    return change.root / f"{change.token}.state"


def _keep_path(change: DisplayChange) -> Path:
    _request_path(change)
    return change.root / f"{change.token}.keep"


def _keep_requested(change: DisplayChange) -> bool:
    """Require the exact private confirmation marker, not merely an existing path.

    A malformed, stale or symlinked marker must never approve a display
    change. The independent timeout worker will instead perform its rollback.
    """
    path = _keep_path(change)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return False
    with os.fdopen(fd, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                or metadata.st_mode & 0o077 or not 1 <= metadata.st_size <= 64):
            return False
        try:
            record = json.loads(stream.read(65), object_pairs_hook=_unique_record)
        except (ValueError, UnicodeError, RecursionError):
            return False
    return type(record) is dict and set(record) == {"keep"} and record["keep"] is True


def _write_new(path: Path, value: dict) -> None:
    body = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(body) > _MAX_FILE:
        raise ValueError("Display change request is too large")
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


def _write_state(change: DisplayChange, state: str, detail: str = "") -> None:
    if state not in _STATES:
        raise ValueError("Invalid display change state")
    temporary = change.root / ("." + change.token + ".tmp")
    # Only one worker for this token. O_EXCL also rejects stale/foreign files.
    _write_new(temporary, {"state": state, "detail": detail[:180], "at": time.time()})
    try:
        os.replace(temporary, _state_path(change))
    finally:
        temporary.unlink(missing_ok=True)


def read_status(change: DisplayChange) -> tuple[str, str]:
    path = _state_path(change)
    try:
        if path.is_symlink() or path.stat().st_size > _MAX_FILE:
            raise ValueError("Invalid display change status file")
        data = json.loads(path.read_text(encoding="utf-8"),
                          object_pairs_hook=_unique_record)
    except FileNotFoundError:
        return "starting", "Waiting for independent display guard"
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise RuntimeError("Cannot read display guard status") from exc
    if (not isinstance(data, dict) or data.get("state") not in _STATES
            or not isinstance(data.get("detail"), str)):
        raise ValueError("Invalid display guard status")
    return data["state"], data["detail"][:180]


def _validated_output(name: str, mode: str, x: int, y: int, outputs) -> tuple[str, int, int]:
    if type(x) is not int or type(y) is not int or abs(x) > 16384 or abs(y) > 16384:
        raise ValueError("Display position is outside the supported range")
    source = next((item for item in outputs if item.name == name), None)
    if source is None or source.current_mode is None or source.position is None:
        raise ValueError("Only active, connected displays can be edited")
    if mode not in source.modes:
        raise ValueError("The selected display does not advertise this mode")
    return source.current_mode, *source.position


def begin_change(name: str, mode: str, x: int, y: int) -> DisplayChange:
    outputs = display_layout.read_monitor_layout()
    old_mode, old_x, old_y = _validated_output(name, mode, x, y, outputs)
    if (mode, x, y) == (old_mode, old_x, old_y):
        raise ValueError("Display configuration is already set to these values")
    root = runtime_root()
    change = DisplayChange(secrets.token_hex(16), root)
    request = _request_path(change)
    _write_new(request, {"name": name, "mode": mode, "x": x, "y": y,
                         "old_mode": old_mode, "old_x": old_x, "old_y": old_y})
    try:
        subprocess.Popen((sys.executable, str(Path(__file__).resolve()), "--worker",
                          str(root), change.token), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         close_fds=True, start_new_session=True)
    except OSError as exc:
        request.unlink(missing_ok=True)
        raise RuntimeError("Could not start the independent display rollback guard") from exc
    return change


def keep_change(change: DisplayChange) -> None:
    state, _ = read_status(change)
    if state != "pending":
        raise RuntimeError("The display change is not waiting for confirmation")
    _write_new(_keep_path(change), {"keep": True})


def _run_xrandr(name: str, mode: str, x: int, y: int) -> None:
    command = ("xrandr", "--output", name, "--mode", mode, "--pos", f"{x}x{y}")
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=6, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("X11 display change timed out or xrandr is unavailable") from exc
    if result.returncode:
        raise RuntimeError("X11 rejected the display change")


def _check_current(name: str, mode: str, x: int, y: int) -> bool:
    return any(item.name == name and item.current_mode == mode
               and item.position == (x, y) for item in display_layout.read_monitor_layout())


def run_worker(change: DisplayChange) -> int:
    """Run only in the detached helper. Never launch on the GTK main loop."""
    request = _request_path(change)
    if request.is_symlink() or request.stat().st_size > _MAX_FILE:
        raise ValueError("Unsafe display change request")
    data = json.loads(request.read_text(encoding="utf-8"),
                      object_pairs_hook=_unique_record)
    if not isinstance(data, dict) or set(data) != {
            "name", "mode", "x", "y", "old_mode", "old_x", "old_y"}:
        raise ValueError("Invalid display change request")
    name, mode, x, y = data["name"], data["mode"], data["x"], data["y"]
    old = (data["old_mode"], data["old_x"], data["old_y"])
    lock_path = change.root / "change.lock"
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "a+b") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _write_state(change, "failed", "Another display change is already pending")
            return 1
        originals = display_layout.read_monitor_layout()
        current = _validated_output(name, mode, x, y, originals)
        if current != old:
            _write_state(change, "failed", "Display topology changed; no changes applied")
            return 1
        _write_state(change, "starting", "Applying temporary display mode")
        stopped = [False]

        def terminate(_signal, _frame):
            stopped[0] = True

        signal.signal(signal.SIGTERM, terminate)
        signal.signal(signal.SIGHUP, terminate)
        verified = False
        approved = False
        try:
            # The guard is already armed before the first potentially disruptive write.
            _run_xrandr(name, mode, x, y)
            if not _check_current(name, mode, x, y):
                raise RuntimeError("Display change could not be verified")
            verified = True
            _write_state(change, "pending", f"Confirm within {TIMEOUT_SECONDS} seconds")
            deadline = time.monotonic() + TIMEOUT_SECONDS
            while time.monotonic() < deadline and not stopped[0]:
                if _keep_requested(change):
                    _write_state(change, "kept", "New display settings confirmed")
                    approved = True
                    return 0
                time.sleep(0.12)
        except (OSError, RuntimeError, ValueError) as exc:
            # xrandr may fail *after* a partial layout change: revert regardless.
            _write_state(change, "starting", str(exc))
        finally:
            if not verified or not approved or stopped[0]:
                try:
                    _run_xrandr(name, *old)
                    if not _check_current(name, *old):
                        raise RuntimeError("X11 rollback verification failed")
                    _write_state(change, "reverted", "Original mode and position restored")
                except (OSError, RuntimeError, ValueError) as exc:
                    _write_state(change, "revert-failed", str(exc))
            _keep_path(change).unlink(missing_ok=True)
            request.unlink(missing_ok=True)
        return 1


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] != "--worker":
        return 2
    root = Path(argv[1])
    if root != runtime_root() or root.is_symlink():
        return 2
    change = DisplayChange(argv[2], root)
    try:
        return run_worker(change)
    except (OSError, ValueError, RuntimeError) as exc:
        try:
            _write_state(change, "failed", str(exc))
        except (OSError, ValueError):
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
