"""Fail-closed classification of polkit/D-Bus authorization refusals.

Only the *fact* of a refusal leaves this module. Raw tool output is inspected
in memory and is never stored, logged or placed in an exception message.
"""
from __future__ import annotations

# Lower-case fragments printed by timedatectl, nmcli (NetworkManager) and
# systemd/polkit when the caller is not authorized. Unknown text is NOT a denial.
_DENIAL_MARKERS = (
    "access denied",
    "interactive authentication required",
    "authentication is required",
    "org.freedesktop.dbus.error.accessdenied",
    "org.bluez.error.notauthorized",
    "org.freedesktop.networkmanager.permissiondenied",
    "not authorized",
    "not authorised",
    "insufficient privileges",
)

DENIED_MESSAGE = ("Permission denied: the system did not authorize this change; "
                  "nothing was changed")


class AuthorizationDenied(RuntimeError):
    """The OS refused the request for lack of authorization (no write happened)."""

    def __init__(self, message: str = DENIED_MESSAGE):
        super().__init__(message)


def is_authorization_denial(stderr: object) -> bool:
    """True only when bounded stderr text carries a recognized refusal marker."""
    if isinstance(stderr, (bytes, bytearray)):
        text = bytes(stderr[:4096]).decode("utf-8", "replace")
    elif isinstance(stderr, str):
        text = stderr[:4096]
    else:
        return False
    lowered = text.casefold()
    return any(marker in lowered for marker in _DENIAL_MARKERS)
