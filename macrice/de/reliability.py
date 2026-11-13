"""Read-only, bounded observation of an opt-in labwc/RiceBowl session.

The report never equates same-UID process names with session membership.
It neither starts services nor attempts to repair a recipe or journal.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from . import acceptance, live_recovery
from .session import DESKTOP_NAME, REQUIRED_TOOLS

# Kernel comm names are limited to 15 bytes. Do not infer process membership
# from argv (which can expose unrelated private commands and arguments).
PROCESS_NAMES = {
    "compositor": ("labwc",),
    "native-panel": ("riceplate-nativ", "riceplate-native"),
    "fallback-panel": ("waybar",),
    "lock-guard": ("swayidle",),
    "wallpaper": ("swaybg",),
    "notifications": ("mako",),
    "accessibility": ("orca",),
    "xfce-session": ("xfce4-session",),
    "xfce-wm": ("xfwm4",),
    "xfce-panel": ("xfce4-panel",),
    "xfce-desktop": ("xfdesktop",),
    "xfce-settings": ("xfsettingsd",),
}
REQUIRED_PROTOCOLS = ("wl_compositor", "xdg_wm_base", "zwlr_layer_shell_v1")
OPTIONAL_PROTOCOLS = ("zwlr_foreign_toplevel_manager_v1", "zwlr_output_manager_v1")
MAX_PROCESS_SCAN = 32768
MAX_WAYLAND_OUTPUT = 65_536


@dataclass(frozen=True)
class ProcessSample:
    pid: int
    role: str
    start_ticks: int
    cpu_ticks: int
    rss_kib: int | None
    pss_kib: int | None
    switches: int | None
    wakeups: int | None


def _numeric_line(text: str, prefix: str) -> int | None:
    for line in text.splitlines():
        if line.startswith(prefix):
            tail = line[len(prefix):].strip().split()
            if tail and tail[0].isdigit():
                return int(tail[0])
    return None


def _sample_pid(path: Path, *, uid: int) -> ProcessSample | None:
    """Read only metadata for allowlisted processes owned by this user."""
    try:
        status = (path / "status").read_text(encoding="ascii")
        uid_line = next((line for line in status.splitlines()
                         if line.startswith("Uid:")), "")
        uid_fields = uid_line[4:].split()
        if not uid_fields or not uid_fields[0].isdigit() or int(uid_fields[0]) != uid:
            return None
        name = next((line[5:].strip() for line in status.splitlines()
                     if line.startswith("Name:")), "")
        role = next((key for key, names in PROCESS_NAMES.items() if name in names), None)
        if role is None:
            return None
        # Field 22 = starttime, 14+15 = user/system jiffies. Split at the
        # last ')' because /proc/PID/comm can itself contain parentheses.
        stat_fields = (path / "stat").read_text(encoding="ascii").rsplit(") ", 1)[1].split()
        start = int(stat_fields[19])
        cpu_ticks = int(stat_fields[11]) + int(stat_fields[12])
        rss = _numeric_line(status, "VmRSS:")
        try:
            pss = _numeric_line((path / "smaps_rollup").read_text(encoding="ascii"), "Pss:")
        except (OSError, UnicodeError):
            pss = None
        switches_a = _numeric_line(status, "voluntary_ctxt_switches:")
        switches_b = _numeric_line(status, "nonvoluntary_ctxt_switches:")
        switches = switches_a + switches_b if switches_a is not None and switches_b is not None else None
        try:
            sched = (path / "sched").read_text(encoding="ascii")
            wakeups = None
            for line in sched.splitlines():
                if re.match(r"^nr_wakeups\s*:", line):
                    value = line.split(":", 1)[1].strip()
                    if value.isdigit():
                        wakeups = int(value)
                    break
        except (OSError, UnicodeError):
            wakeups = None
        return ProcessSample(int(path.name), role, start, cpu_ticks, rss, pss, switches, wakeups)
    except (OSError, UnicodeError, ValueError, IndexError, StopIteration):
        return None


def scan_processes(*, proc_root: Path = Path("/proc"), uid: int | None = None
                   ) -> tuple[ProcessSample, ...]:
    """Bound /proc enumeration; never read other users' argv or environment."""
    owner = os.getuid() if uid is None else uid
    found = []
    try:
        entries = proc_root.iterdir()
        scanned = 0
        for path in entries:
            if not path.name.isdecimal():
                continue
            scanned += 1
            if scanned > MAX_PROCESS_SCAN:
                break
            sample = _sample_pid(path, uid=owner)
            if sample:
                found.append(sample)
    except OSError:
        return tuple()
    return tuple(sorted(found, key=lambda item: item.pid))


