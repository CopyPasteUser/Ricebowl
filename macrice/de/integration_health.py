"""Read-only, on-demand D-Bus owner inventory for an opt-in full RiceBowl login.

NameHasOwner is a method on the D-Bus daemon. It does not activate the
requested service, connect to its private API or alter Linux settings.
A name without a current owner may still be installed and activatable.
This never runs as a resident session monitor.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping

from . import acceptance
from .session import DESKTOP_NAME

# Strict allowlist. In particular, do NOT call StartServiceByName, systemctl,
# loginctl actions or any provider-specific setter from a health command.
_SERVICES: tuple[tuple[str, str, str], ...] = (
    ("xdg_desktop_portal", "session", "org.freedesktop.portal.Desktop"),
    ("notifications", "session", "org.freedesktop.Notifications"),
    ("logind", "system", "org.freedesktop.login1"),
    ("polkit_authority", "system", "org.freedesktop.PolicyKit1"),
    ("network_manager", "system", "org.freedesktop.NetworkManager"),
    ("bluez", "system", "org.bluez"),
)
_MAX_OUTPUT = 4096
_REPLY_TIMEOUT_MS = 1000
_PROCESS_TIMEOUT_SECONDS = 2.0


def _owner(name: str, bus: str, *, binary: str,
           env: Mapping[str, str],
           run: Callable[..., subprocess.CompletedProcess[str]]) -> str:
    """Observe one allowlisted bus name without activating the target."""
    if (bus not in ("session", "system")
            or (bus, name) not in {(kind, target) for _, kind, target in _SERVICES}):
        raise ValueError("Unknown integration service")
    try:
        response = run(
            [binary, "--" + bus, "--type=method_call",
             "--print-reply=literal", f"--reply-timeout={_REPLY_TIMEOUT_MS}",
             "--dest=org.freedesktop.DBus", "/org/freedesktop/DBus",
             "org.freedesktop.DBus.NameHasOwner", "string:" + name],
            env=dict(env), capture_output=True, text=True,
            timeout=_PROCESS_TIMEOUT_SECONDS, check=False,
            stdin=subprocess.DEVNULL,
        )
        if response.returncode:
            return "unreachable"
        output = response.stdout
        if not isinstance(output, str) or len(output) > _MAX_OUTPUT:
            return "invalid-response"
        flags = re.findall(r"(?m)^\s*boolean\s+(true|false)\s*$", output)
        if len(flags) != 1:
            return "invalid-response"
        return "owned" if flags[0] == "true" else "not-owned"
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return "unreachable"


def inspect(*, environment: Mapping[str, str] | None = None,
            which: Callable[[str], str | None] = shutil.which,
            run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
            socket_probe: Callable[[Mapping[str, str]], str] = acceptance._socket_state
            ) -> dict[str, object]:
    """Probe only a live *full* RiceBowl session, not XFCE or nested previews."""
    env = os.environ if environment is None else environment
    marked = (env.get("XDG_SESSION_TYPE", "").lower() == "wayland"
              and env.get("XDG_CURRENT_DESKTOP") == DESKTOP_NAME
              and env.get("RICEBOWL_DE_SHELL_CHILD") == "1"
              and env.get("RICEBOWL_DE_NESTED") == "0")
    socket = socket_probe(env) if marked else "not-checked"
    if socket not in ("present", "missing", "invalid", "not-checked"):
        socket = "invalid"
    eligible = marked and socket == "present"
    binary = which("dbus-send") if eligible else None
    declared_bus = bool(env.get("DBUS_SESSION_BUS_ADDRESS"))
    services: dict[str, str] = {}
    for key, bus, name in _SERVICES:
        if not eligible:
            result = "not-run"
        elif not binary:
            result = "tool-missing"
        elif bus == "session" and not declared_bus:
            result = "not-declared"
        else:
            result = _owner(name, bus, binary=binary, env=env, run=run)
        services[key] = result
    return {
        "schema_version": 1,
        "read_only": True,
        "hardware_accepted": False,
        "session": {
            "full_ricebowl": eligible,
            "socket": socket,
            "nested": env.get("RICEBOWL_DE_NESTED") == "1",
            "session_bus_declared": declared_bus,
        },
        "services": services,
        "limitations": [
            "D-Bus name ownership is not service readiness, permission or successful UI interaction",
            "Not-owned can mean an installed but not yet activated service",
            "PipeWire, WirePlumber, GPU portals and physical lock/suspend are not verified",
            "No services are started, reconfigured or restarted",
        ],
    }
