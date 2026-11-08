"""Bounded wlroots monitor editor with an independent, timed rollback worker.

Only an already enabled output's advertised mode and scale can be changed.
Never enables/disables outputs or touches compositor/system configuration files.
"""

from __future__ import annotations

import fcntl
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

if not __package__:  # Launched as a detached file from an unpacked checkout.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from macrice import display_guard as guard


_HEADER = re.compile(r'^([^\s]{1,80}) "[^\n]{0,240}"$')
_MODE = re.compile(r'^\s+(\d{2,5})x(\d{2,5}) px, (\d+(?:\.\d+)?) Hz(?: \(([^)]+)\))?$')
_SCALE = re.compile(r'^\s*Scale: (\d+(?:\.\d+)?)$')
_POSITION = re.compile(r'^\s*Position: (-?\d+),(-?\d+)$')
_SAFE_NAME = re.compile(r"[A-Za-z0-9_.:-]{1,80}\Z")
SCALES = (1.0, 1.25, 1.5, 2.0)


@dataclass(frozen=True)
class Output:
    name: str
    current_mode: str
    modes: tuple[str, ...]
    scale: float
    position: tuple[int, int] = (0, 0)


def _in_session() -> bool:
    return (os.environ.get("RICEBOWL_DE_SHELL_CHILD") == "1"
            and os.environ.get("XDG_CURRENT_DESKTOP") == "RiceBowl:labwc:wlroots"
            and bool(os.environ.get("WAYLAND_DISPLAY")))


def parse(text: str) -> tuple[Output, ...]:
    if len(text) > 64 * 1024:
        raise ValueError("Monitor inventory is too large")
    entries: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        match = _HEADER.fullmatch(line)
        if match:
            if len(entries) >= 16 or not _SAFE_NAME.fullmatch(match[1]):
                raise ValueError("Invalid monitor identity or count")
            current = {"name": match[1], "enabled": False, "scale": None,
                       "modes": [], "current_mode": None, "position": None}
            entries.append(current)
            continue
        if current is None:
            continue
        if line.strip() == "Enabled: yes":
            current["enabled"] = True
        elif line.strip() == "Enabled: no":
            current["enabled"] = False
        elif match := _MODE.fullmatch(line):
            w, h, refresh = int(match[1]), int(match[2]), float(match[3])
            if not 320 <= w <= 16384 or not 200 <= h <= 16384 or not 20 <= refresh <= 500:
                raise ValueError("Invalid advertised monitor mode")
            mode = f"{w}x{h}@{match[3]}Hz"
            if mode in current["modes"] or len(current["modes"]) >= 96:
                raise ValueError("Duplicate or excessive display modes")
            current["modes"].append(mode)
            if "current" in (match[4] or "").split(", "):
                current["current_mode"] = mode
        elif match := _SCALE.fullmatch(line):
            current["scale"] = float(match[1])
        elif match := _POSITION.fullmatch(line):
            current["position"] = (int(match[1]), int(match[2]))
    outputs = []
    for entry in entries:
        if not entry["enabled"]:
            continue
        if (entry["current_mode"] not in entry["modes"] or entry["scale"] is None
                or not 0.5 <= entry["scale"] <= 4.0 or entry["position"] is None
                or any(abs(number) > 16384 for number in entry["position"])):
            raise ValueError("Incomplete active monitor inventory")
        outputs.append(Output(entry["name"], entry["current_mode"],
                              tuple(entry["modes"]), entry["scale"], entry["position"]))
    if not outputs or len({out.name for out in outputs}) != len(outputs):
        raise ValueError("No valid enabled monitors returned")
    return tuple(outputs)