def _probe_protocols(*, enabled: bool, env: Mapping[str, str],
                     which: Callable[[str], str | None],
                     run: Callable[..., subprocess.CompletedProcess[str]]
                     ) -> dict[str, object]:
    names = (*REQUIRED_PROTOCOLS, *OPTIONAL_PROTOCOLS)
    if not enabled:
        return {"probe": "not-run", "required": {name: None for name in REQUIRED_PROTOCOLS},
                "optional": {name: None for name in OPTIONAL_PROTOCOLS}}
    binary = which("wayland-info")
    if binary is None:
        return {"probe": "tool-missing", "required": {name: None for name in REQUIRED_PROTOCOLS},
                "optional": {name: None for name in OPTIONAL_PROTOCOLS}}
    try:
        result = run([binary], env=dict(env), capture_output=True, text=True,
                     timeout=3, check=False)
        if (result.returncode != 0 or len(result.stdout) > MAX_WAYLAND_OUTPUT):
            raise ValueError("Protocol discovery failed")
        # Only known interface names leave this function. Arbitrary compositor
        # text and window/application titles are never returned.
        # Parse protocol registry advertisements, not arbitrary titles,
        # error strings or help text that merely mention an interface.
        advertised = set(re.findall(
            r"""^\s*interface:\s*['"]([a-zA-Z0-9_]+)['"]""",
            result.stdout, flags=re.MULTILINE))
        found = set(names) & advertised
        return {"probe": "observed",
                "required": {name: name in found for name in REQUIRED_PROTOCOLS},
                "optional": {name: name in found for name in OPTIONAL_PROTOCOLS}}
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return {"probe": "unavailable", "required": {name: None for name in REQUIRED_PROTOCOLS},
                "optional": {name: None for name in OPTIONAL_PROTOCOLS}}


def _probe_bus(*, enabled: bool, env: Mapping[str, str],
               which: Callable[[str], str | None],
               run: Callable[..., subprocess.CompletedProcess[str]]) -> str:
    """Ping the existing user bus once without activating an arbitrary service."""
    if not enabled:
        return "not-run"
    if not env.get("DBUS_SESSION_BUS_ADDRESS"):
        return "not-declared"
    binary = which("dbus-send")
    if binary is None:
        return "tool-missing"
    try:
        result = run(
            [binary, "--session", "--type=method_call", "--print-reply=literal",
             "--reply-timeout=1500", "--dest=org.freedesktop.DBus",
             "/org/freedesktop/DBus", "org.freedesktop.DBus.Peer.Ping"],
            env=dict(env), capture_output=True, text=True, timeout=3,
            check=False)
        return "responsive" if result.returncode == 0 else "unreachable"
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return "unavailable"


def inspect(*, environment: Mapping[str, str] | None = None,
            which: Callable[[str], str | None] = shutil.which,
            run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
            socket_probe: Callable[[Mapping[str, str]], str] = acceptance._socket_state,
            samples: tuple[ProcessSample, ...] | None = None,
            recovery: Mapping[str, object] | None = None) -> dict[str, object]:
    """Produce sanitized observations; none proves a full physical login."""
    env = os.environ if environment is None else environment
    session_type = env.get("XDG_SESSION_TYPE", "").lower()
    if session_type not in ("x11", "wayland"):
        session_type = "unknown"
    marked = (session_type == "wayland"
              and env.get("XDG_CURRENT_DESKTOP") == DESKTOP_NAME
              and env.get("RICEBOWL_DE_SHELL_CHILD") == "1")
    nested = env.get("RICEBOWL_DE_NESTED") == "1"
    panel = env.get("RICEBOWL_DE_PANEL", "unknown")
    if panel not in ("native", "waybar"):
        panel = "unknown"
    socket = socket_probe(env) if marked else "not-checked"
    if socket not in ("present", "missing", "invalid", "not-checked"):
        socket = "invalid"
    protocols = _probe_protocols(enabled=marked and socket == "present",
                                 env=env, which=which, run=run)
    binaries = {name: bool(which(name)) for name in
                (*REQUIRED_TOOLS, "swayidle", "riceplate-native", "mako",
                 "swaybg", "orca", "wayland-info", "wlr-randr")}
    mandatory = (*REQUIRED_TOOLS, "swayidle")
    required_missing = [name for name in mandatory if not binaries[name]]
    if panel == "native" and not binaries["riceplate-native"]:
        required_missing.append("riceplate-native")
    if marked:
        records = scan_processes() if samples is None else samples
        processes = {}
        for role in PROCESS_NAMES:
            selected = [item for item in records if item.role == role]
            processes[role] = {
                "count": len(selected),
                "rss_kib": sum(x.rss_kib for x in selected if x.rss_kib is not None)
                            if selected and all(x.rss_kib is not None for x in selected) else None,
                "pss_kib": sum(x.pss_kib for x in selected if x.pss_kib is not None)
                            if selected and all(x.pss_kib is not None for x in selected) else None,
            }
    else:
        processes = None
    if recovery is None:
        try:
            recovery = live_recovery.status()
        except (OSError, ValueError):
            recovery = {"ok": False, "pending": None}
    # Never return untrusted journal data, paths or process command lines.
    journal = {"state": ("unsafe" if recovery.get("ok") is not True else
                         "pending" if recovery.get("pending") is True else "clean"
                         if recovery.get("pending") is False else "unknown"),
               "owner_running": recovery.get("owner_running")
               if type(recovery.get("owner_running")) is bool else None,
               "recent_events": "not-recorded"}
    return {
        "schema_version": 1, "read_only": True, "hardware_accepted": False,
        "session": {"type": session_type, "ricebowl_marked": marked,
                    "nested": nested, "panel": panel, "socket": socket},
        "binaries": binaries, "required_missing": required_missing,
        "session_bus": {
            "address_declared": bool(env.get("DBUS_SESSION_BUS_ADDRESS")),
            "probe": _probe_bus(enabled=marked, env=env, which=which, run=run),
        },
        "protocols": protocols, "processes": processes,
        "process_scope": "same-uid-not-session-attributed" if marked else "not-probed",
        "recovery": journal,
        "limitations": ["Process name matches can include other sessions of the same user",
                        "No persisted supervisor event history; pending journal only",
                        "No login-to-ready startup timing or hardware validation"],
    }
