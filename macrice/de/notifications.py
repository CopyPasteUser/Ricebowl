"""On-demand RicePop bridge to the sole existing Wayland notification host.

Mako owns org.freedesktop.Notifications. Only an explicit, freshly verified
active ID and advertised action key may invoke an application's own action.
No second notification owner, arbitrary command, persistence or poller.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any


class NotificationBridgeError(ValueError):
    def __init__(self, message: str, code: str = "notifications_unavailable") -> None:
        super().__init__(message)
        self.code = code


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


def inspect() -> dict[str, Any]:
    """Query the active notification owner only on explicit CLI invocation."""
    command = shutil.which("makoctl")
    if command is None:
        raise NotificationBridgeError("makoctl is not installed")
    snapshots = {}
    truncated = False
    for source, action in (("active", "list"), ("history", "history")):
        try:
            process = subprocess.run([command, action, "-j"], capture_output=True,
                                     timeout=3, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise NotificationBridgeError("Wayland notification host is unreachable") from exc
        if process.returncode:
            raise NotificationBridgeError("Wayland notification host rejected a read-only query")
        snapshots[source], limited = _records(process.stdout,
                                             include_actions=source == "active")
        truncated |= limited
    return {"ok": True, "backend": "mako", "active": snapshots["active"],
            "history": snapshots["history"], "truncated": truncated,
            "read_only": True, "actions_replayed": False,
            "mutates_active_desktop": False, "source_contains_private_messages": True}


def _fresh_active(command: str, *, include_actions: bool = False) -> list[dict[str, Any]]:
    """Revalidate the exact bounded current inventory before any mutation."""
    try:
        snapshot = subprocess.run([command, "list", "-j"], capture_output=True,
                                  timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NotificationBridgeError("Notification host is unreachable") from exc
    if snapshot.returncode:
        raise NotificationBridgeError("Notification host rejected the active list")
    active, truncated = _records(snapshot.stdout, include_actions=include_actions)
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
    active = _fresh_active(command)
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
    active = _fresh_active(command, include_actions=True)
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
            attempted_invoke: bool = False) -> dict[str, Any]:
    return {"ok": False, "backend": "mako", "active": [], "history": [],
            "read_only": not (attempted_dismiss or attempted_invoke),
            "dismissed": False, "invoked": False,
            "error": {"code": error.code, "message": str(error)}}
