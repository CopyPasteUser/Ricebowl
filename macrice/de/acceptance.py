"""Read-only on-device acceptance preflight for the experimental Wayland shell.

This intentionally does not certify hardware: a human must exercise the
keyboard, screen reader, login and recovery paths on the actual machine.
No display, service, preference or session state is changed by this module.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from .session import DESKTOP_NAME


@dataclass(frozen=True)
class ManualCheck:
    key: str
    title: str
    procedure: str
    status: str = "pending"


MANUAL_CHECKS = (
    ManualCheck("login", "Session selection and relogin",
                "Choose native RiceBowl at the greeter, log out, log back in and verify XFCE is still selectable."),
    ManualCheck("apps", "Real application launch",
                "Open an installed app from RicePlate, search using a localized name, close it and relaunch."),
    ManualCheck("keyboard", "Keyboard and window focus",
                "Navigate the menu with arrows, Tab/Shift+Tab, Enter and Escape; test Alt+Tab and app focus."),
    ManualCheck("accessibility", "Screen reader and accessible focus",
                "With Orca enabled, check spoken button labels, menu focus, status updates and recovery."),
    ManualCheck("displays", "Multi-monitor and scaling",
                "Test each display, different scales, unplug/replug, menu ownership and persisted placement."),
    ManualCheck("portals", "Clipboard, XWayland and portals",
                "Test native/XWayland clipboard, file chooser, screenshot permission and screen sharing."),
    ManualCheck("lock", "Lock and suspend",
                "Verify explicit lock, idle lock, suspend/resume, lid close and keyboard unlock."),
    ManualCheck("recovery", "Fail-safe return to XFCE",
                "Test a normal logout, select XFCE again and confirm the previous desktop is unchanged."),
    ManualCheck("resources", "Real resource baseline",
                "Measure cold login, settled PSS/RSS, idle CPU and app launch latency on your ThinkPad."),
)


@dataclass(frozen=True)
class Report:
    session_type: str
    ricebowl_session: bool
    nested: bool
    selected_panel: str
    wayland_socket: str
    output_probe: str
    active_outputs: int | None
    fractional_scale_present: bool | None
    required_tools_present: bool
    ready_for_manual_checks: bool
    manual_checks: tuple[ManualCheck, ...] = MANUAL_CHECKS

    @property
    def next_step(self) -> str:
        if (self.session_type != "wayland" or not self.ricebowl_session or self.nested
                or self.selected_panel != "native"):
            return "Log in using the opt-in native RiceBowl session; keep XFCE as fallback."
        if self.wayland_socket != "present":
            return "Inspect the current user's private Wayland runtime/socket."
        if not self.required_tools_present:
            return "Check native RicePlate, labwc and swaylock/swayidle installation."
        if self.output_probe != "observed" or not self.active_outputs:
            return "Check the read-only wlr-randr --json display probe before device tests."
        return "Run each pending manual test; readiness is not hardware approval."

    def as_dict(self) -> dict[str, object]:
        return {"schema_version": 1,
                "session": {"type": self.session_type,
                            "ricebowl": self.ricebowl_session,
                            "nested": self.nested,
                            "selected_panel": self.selected_panel,
                            "wayland_socket": self.wayland_socket},
                "outputs": {"probe": self.output_probe,
                            "active_count": self.active_outputs,
                            "fractional_scale_present": self.fractional_scale_present},
                "required_tools_present": self.required_tools_present,
                "ready_for_manual_checks": self.ready_for_manual_checks,
                "next_step": self.next_step,
                "hardware_accepted": False,
                "manual_checks": [asdict(check) for check in self.manual_checks]}


def _socket_state(env: Mapping[str, str]) -> str:
    """Check an owned Wayland UNIX socket, without connecting to the session."""
    display = env.get("WAYLAND_DISPLAY", "")
    runtime = env.get("XDG_RUNTIME_DIR", "")
    if not display or "\x00" in display or not runtime:
        return "missing"
    try:
        runtime_info = Path(runtime).lstat()
    except OSError:
        return "missing"
    if (not Path(runtime).is_absolute() or not stat.S_ISDIR(runtime_info.st_mode)
            or runtime_info.st_uid != os.getuid() or runtime_info.st_mode & 0o077):
        return "invalid"
    path = Path(display)
    if not path.is_absolute():
        path = Path(runtime) / path
    try:
        details = path.lstat()  # Do not follow untrusted socket symlinks.
    except OSError:
        return "missing"
    if not stat.S_ISSOCK(details.st_mode) or details.st_uid != os.getuid():
        return "invalid"
    return "present"


def _outputs(env: Mapping[str, str], binary: str | None,
             run: Callable[..., subprocess.CompletedProcess[str]]) -> tuple[str, int | None, bool | None]:
    if not binary:
        return "tool-missing", None, None
    try:
        result = run([binary, "--json"], env=dict(env), capture_output=True,
                     text=True, timeout=3, check=True)
        if len(result.stdout) > 65_536:
            return "invalid-response", None, None
        raw = json.loads(result.stdout)
        if not isinstance(raw, list) or len(raw) > 32:
            return "invalid-response", None, None
        if not all(isinstance(item, dict) for item in raw):
            return "invalid-response", None, None
        enabled = [item for item in raw if isinstance(item, dict) and item.get("enabled") is True]
        scales = [item.get("scale", 1) for item in enabled]
        if any(type(value) not in (int, float) or not 0.25 <= value <= 8 for value in scales):
            return "invalid-response", None, None
        return "observed", len(enabled), any(value != int(value) for value in scales)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return "unavailable", None, None


def inspect(*, environment: Mapping[str, str] | None = None,
            which: Callable[[str], str | None] = shutil.which,
            socket_probe: Callable[[Mapping[str, str]], str] = _socket_state,
            run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> Report:
    """Inspect only the current session and public capabilities, never user data."""
    env = os.environ if environment is None else environment
    session_type = env.get("XDG_SESSION_TYPE", "").lower()
    if session_type not in {"wayland", "x11"}:
        session_type = "unknown"
    ricebowl = (env.get("XDG_CURRENT_DESKTOP") == DESKTOP_NAME
                and env.get("RICEBOWL_DE_SHELL_CHILD") == "1")
    nested = env.get("RICEBOWL_DE_NESTED") == "1"
    panel = env.get("RICEBOWL_DE_PANEL", "")
    panel = panel if panel in {"native", "waybar"} else "unknown"
    socket_state = socket_probe(env) if session_type == "wayland" else "not-wayland"
    required = all(which(tool) for tool in ("labwc", "riceplate-native", "swaylock", "swayidle"))
    eligible = (session_type == "wayland" and ricebowl and not nested
                and panel == "native" and socket_state == "present" and required)
    probe, count, fractional = (_outputs(env, which("wlr-randr"), run) if eligible
                                else ("not-run", None, None))
    return Report(session_type=session_type, ricebowl_session=ricebowl,
                  nested=nested, selected_panel=panel, wayland_socket=socket_state,
                  output_probe=probe, active_outputs=count,
                  fractional_scale_present=fractional, required_tools_present=required,
                  ready_for_manual_checks=eligible and probe == "observed" and count is not None and count > 0)
