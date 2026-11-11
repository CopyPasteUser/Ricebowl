"""Explicit, reversible resource preferences for the existing Control Center.

Light/Balanced/Visual map to its tested Light/Balanced/Responsive policies.
No always-running profile daemon, silent hardware guesses or extra dependencies.
"""

from __future__ import annotations

import os
import shutil
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from .environment import config_home, data_home, private_state_root
from .shell_session import SHELLS
from .themes import _read_preferences, _stage_json


RICEBOWL_NAMES = {
    "aero": "RiceBowl Windows 7", "ten": "RiceBowl Windows 10",
    "winxp": "RiceBowl XP Luna", "winclassic": "RiceBowl Windows 98 SE",
    "chromeos": "RiceBowl ChromeOS", "frutiger": "RiceBowl Frutiger Aero",
}

# These are resource/ownership classifications, not permission to stop a
# service. All listed processes remain under the user's existing session.
XFCE_ROLES = {
    "xfwm4": "core", "xfce4-session": "core", "xfconfd": "core",
    "xfsettingsd": "core", "xfdesktop": "core",
    "xfce4-power-manager": "shared", "xfce4-notifyd": "shared",
    "xfce4-screensaver": "shared", "xfce4-clipman": "shared",
    "tumblerd": "shared", "xfce4-appfinder": "shared",
    "xfce4-panel": "replaceable",
}

# Existing upstream labwc session components are counted on demand. This is
# an ownership inventory, never permission to kill or disable a service.
WAYLAND_ROLES = {
    "labwc": "compositor", "waybar": "panel", "riceplate-native": "panel",
    "swaybg": "wallpaper", "mako": "notifications", "swayidle": "idle",
    "swaylock": "lock", "fuzzel": "launcher",
}


PROFILES = {
    "light": {
        "resource_profile": "light", "animation_speed": "off",
        "reduce_motion": True, "media_thumbnail": False,
    },
    "balanced": {
        "resource_profile": "balanced", "animation_speed": "fast",
        "reduce_motion": False, "media_thumbnail": True,
    },
    "visual": {
        "resource_profile": "responsive", "animation_speed": "smooth",
        "reduce_motion": False, "media_thumbnail": True,
    },
}


def _component(argv: list[str]) -> str | None:
    if any(Path(arg).name == "launcher.py" for arg in argv[:3]):
        for profile, title in RICEBOWL_NAMES.items():
            if SHELLS[profile] in argv[2:5]:
                return title
    if any(argv[i:i + 2] == ["-m", "macmenu"] for i in range(len(argv) - 1)):
        return "MacMenu"
    names = {Path(arg).name for arg in argv[:4]}
    if "macos-control-center" in names:
        return "Control Center"
    if "macbar.py" in names or "macbar" in names:
        return "MacBar"
    if argv and Path(argv[0]).name == "plank":
        return "Plank"
    return None


def _desktop_component(argv: list[str]) -> tuple[str, str] | None:
    """Match only executable names, never user arguments or window titles."""
    if not argv:
        return None
    name = Path(argv[0]).name
    role = XFCE_ROLES.get(name) or WAYLAND_ROLES.get(name)
    return (name, role) if role else None


def _process_ticks(process: Path) -> int | None:
    try:
        # The command name in stat may contain spaces or parentheses.
        fields = (process / "stat").read_text().rsplit(") ", 1)[1].split()
        return int(fields[11]) + int(fields[12])
    except (IndexError, OSError, ValueError):
        return None


def _process_threads(process: Path) -> int | None:
    try:
        for line in (process / "status").read_text().splitlines():
            if line.startswith("Threads:"):
                return int(line.split()[1])
    except (IndexError, OSError, ValueError):
        pass
    return None


def current_wayland_session_config(environment: Mapping[str, str]) -> str:
    """Require an opt-in *full* RiceBowl Wayland session, never a nested demo."""
    marker = environment.get("RICEBOWL_DE_SESSION_CONFIG", "")
    path = Path(marker)
    if (environment.get("RICEBOWL_DE_SHELL_CHILD") != "1"
            or environment.get("RICEBOWL_DE_NESTED") != "0"
            or environment.get("XDG_SESSION_TYPE") != "wayland"
            or not marker or not path.is_absolute() or ".." in path.parts):
        raise ValueError("--wayland-session requires a running full RiceBowl Wayland login")
    return marker


