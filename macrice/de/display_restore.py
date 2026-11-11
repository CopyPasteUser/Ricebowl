"""All-output RiceSpice preset trial with an independent, all-or-nothing rollback.

A saved layout is never trusted without comparing it with the live enabled
outputs and their advertised modes. The detached guard rolls *every* touched
output back unless the user explicitly confirms within eighteen seconds.
"""

from __future__ import annotations

import fcntl
import json
import os
import secrets
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

if not __package__:  # Independent worker launched from an installed checkout.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from macrice import display_guard as guard
from macrice.de import display_presets, wayland_displays


def _by_name(entries: list[dict]) -> dict[str, dict]:
    return {entry["name"]: entry for entry in entries}


def plan(saved: list[dict], outputs: tuple[wayland_displays.Output, ...]
         ) -> tuple[list[dict], list[dict]]:
    """Validate the complete enabled topology before returning a restore plan."""
    target = display_presets._validated(saved)
    baseline = display_presets.from_outputs(outputs)
    if (not target or len(target) != len(baseline)
            or _by_name(target).keys() != _by_name(baseline).keys()):
        raise ValueError("Saved layout does not match the connected enabled monitors")
    current = {output.name: output for output in outputs}
    for entry in target:
        actual = current[entry["name"]]
        # Reuse the same advertised-mode / supported-scale checks as a single
        # guarded output trial. Never enable a disconnected monitor.
        wayland_displays._validated(entry["name"], entry["mode"], entry["scale"], outputs)
        if entry["mode"] not in actual.modes:
            raise ValueError("Saved monitor mode is no longer available")
    if _by_name(target) == _by_name(baseline):
        raise ValueError("Saved monitor layout is already active")
    return baseline, target


def begin(saved: list[dict]) -> guard.DisplayChange:
    """Start one bounded trial of the full reviewed layout; never commit automatically."""
    if not wayland_displays._in_session():
        raise RuntimeError("Monitor restore is restricted to the active RiceBowl session")
    checked = display_presets._validated(saved)
    if checked != display_presets.load():
        raise ValueError("Saved monitor layout changed; refresh before restoring")
    baseline, target = plan(checked, wayland_displays.inventory())
    change = guard.DisplayChange(secrets.token_hex(16), wayland_displays.runtime_root())
    guard._write_new(guard._request_path(change), {
        "version": 1, "baseline": baseline, "target": target,
    })
    try:
        subprocess.Popen((sys.executable, str(Path(__file__).resolve()), "--worker",
                          str(change.root), change.token), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True)
    except OSError as exc:
        guard._request_path(change).unlink(missing_ok=True)
        raise RuntimeError("Could not start the independent monitor restore guard") from exc
    return change


def _request(change: guard.DisplayChange) -> tuple[list[dict], list[dict]]:
    path = guard._request_path(change)
    if path.is_symlink() or path.stat().st_size > 4096:
        raise ValueError("Unsafe monitor restore request")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Invalid monitor restore request") from exc
    if (type(record) is not dict or set(record) != {"version", "baseline", "target"}
            or record["version"] != 1 or type(record["version"]) is not int):
        raise ValueError("Unsupported monitor restore request")
    return (display_presets._validated(record["baseline"]),
            display_presets._validated(record["target"]))


def _is_layout(entries: list[dict], outputs: tuple[wayland_displays.Output, ...]) -> bool:
    return _by_name(display_presets.from_outputs(outputs)) == _by_name(entries)


def run_worker(change: guard.DisplayChange) -> int:
    baseline, target = _request(change)
    root = change.root
    lock_fd = os.open(root / "change.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "rb") as lock:
        info = os.fstat(lock.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077):
            raise ValueError("Unsafe display guard lock")
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            guard._write_state(change, "failed", "Another monitor change is pending")
            return 1

        try:
            original = wayland_displays.inventory()
            if not _is_layout(baseline, original):
                raise ValueError("Monitor topology changed; nothing applied")
            plan(target, original)
        except (OSError, RuntimeError, ValueError) as exc:
            guard._write_state(change, "failed", str(exc))
            guard._request_path(change).unlink(missing_ok=True)
            return 1
        old_by_name, target_by_name = _by_name(baseline), _by_name(target)
        touched: list[str] = []
        stopped = [False]

        def stop(_signal, _frame):
            stopped[0] = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGHUP, stop)
        kept = False
        try:
            guard._write_state(change, "starting", "Trying all saved monitor settings")
            for old in baseline:
                name = old["name"]
                wanted = target_by_name[name]
                if old == wanted:
                    continue
                if stopped[0]:
                    raise RuntimeError("Monitor restore was interrupted")
                touched.append(name)  # A failed write may already have changed the output.
                wayland_displays._set(name, wanted["mode"], wanted["scale"],
                                      (wanted["x"], wanted["y"]))
                if not wayland_displays._matches(
                        name, wanted["mode"], wanted["scale"], (wanted["x"], wanted["y"])):
                    raise RuntimeError("Monitor restore could not be verified")
            if not _is_layout(target, wayland_displays.inventory()):
                raise RuntimeError("Full monitor layout does not match the preset")
            guard._write_state(change, "pending", "Confirm the entire layout within 18 seconds")
            deadline = time.monotonic() + guard.TIMEOUT_SECONDS
            while time.monotonic() < deadline and not stopped[0]:
                if guard._keep_path(change).is_file():
                    guard._write_state(change, "kept", "Full monitor layout confirmed")
                    kept = True
                    if os.environ.get("RICEBOWL_DE_LIVE") == "1":
                        try:
                            from macrice.de import live
                            if not live.request("refresh-outputs").get("ok"):
                                raise live.LiveError("Output refresh rejected")
                        except (OSError, ValueError, live.LiveError):
                            guard._write_state(change, "kept",
                                               "Layout kept; restart RiceBowl to refresh the panel")
                    return 0
                time.sleep(0.12)
        except (OSError, RuntimeError, ValueError) as exc:
            guard._write_state(change, "starting", str(exc))
        finally:
            if not kept:
                errors = []
                for name in reversed(touched):
                    old = old_by_name[name]
                    try:
                        wayland_displays._set(name, old["mode"], old["scale"],
                                              (old["x"], old["y"]))
                    except (OSError, RuntimeError, ValueError) as exc:
                        errors.append(f"{name}: {exc}")
                try:
                    if not _is_layout(baseline, wayland_displays.inventory()):
                        errors.append("Original full monitor layout could not be verified")
                except (OSError, RuntimeError, ValueError) as exc:
                    errors.append(f"Cannot verify full rollback: {exc}")
                guard._write_state(change, "revert-failed" if errors else "reverted",
                                   "; ".join(errors) if errors else "Full original layout restored")
            guard._keep_path(change).unlink(missing_ok=True)
            guard._request_path(change).unlink(missing_ok=True)
    return 1


def main(args: list[str]) -> int:
    if len(args) != 3 or args[0] != "--worker" or not wayland_displays._in_session():
        return 2
    try:
        root = wayland_displays.runtime_root()
        if root != Path(args[1]):
            return 2
        return run_worker(guard.DisplayChange(args[2], root))
    except (OSError, ValueError, RuntimeError) as exc:
        try:
            guard._write_state(guard.DisplayChange(args[2], root), "failed", str(exc))
        except (OSError, ValueError, UnboundLocalError):
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
