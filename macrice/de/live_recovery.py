"""Crash-consistent next-login recovery for supervised Wayland live switches.

The compositor menu and RiceProfile clients are disposable per-session files.
Only the next-login selection persists after a supervisor crash, so each full
session switch records a durable selection rollback intent *before* changing
those components. An interrupted switch is conservatively undone at next
Wayland login, never during XFCE startup or an isolated nested preview.
"""

from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from . import recipes

VERSION = 1
MAX_BYTES = 4096
FILE_NAME = ".live-switch.pending"
_ID = re.compile(r"[a-z][a-z0-9-]{1,31}\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_BOOT = re.compile(r"[a-f0-9-]{36}\Z")


class LiveRecoveryError(ValueError):
    """A pending live switch cannot be trusted, recorded or cleared safely."""


def _directory(*, create: bool) -> Path:
    try:
        return recipes._private_recipe_dir(create=create)
    except recipes.RecipeError as exc:
        raise LiveRecoveryError("Private RiceBowl selection directory is unsafe") from exc


def _sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _boot_id() -> str:
    return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()


def _process_start(pid: int) -> str:
    # Fields before the closing ')' may contain spaces or parentheses. Start
    # time is field 22 (zero-based index 19 after the comm field).
    record = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    return record.rsplit(") ", 1)[1].split()[19]


def _owner_running(record: dict[str, Any]) -> bool:
    try:
        current_boot = _boot_id()
    except OSError:
        return True  # Unable to prove the prior session is gone.
    if current_boot != record["boot_id"]:
        return False
    try:
        return _process_start(record["owner_pid"]) == record["owner_start"]
    except FileNotFoundError:
        return False
    except (OSError, IndexError, ValueError):
        return True  # Unreadable owner state: never steal a possible live switch.


def _validate_record(data: Any) -> dict[str, Any]:
    if (type(data) is not dict or set(data) != {"version", "target", "sha256", "before",
                                                "owner_pid", "owner_start", "boot_id"}
            or type(data["version"]) is not int or data["version"] != VERSION
            or type(data["target"]) is not str or _ID.fullmatch(data["target"]) is None
            or type(data["sha256"]) is not str or _SHA.fullmatch(data["sha256"]) is None
            or type(data["owner_pid"]) is not int or data["owner_pid"] <= 0
            or type(data["owner_start"]) is not str or not data["owner_start"].isdigit()
            or type(data["boot_id"]) is not str or _BOOT.fullmatch(data["boot_id"]) is None):
        raise LiveRecoveryError("Invalid pending Wayland switch record")
    before = data["before"]
    if before is not None:
        try:
            recipes._validate_selection_state(before)
        except recipes.RecipeError as exc:
            raise LiveRecoveryError("Invalid previous Wayland selection snapshot") from exc
    return data


def read() -> dict[str, Any] | None:
    """Read only a bounded, owner-private regular journal, never follow a link."""
    path = _directory(create=False) / FILE_NAME
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise LiveRecoveryError("Pending live switch cannot be opened safely") from exc
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_size > MAX_BYTES):
            raise LiveRecoveryError("Pending live switch is not a bounded private file")
        payload = stream.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise LiveRecoveryError("Pending live switch grew beyond the safe limit")
    try:
        data = json.loads(payload.decode("utf-8"),
                          object_pairs_hook=recipes._object_without_duplicates)
    except (ValueError, UnicodeError, TypeError, RecursionError) as exc:
        raise LiveRecoveryError("Pending live switch contains invalid JSON") from exc
    return _validate_record(data)


def begin(target: str, digest: str, before: dict[str, Any] | None) -> dict[str, Any]:
    """Persist a no-overwrite rollback intent before spawning replacement clients."""
    try:
        record = _validate_record({"version": VERSION, "target": target,
                                   "sha256": digest, "before": before,
                                   "owner_pid": os.getpid(), "owner_start": _process_start(os.getpid()),
                                   "boot_id": _boot_id()})
    except (OSError, IndexError, ValueError) as exc:
        raise LiveRecoveryError("Cannot identify the Wayland switch owner") from exc
    directory = _directory(create=True)
    try:
        if recipes._selection_snapshot() != before:
            raise LiveRecoveryError("Next-login selection changed during live preflight")
        payload = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
        recipes._write_private_new(directory / FILE_NAME, payload, suffix=".pending")
        _sync_directory(directory)
    except FileExistsError as exc:
        raise LiveRecoveryError("Previous interrupted live switch requires recovery") from exc
    except (OSError, recipes.RecipeError) as exc:
        raise LiveRecoveryError("Cannot durably save the live rollback record") from exc
    return record


def finish(record: dict[str, Any]) -> None:
    """Delete only our exact record, durably, after success or full rollback."""
    if read() != record:
        raise LiveRecoveryError("Pending live switch changed; refusing to clear it")
    directory = _directory(create=False)
    try:
        (directory / FILE_NAME).unlink()
        _sync_directory(directory)
    except OSError as exc:
        raise LiveRecoveryError("Could not durably clear pending Wayland switch") from exc


def status() -> dict[str, Any]:
    """Inspect restart safety without changing next-login selection or journal."""
    try:
        record = read()
    except LiveRecoveryError:
        return {"version": VERSION, "ok": False, "pending": None,
                "error": {"code": "unsafe_journal",
                          "message": "Pending Wayland journal is damaged or inaccessible"}}
    return {"version": VERSION, "ok": True, "pending": record is not None,
            "owner_running": _owner_running(record) if record else False,
            "automatic_recovery": "at-next-full-wayland-login" if record else "not-needed"}


def reconcile() -> dict[str, Any]:
    """Undo only our exact persisted switch; never override a concurrent stage.

    A malformed journal or failed recovery forces the next Wayland login to
    use the built-in classic recipe for that session, without deleting data.
    """
    try:
        record = read()
    except LiveRecoveryError:
        return {"status": "unsafe", "use_saved_selection": False}
    if record is None:
        return {"status": "clean", "use_saved_selection": True}
    if _owner_running(record):
        return {"status": "in_progress", "use_saved_selection": False}
    try:
        changed = recipes._restore_failed_live_selection(
            record["target"], record["sha256"], record["before"])
    except recipes.SelectionConflict:
        # A separate Creator stage won the race. Keep its choice, but only
        # after the ordinary pinned-selection verifier approves it.
        try:
            recipes.selected_recipe()
            finish(record)
        except (recipes.RecipeError, LiveRecoveryError, OSError):
            return {"status": "unsafe", "use_saved_selection": False}
        return {"status": "superseded", "use_saved_selection": True}
    except (recipes.RecipeError, OSError):
        return {"status": "unsafe", "use_saved_selection": False}
    try:
        finish(record)
    except LiveRecoveryError:
        return {"status": "unsafe", "use_saved_selection": False}
    return {"status": "restored" if changed else "unchanged", "use_saved_selection": True}