def _belongs_to_wayland_session(process: Path, session_config: str) -> bool:
    """Bounded exact-match of initial process environment; absence is unknown."""
    try:
        with (process / "environ").open("rb") as stream:
            payload = stream.read(131073)
    except OSError:
        return False
    if len(payload) > 131072:
        return False
    fields = set(payload.split(b"\0"))
    return {b"RICEBOWL_DE_SHELL_CHILD=1", b"RICEBOWL_DE_NESTED=0",
            b"RICEBOWL_DE_SESSION_CONFIG=" + os.fsencode(session_config)}.issubset(fields)


def measure_processes(*, proc_root: Path = Path("/proc"), sample_ms: int = 200,
                      include_desktop: bool = False,
                      session_config: str | None = None) -> list[dict]:
    """On-demand PSS/CPU report. Never runs as a resident background monitor."""
    processes = []
    uid = os.getuid()
    for process in proc_root.iterdir():
        if not process.name.isdecimal():
            continue
        try:
            if process.stat().st_uid != uid:
                continue
            argv = (process / "cmdline").read_bytes()[:8192].decode("utf-8", "replace").rstrip("\0").split("\0")
            name = _component(argv)
            role = "ricebowl" if name in RICEBOWL_NAMES.values() else "dock" if name == "Plank" else "shared"
            if not name and include_desktop:
                xfce = _desktop_component(argv)
                if xfce:
                    name, role = xfce
            if not name:
                continue
            if session_config is not None and not _belongs_to_wayland_session(process, session_config):
                continue
            pss = None
            try:
                for line in (process / "smaps_rollup").read_text().splitlines():
                    if line.startswith("Pss:"):
                        pss = int(line.split()[1])
                        break
            except (OSError, ValueError):
                pass
            processes.append({"name": name, "pid": int(process.name), "pss_kib": pss,
                              "ticks": _process_ticks(process), "threads": _process_threads(process),
                              "path": process, "role": role})
        except (OSError, ValueError):
            continue
    if not processes:
        return []
    start = time.monotonic()
    time.sleep(max(50, min(sample_ms, 1000)) / 1000)
    elapsed = max(0.001, time.monotonic() - start)
    ticks_per_second = os.sysconf("SC_CLK_TCK")
    result = []
    for item in processes:
        latest = _process_ticks(item["path"])
        delta = max(0, latest - item["ticks"]) if latest is not None and item["ticks"] is not None else None
        reading = {"name": item["name"], "pid": item["pid"], "pss_kib": item["pss_kib"],
                   "threads": item["threads"],
                   "cpu_percent": round(100 * delta / (elapsed * ticks_per_second), 1) if delta is not None else None}
        if include_desktop:
            reading["role"] = item["role"]
        result.append(reading)
    return result


def summarize_samples(samples: list[list[dict]]) -> dict:
    """Median per-PID resource snapshot; absent counters stay explicitly unknown.

    PSS estimates unique resident footprint; summing RSS would double count
    shared libraries. Per-process CPU is a one-core percentage, not a machine
    total, and sampling does not run unless explicitly requested.
    """
    grouped = {}
    for sample in samples:
        for item in sample:
            key = (item["name"], item["pid"])
            grouped.setdefault(key, []).append(item)
    components = []
    for (name, pid), readings in sorted(grouped.items()):
        medians = {}
        for field in ("pss_kib", "cpu_percent", "threads"):
            values = [item[field] for item in readings if item[field] is not None]
            medians[field] = round(statistics.median(values), 1) if values else None
        components.append({"name": name, "pid": pid, "observations": len(readings),
                           **medians})
    totals = {field: [] for field in ("pss_kib", "cpu_percent")}
    partial = False
    for sample in samples:
        for field in totals:
            observed = [item[field] for item in sample if item[field] is not None]
            if sample and len(observed) == len(sample):
                totals[field].append(sum(observed))
            elif sample:
                partial = True
    partial |= any(entry[field] is None for entry in components
                   for field in ("pss_kib", "cpu_percent"))
    return {
        "samples": len(samples), "components": components,
        "total_pss_kib": round(statistics.median(totals["pss_kib"]), 1)
        if totals["pss_kib"] else None,
        "total_cpu_percent": round(statistics.median(totals["cpu_percent"]), 1)
        if totals["cpu_percent"] else None,
        "partial": partial,
    }