def _run(args: tuple[str, ...]) -> str:
    binary = shutil.which("wlr-randr")
    if not binary:
        raise RuntimeError("wlr-randr is not installed")
    try:
        completed = subprocess.run((binary, *args), stdin=subprocess.DEVNULL,
                                   capture_output=True, timeout=6, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("wlroots display service unavailable or timed out") from exc
    if completed.returncode or len(completed.stdout) > 64 * 1024:
        raise RuntimeError("wlroots rejected the monitor operation")
    try:
        return completed.stdout.decode("utf-8")
    except UnicodeError as exc:
        raise RuntimeError("Invalid monitor inventory encoding") from exc


def inventory() -> tuple[Output, ...]:
    if not _in_session():
        raise RuntimeError("Display editor is restricted to an active RiceBowl labwc session")
    return parse(_run(()))


def _validated(name: str, mode: str, scale: float, outputs: tuple[Output, ...]) -> Output:
    if (type(name) is not str or not _SAFE_NAME.fullmatch(name)
            or type(mode) is not str or type(scale) not in (int, float)
            or not 0.5 <= scale <= 4):
        raise ValueError("Invalid monitor setting")
    output = next((item for item in outputs if item.name == name), None)
    if output is None or mode not in output.modes:
        raise ValueError("Output or mode is no longer advertised")
    if scale not in SCALES and abs(scale - output.scale) > 0.005:
        raise ValueError("Select a supported scale, or retain the current scale")
    return output


def runtime_root() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime or not Path(runtime).is_absolute():
        raise RuntimeError("Private XDG_RUNTIME_DIR is required for safe display changes")
    parent = Path(runtime)
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("Unsafe session runtime directory")
    root = parent / "ricebowl-wayland-display-guard"
    root.mkdir(mode=0o700, exist_ok=True)
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("Unsafe Wayland display guard directory")
    return root


def begin_change(name: str, mode: str, scale: float, *,
                 position: tuple[int, int] | None = None) -> guard.DisplayChange:
    import secrets

    original = _validated(name, mode, scale, inventory())
    if position is not None and (type(position) is not tuple or len(position) != 2
                                 or any(type(value) is not int or abs(value) > 16384
                                        for value in position)):
        raise ValueError("Invalid selected monitor position")
    target_position = original.position if position is None else position
    if ((mode, float(scale), target_position) ==
            (original.current_mode, original.scale, original.position)):
        raise ValueError("Monitor settings are already selected")
    change = guard.DisplayChange(secrets.token_hex(16), runtime_root())
    request = {
        "name": name, "mode": mode, "scale": scale,
        "old_mode": original.current_mode, "old_scale": original.scale,
    }
    if position is not None:
        request.update(x=position[0], y=position[1],
                       old_x=original.position[0], old_y=original.position[1])
    guard._write_new(guard._request_path(change), request)
    try:
        subprocess.Popen((sys.executable, str(Path(__file__).resolve()), "--worker",
                          str(change.root), change.token), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True)
    except OSError as exc:
        guard._request_path(change).unlink(missing_ok=True)
        raise RuntimeError("Could not start detached Wayland display rollback") from exc
    return change


def _set(name: str, mode: str, scale: float, position: tuple[int, int] | None = None) -> None:
    args = ("--output", name, "--mode", mode, "--scale", str(scale))
    if position is not None:
        args += ("--pos", f"{position[0]},{position[1]}")
    _run(args)


def _matches(name: str, mode: str, scale: float,
             position: tuple[int, int] | None = None) -> bool:
    return any(out.name == name and out.current_mode == mode
               and abs(out.scale - scale) < 0.005
               and (position is None or out.position == position) for out in inventory())


def run_worker(change: guard.DisplayChange) -> int:
    import json

    request = guard._request_path(change)
    if request.is_symlink() or request.stat().st_size > 4096:
        raise ValueError("Invalid monitor change request")
    data = json.loads(request.read_text(encoding="utf-8"))
    base = {"name", "mode", "scale", "old_mode", "old_scale"}
    has_position = set(data) == base | {"x", "y", "old_x", "old_y"} if isinstance(data, dict) else False
    if not isinstance(data, dict) or (set(data) != base and not has_position):
        raise ValueError("Malformed monitor change request")
    name, mode, scale = data["name"], data["mode"], data["scale"]
    old_mode, old_scale = data["old_mode"], data["old_scale"]
    position = (data["x"], data["y"]) if has_position else None
    old_position = (data["old_x"], data["old_y"]) if has_position else None
    if has_position and (any(type(value) is not int or abs(value) > 16384
                             for value in (*position, *old_position))):
        raise ValueError("Invalid monitor position request")
    lock_fd = os.open(change.root / "change.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "rb") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            guard._write_state(change, "failed", "Another monitor change is pending")
            return 1
        current = _validated(name, mode, scale, inventory())
        if (current.current_mode != old_mode or current.scale != old_scale
                or (has_position and current.position != old_position)):
            guard._write_state(change, "failed", "Monitor changed; no change applied")
            return 1
        if not _SAFE_NAME.fullmatch(name):
            raise ValueError("Invalid monitor name")
        _validated(name, old_mode, old_scale, inventory())
        stopped = [False]

        def stop(_sig, _frame):
            stopped[0] = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGHUP, stop)
        confirmed = False
        try:
            guard._write_state(change, "starting", "Trying new monitor settings")
            _set(name, mode, scale, position) if has_position else _set(name, mode, scale)
            verified = (_matches(name, mode, scale, position) if has_position
                        else _matches(name, mode, scale))
            if not verified:
                raise RuntimeError("New monitor settings could not be verified")
            guard._write_state(change, "pending", "Confirm within 18 seconds or rollback")
            deadline = time.monotonic() + guard.TIMEOUT_SECONDS
            while time.monotonic() < deadline and not stopped[0]:
                if guard._keep_path(change).is_file():
                    guard._write_state(change, "kept", "Monitor settings confirmed for this session")
                    confirmed = True
                    return 0
                time.sleep(0.12)
        except (RuntimeError, ValueError, OSError) as exc:
            guard._write_state(change, "starting", str(exc))
        finally:
            if not confirmed:
                try:
                    (_set(name, old_mode, old_scale, old_position) if has_position
                     else _set(name, old_mode, old_scale))
                    restored = (_matches(name, old_mode, old_scale, old_position)
                                if has_position else _matches(name, old_mode, old_scale))
                    if not restored:
                        raise RuntimeError("Display rollback could not be verified")
                    guard._write_state(change, "reverted", "Original monitor settings restored")
                except (RuntimeError, ValueError, OSError) as exc:
                    guard._write_state(change, "revert-failed", str(exc))
            guard._keep_path(change).unlink(missing_ok=True)
            request.unlink(missing_ok=True)
    return 1


def main(args: list[str]) -> int:
    if len(args) != 3 or args[0] != "--worker" or not _in_session():
        return 2
    try:
        root = runtime_root()
        if root != Path(args[1]):
            return 2
        return run_worker(guard.DisplayChange(args[2], root))
    except (OSError, RuntimeError, ValueError) as exc:
        try:
            guard._write_state(guard.DisplayChange(args[2], root), "failed", str(exc))
        except (OSError, ValueError, UnboundLocalError):
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
