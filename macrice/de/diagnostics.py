"""Side-effect-free preflight for the opt-in RiceBowl labwc session.

The presence of a compositor alone never means the complete Wayland desktop
is ready. This module intentionally does not inspect private user files or
invoke external commands.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass

from .session import REQUIRED_TOOLS


@dataclass(frozen=True)
class Check:
    key: str
    status: str
    label: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class Report:
    session_type: str
    checks: tuple[Check, ...]
    nested_prerequisites_ready: bool = False
    login_prerequisites_ready: bool = False
    native_login_prerequisites_ready: bool = False
    standalone_de_ready: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "session_type": self.session_type,
            "nested_prerequisites_ready": self.nested_prerequisites_ready,
            "login_prerequisites_ready": self.login_prerequisites_ready,
            "native_login_prerequisites_ready": self.native_login_prerequisites_ready,
            "standalone_de_ready": self.standalone_de_ready,
            "checks": [check.as_dict() for check in self.checks],
        }

    @property
    def compositor_available(self) -> bool:
        return self.checks[0].status == "ok"


def inspect(
    *,
    environment: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> Report:
    """Return public capability labels, without executing or mutating anything."""
    env = os.environ if environment is None else environment
    session_type = str(env.get("XDG_SESSION_TYPE", "")).lower()
    if session_type not in {"wayland", "x11"}:
        session_type = "unknown"

    tools = {name: bool(which(name)) for name in (*REQUIRED_TOOLS, "swayidle")}
    labwc = tools["labwc"]
    xwayland = bool(which("Xwayland"))
    riceplate = bool(which("riceplate-native"))
    session_bus = bool(env.get("DBUS_SESSION_BUS_ADDRESS")) or bool(which("dbus-run-session"))
    nested_ready = session_bus and all(tools[name] for name in REQUIRED_TOOLS)
    login_ready = nested_ready and tools["swayidle"]
    checks = [
        Check("labwc", "ok" if labwc else "missing", "labwc compositor",
              "Available" if labwc else "Install labwc for the future Wayland session."),
        Check("session-bus", "ok" if session_bus else "missing", "D-Bus session",
              "Active user bus or dbus-run-session available" if session_bus else
              "No session bus detected; user session integration will need one."),
        Check("xwayland", "ok" if xwayland else "optional", "XWayland compatibility",
              "Available" if xwayland else "Not found; legacy X11 apps may not run."),
        Check("riceplate", "ok" if riceplate else "optional", "Native RicePlate preview",
              "Native panel executable found; this does not validate compositor or device integration."
              if riceplate else "Not installed; the separate Waybar Wayland preview remains available."),
    ]
    for name, label in (
        ("waybar", "Waybar recovery panel"),
        ("foot", "Terminal"),
        ("fuzzel", "Application launcher"),
        ("swaylock", "Lock screen"),
        ("swayidle", "Idle and pre-suspend lock guard"),
    ):
        checks.append(Check(name, "ok" if tools[name] else "missing", label,
                            "Available" if tools[name] else
                            f"Install {name} before a full Wayland login."))
    checks.append(
        Check("integration", "planned", "Portal, lock and power integration",
              "Executable checks do not verify portal consent, lock behavior or physical hardware."),
    )
    return Report(session_type=session_type, checks=tuple(checks),
                  nested_prerequisites_ready=nested_ready,
                  login_prerequisites_ready=login_ready,
                  native_login_prerequisites_ready=login_ready and riceplate)