def desktop_session_report(samples: list[list[dict]], *,
                           session_config: str | None = None) -> dict:
    """Read-only desktop footprint, optionally filtered by initial session marker."""
    report = summarize_samples(samples)
    roles = {(item["name"], item["pid"]): item["role"]
             for sample in samples for item in sample if "role" in item}
    for item in report["components"]:
        item["role"] = roles.get((item["name"], item["pid"]), "unknown")

    def role_pss(names: dict[str, str]) -> float | None:
        totals = []
        for sample in samples:
            matching = [item for item in sample if item["name"] in names]
            if matching and any(item["pss_kib"] is None for item in matching):
                return None
            if matching:
                totals.append(sum(item["pss_kib"] for item in matching
                                  if item["pss_kib"] is not None))
        return round(statistics.median(totals), 1) if totals else None

    report["xfce_pss_kib"] = role_pss(XFCE_ROLES)
    report["wayland_pss_kib"] = role_pss(WAYLAND_ROLES)
    if session_config is not None:
        report["scope"] = "current-wayland-session"
        report["scope_note"] = (
            "Current full Wayland login marker: only recognized components with an exact "
            "initial process environment match. Unreadable environments are excluded; "
            "not a complete or hardware-certified session memory benchmark."
        )
    else:
        report["scope"] = "all-user-owned"
        report["scope_note"] = (
            "All matching user-owned processes, potentially across nested/other sessions; "
            "not an isolated single-session memory benchmark."
        )

    names = {item["name"] for item in report["components"]}
    active_rices = names.intersection(RICEBOWL_NAMES.values())
    running_rices = [item for item in report["components"] if item["name"] in active_rices]
    warnings = []
    if len(running_rices) > 1:
        warnings.append("Multiple RiceBowl taskbars are running; only the selected rice should remain.")
    if "xfce4-panel" in names and (active_rices or "MacBar" in names):
        warnings.append("xfce4-panel overlaps a RiceBowl/MacBar panel; check session handoff.")
    if active_rices and "Plank" in names:
        warnings.append("Plank is still running alongside a non-macOS RiceBowl taskbar.")
    if active_rices and "MacBar" in names:
        warnings.append("MacBar is still running alongside a non-macOS RiceBowl taskbar.")
    if "waybar" in names and "riceplate-native" in names:
        warnings.append("Waybar and native RicePlate coexist; check for duplicate panels "
                        "within one session (nested previews may be intentional).")
    report["warnings"] = warnings
    return report


def apply_profile(name: str, *, config_root: Path | None = None,
                  data_root: Path | None = None) -> Path:
    """Back up the complete previous config, atomically update only profile keys."""
    if name not in PROFILES:
        raise ValueError("Choose light, balanced or visual")
    if os.geteuid() == 0:
        raise ValueError("Apply performance profiles as your desktop user, never with sudo")
    config_root = config_root or config_home()
    data_root = data_root or data_home()
    target = config_root / "macos-control-center/config.json"
    if target.parent.is_symlink():
        raise ValueError("Refusing to update preferences through a symlinked directory")
    previous = _read_preferences(target)
    updated = {**previous, **PROFILES[name]}
    if updated == previous:
        return target

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = private_state_root(data_root) / "backups/performance" / stamp
    backup.mkdir(mode=0o700, parents=True, exist_ok=False)
    if target.exists():
        copy = backup / "control-center-config.json"
        shutil.copy2(target, copy, follow_symlinks=False)
        os.chmod(copy, 0o600)
    else:
        (backup / "previously-absent").write_text("Config was absent before profile change\n")

    temporary = _stage_json(target, updated)
    try:
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return backup
