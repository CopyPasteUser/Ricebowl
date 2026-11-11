"""On-demand RicePop bridge to the sole existing Wayland notification host.

Mako owns org.freedesktop.Notifications. Only an explicit, freshly verified
active ID and advertised action key may invoke an application's own action.
No second notification owner, arbitrary command, persistence or poller.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any


class NotificationBridgeError(ValueError):
    def __init__(self, message: str, code: str = "notifications_unavailable") -> None:
        super().__init__(message)
        self.code = code


_DND_MODE = "ricebowl-do-not-disturb"
_NOTIFICATION_BUS = "org.freedesktop.Notifications"
_MAKO_PATH = "/fr/emersion/Mako"
_MAKO_INTERFACE = "fr.emersion.Mako"


def _expected_mako_config(candidate: bytes) -> bytes:
    """Prove Mako's actual config even for apps launched outside shell env.

    labwc-launched RiceSpice may not inherit the panel supervisor's dynamic
    config variable, so the actual /proc argv must also be independently safe.
    """
    shipped = os.fsencode(Path(__file__).parent / "resources" / "mako.conf")
    configured = os.environ.get("RICEBOWL_DE_MAKO_CONFIG")
    if configured is not None and os.fsencode(configured) != candidate:
        raise ValueError("RicePop host configuration changed")
    if candidate == shipped:
        return shipped
    path = Path(os.fsdecode(candidate))
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if (not path.is_absolute() or not runtime or not Path(runtime).is_absolute()
            or path.name != "mako.conf" or not path.parent.name.startswith("ricebowl-pop-")
            or path.parent.parent != Path(runtime) or path.is_symlink()
            or path.parent.is_symlink()):
        raise ValueError("Untrusted RicePop session configuration")
    folder, file = path.parent.stat(), path.stat()
    if (folder.st_uid != os.getuid() or stat.S_IMODE(folder.st_mode) != 0o700
            or file.st_uid != os.getuid() or stat.S_IMODE(file.st_mode) != 0o600
            or not stat.S_ISREG(file.st_mode) or file.st_size > 2048):
        raise ValueError("Unsafe RicePop session configuration")
    return os.fsencode(path)


def _owned_mako() -> tuple[str, int]:
    """Prove Mako's *D-Bus owner*, not just a Wayland environment marker.

    An existing XFCE/nested notification host must never receive a global
    makoctl mode mutation. Missing busctl or an opaque /proc fails closed.
    """
    if (os.environ.get("XDG_SESSION_DESKTOP") != "ricebowl"
            or os.environ.get("RICEBOWL_DE_NESTED") != "0"
            or not os.environ.get("WAYLAND_DISPLAY")):
        raise NotificationBridgeError("Do Not Disturb requires a full RiceBowl Wayland session",
                                      "dnd_session_unavailable")
    command = shutil.which("makoctl")
    busctl = shutil.which("busctl")
    if not command or not busctl:
        raise NotificationBridgeError("Mako controls or D-Bus ownership tools are missing")
    try:
        owner = subprocess.run([busctl, "--user", "status", _NOTIFICATION_BUS],
                               capture_output=True, timeout=3, check=False)
        if owner.returncode or len(owner.stdout) > 16 * 1024:
            raise ValueError("Unverified D-Bus owner")
        match = re.search(rb"(?m)^\s*PID=(\d+)\s*$", owner.stdout)
        if not match or not 1 <= int(match.group(1)) <= 2**31 - 1:
            raise ValueError("No notification owner PID")
        pid = int(match.group(1))
        with open(f"/proc/{pid}/cmdline", "rb") as stream:
            arguments = stream.read(4097)
        if len(arguments) > 4096 or not arguments.endswith(b"\0"):
            raise ValueError("Invalid notification owner command")
        argv = arguments.rstrip(b"\0").split(b"\0")
        expected = _expected_mako_config(argv[2] if len(argv) == 3 else b"")
        if (not argv or Path(os.fsdecode(argv[0])).name != "mako"
                or len(argv) != 3 or argv[1] != b"--config" or argv[2] != expected):
            raise ValueError("Another application owns notifications")
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise NotificationBridgeError("RiceBowl does not own the active Mako notification host",
                                      "dnd_host_unverified") from exc
    return command, pid


def _modes(command: str) -> list[str]:
    try:
        snapshot = subprocess.run([command, "mode"], capture_output=True,
                                  timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NotificationBridgeError("Mako modes are unreachable") from exc
    if snapshot.returncode or len(snapshot.stdout) > 4096:
        raise NotificationBridgeError("Mako mode inventory is unavailable")
    try:
        modes = snapshot.stdout.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise NotificationBridgeError("Invalid Mako mode inventory") from exc
    if len(modes) > 32 or len(set(modes)) != len(modes) or any(
            not value or len(value) > 80 or not value.isprintable() for value in modes):
        raise NotificationBridgeError("Ambiguous Mako mode inventory")
    return modes


def dnd_status() -> dict[str, Any]:
    """Read the verified owner; no writes and no notification text disclosed."""
    command, pid = _owned_mako()
    enabled = _DND_MODE in _modes(command)
    if _owned_mako() != (command, pid):
        raise NotificationBridgeError("Notification owner changed", "dnd_host_unverified")
    return {"ok": True, "backend": "mako", "do_not_disturb": enabled,
            "read_only": True, "mutates_active_desktop": False}


def set_dnd(enabled: bool, *, expected: bool | None = None) -> dict[str, Any]:
    """Compare-and-set a single Mako mode and verify the resulting owner state."""
    if type(enabled) is not bool or (expected is not None and type(expected) is not bool):
        raise NotificationBridgeError("Do Not Disturb expects explicit boolean states",
                                      "invalid_dnd_state")
    command, pid = _owned_mako()
    previous = _DND_MODE in _modes(command)
    if expected is not None and previous != expected:
        raise NotificationBridgeError("Do Not Disturb changed; refresh before retrying",
                                      "stale_dnd_state")
    if previous != enabled:
        # Check D-Bus ownership once more just before mutation (e.g. a daemon
        # may have exited while RiceSpice's asynchronous page was open).
        if _owned_mako() != (command, pid):
            raise NotificationBridgeError("Notification owner changed", "dnd_host_unverified")
        try:
            result = subprocess.run([command, "mode", "-a" if enabled else "-r", _DND_MODE],
                                    capture_output=True, timeout=3, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise NotificationBridgeError("Do Not Disturb change could not be confirmed") from exc
        if result.returncode:
            raise NotificationBridgeError("Notification host rejected Do Not Disturb")
    if _owned_mako() != (command, pid):
        raise NotificationBridgeError("Notification owner changed", "dnd_host_unverified")
    if (_DND_MODE in _modes(command)) != enabled:
        raise NotificationBridgeError("Do Not Disturb verification failed", "dnd_verify_failed")
    return {"ok": True, "backend": "mako", "do_not_disturb": enabled,
            "changed": previous != enabled, "read_only": False,
            "mutates_active_desktop": previous != enabled}


def _action_key(key: object) -> bool:
    return type(key) is str and 0 < len(key) <= 80 and key.isprintable()


def _records(raw: bytes, *, include_actions: bool = False) -> tuple[list[dict[str, Any]], bool]:
    if len(raw) > 128 * 1024:
        raise NotificationBridgeError("Notification host response is oversized",
                                      "invalid_notification_response")
    try:
        records = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise NotificationBridgeError("Notification host returned invalid JSON",
                                      "invalid_notification_response") from exc
    return _validate_records(records, include_actions=include_actions)


def _validate_records(records: object, *, include_actions: bool = False
                      ) -> tuple[list[dict[str, Any]], bool]:
    if type(records) is not list:
        raise NotificationBridgeError("Notification list must be an array",
                                      "invalid_notification_response")
    result = []
    for record in records[:64]:
        if type(record) is not dict or type(record.get("id")) is not int or not 0 < record["id"] <= 2**32 - 1:
            raise NotificationBridgeError("Notification entry is invalid",
                                          "invalid_notification_response")
        for key in ("summary", "body", "app_name", "urgency"):
            if record.get(key) is not None and type(record[key]) is not str:
                raise NotificationBridgeError("Notification text is invalid",
                                              "invalid_notification_response")
        entry = {
            "id": record["id"],
            "summary": (record.get("summary") or "")[:160],
            "body": (record.get("body") or "")[:2048],
            "app_name": (record.get("app_name") or "")[:80],
            "urgency": (record.get("urgency") or "unknown")[:32],
        }
        if include_actions:
            raw_actions = record.get("actions", {})
            if type(raw_actions) is not dict or len(raw_actions) > 8:
                raise NotificationBridgeError("Notification actions are invalid",
                                              "invalid_notification_response")
            actions = []
            for key, label in raw_actions.items():
                if not _action_key(key) or not _action_key(label) or len(label) > 80:
                    raise NotificationBridgeError("Notification action is invalid",
                                                  "invalid_notification_response")
                actions.append({"key": key, "label": label})
            entry["actions"] = actions
        result.append(entry)
    return result, len(records) > 64


def _busctl_records(raw: bytes, *, include_actions: bool = False
                    ) -> tuple[list[dict[str, Any]], bool]:
    """Decode Mako's stable D-Bus aa{sv} shape across 1.8–1.11.

    Ubuntu 24.04 ships Mako 1.8, whose ``makoctl list`` emits typed busctl
    JSON *without* a ``-j`` option. Mako 1.10 switched to text and 1.11
    gained its own JSON format. Read Mako's actual D-Bus API instead of
    guessing which incompatible makoctl representation is installed.
    """
    if len(raw) > 128 * 1024:
        raise NotificationBridgeError("Notification host response is oversized",
                                      "invalid_notification_response")
    try:
        reply = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise NotificationBridgeError("Notification host returned invalid JSON",
                                      "invalid_notification_response") from exc
    if (type(reply) is not dict or reply.get("type") != "aa{sv}"
            or type(reply.get("data")) is not list or len(reply["data"]) != 1
            or type(reply["data"][0]) is not list):
        raise NotificationBridgeError("Unexpected Mako D-Bus response",
                                      "invalid_notification_response")

    fields = {"id": "u", "summary": "s", "body": "s", "app-name": "s",
              "urgency": "y", "actions": "a{ss}"}
    result = []
    for entry in reply["data"][0][:64]:
        if type(entry) is not dict:
            raise NotificationBridgeError("Invalid Mako notification entry",
                                          "invalid_notification_response")
        normalized = {}
        for key, expected_type in fields.items():
            if key not in entry:
                continue
            typed = entry[key]
            if (type(typed) is not dict or typed.get("type") != expected_type
                    or "data" not in typed):
                raise NotificationBridgeError("Invalid Mako notification property",
                                              "invalid_notification_response")
            value = typed["data"]
            if key == "urgency":
                if type(value) is not int or value not in (0, 1, 2):
                    raise NotificationBridgeError("Invalid Mako notification urgency",
                                                  "invalid_notification_response")
                value = ("low", "normal", "critical")[value]
            elif key == "id":
                if type(value) is not int:
                    raise NotificationBridgeError("Invalid Mako notification ID",
                                                  "invalid_notification_response")
            elif key == "actions":
                if type(value) is not dict:
                    raise NotificationBridgeError("Invalid Mako notification actions",
                                                  "invalid_notification_response")
            elif type(value) is not str:
                raise NotificationBridgeError("Invalid Mako notification text",
                                              "invalid_notification_response")
            normalized["app_name" if key == "app-name" else key] = value
        result.append(normalized)
    validated, _ = _validate_records(result, include_actions=include_actions)
    return validated, len(reply["data"][0]) > 64


def _read_mako(action: str, *, include_actions: bool = False
               ) -> tuple[list[dict[str, Any]], bool]:
    """Read only Mako's private ListNotifications/ListHistory D-Bus API."""
    if action not in ("ListNotifications", "ListHistory"):
        raise ValueError("Unsupported Mako read operation")
    busctl = shutil.which("busctl")
    if busctl is None:
        raise NotificationBridgeError("D-Bus notification inventory tools are missing")
    try:
        process = subprocess.run(
            [busctl, "--user", "--json=short", "call", _NOTIFICATION_BUS,
             _MAKO_PATH, _MAKO_INTERFACE, action],
            capture_output=True, timeout=3, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NotificationBridgeError("Wayland notification host is unreachable") from exc
    if process.returncode:
        raise NotificationBridgeError("Mako notification inventory is unavailable")
    return _busctl_records(process.stdout, include_actions=include_actions)


def inspect() -> dict[str, Any]:
    """Query the active notification owner only on explicit CLI invocation."""
    snapshots = {}
    truncated = False
    for source, action in (("active", "ListNotifications"), ("history", "ListHistory")):
        snapshots[source], limited = _read_mako(action, include_actions=source == "active")
        truncated |= limited
    return {"ok": True, "backend": "mako", "active": snapshots["active"],
            "history": snapshots["history"], "truncated": truncated,
            "read_only": True, "actions_replayed": False,
            "mutates_active_desktop": False, "source_contains_private_messages": True}


def _fresh_active(*, include_actions: bool = False) -> list[dict[str, Any]]:
    """Revalidate the exact bounded current inventory before any mutation."""
    active, truncated = _read_mako("ListNotifications", include_actions=include_actions)
    if truncated or len({record["id"] for record in active}) != len(active):
        raise NotificationBridgeError("Active notification inventory is ambiguous",
                                      "ambiguous_notification_id")
    return active


def dismiss(notification_id: int) -> dict[str, Any]:
    """Close one still-active ID. Never dismiss all or invoke its actions."""
    if type(notification_id) is not int or not 0 < notification_id <= 2**32 - 1:
        raise NotificationBridgeError("Notification ID must be a nonzero uint32",
                                      "invalid_notification_id")
    command = shutil.which("makoctl")
    if command is None:
        raise NotificationBridgeError("makoctl is not installed")
    active = _fresh_active()
    if notification_id not in {record["id"] for record in active}:
        raise NotificationBridgeError("Notification is no longer active",
                                      "notification_not_found")
    try:
        outcome = subprocess.run([command, "dismiss", "-n", str(notification_id)],
                                 capture_output=True, timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NotificationBridgeError("Notification dismissal could not be completed") from exc
    if outcome.returncode:
        raise NotificationBridgeError("Notification host rejected dismissal",
                                      "dismiss_failed")
    return {"ok": True, "backend": "mako", "dismissed": True,
            "notification_id": notification_id, "mutates_active_desktop": True,
            "actions_replayed": False, "all_notifications_affected": False}


def invoke(notification_id: int, action_key: str) -> dict[str, Any]:
    """Invoke a chosen, currently advertised Mako action, never history/default by accident.

    The action key comes from the current host inventory, not from a recipe or
    executable command. The host may still expire the entry between recheck
    and execution; a failed invocation is reported rather than retried.
    """
    if type(notification_id) is not int or not 0 < notification_id <= 2**32 - 1:
        raise NotificationBridgeError("Notification ID must be a nonzero uint32",
                                      "invalid_notification_id")
    if not _action_key(action_key):
        raise NotificationBridgeError("Action key is invalid", "invalid_action_key")
    command = shutil.which("makoctl")
    if command is None:
        raise NotificationBridgeError("makoctl is not installed")
    active = _fresh_active(include_actions=True)
    matching = next((item for item in active if item["id"] == notification_id), None)
    if matching is None:
        raise NotificationBridgeError("Notification is no longer active", "notification_not_found")
    if action_key not in {action["key"] for action in matching["actions"]}:
        raise NotificationBridgeError("Notification action is no longer available",
                                      "notification_action_not_found")
    try:
        outcome = subprocess.run([command, "invoke", "-n", str(notification_id), "--", action_key],
                                 capture_output=True, timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NotificationBridgeError("Notification action could not be completed") from exc
    if outcome.returncode:
        raise NotificationBridgeError("Notification host rejected the action", "invoke_failed")
    return {"ok": True, "backend": "mako", "invoked": True,
            "notification_id": notification_id, "action_key": action_key,
            "mutates_active_desktop": True, "all_notifications_affected": False}


def invalid(error: NotificationBridgeError, *, attempted_dismiss: bool = False,
            attempted_invoke: bool = False, attempted_dnd: bool = False) -> dict[str, Any]:
    return {"ok": False, "backend": "mako", "active": [], "history": [],
            "read_only": not (attempted_dismiss or attempted_invoke or attempted_dnd),
            "dismissed": False, "invoked": False, "do_not_disturb": None,
            "error": {"code": error.code, "message": str(error)}}
