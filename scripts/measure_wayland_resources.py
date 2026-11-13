#!/usr/bin/env python3
"""On-demand, side-effect-free /proc sampling; never claims a cold-login result.

Run once per session after settling; compare JSON snapshots from native,
Waybar and XFCE on the same machine. No daemon, sudo, perf or writes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from macrice.de.reliability import ProcessSample, scan_processes

PROFILES = {
    "native": ("compositor", "native-panel", "fallback-panel", "lock-guard",
               "wallpaper", "notifications", "accessibility"),
    "waybar": ("compositor", "fallback-panel", "lock-guard",
               "wallpaper", "notifications", "accessibility"),
    "xfce": ("xfce-session", "xfce-wm", "xfce-panel", "xfce-desktop", "xfce-settings"),
}


def actual_profile(env: Mapping[str, str]) -> str:
    if env.get("XDG_SESSION_TYPE") == "x11" and "XFCE" in env.get("XDG_CURRENT_DESKTOP", "").upper():
        return "xfce"
    if (env.get("XDG_SESSION_TYPE") == "wayland"
            and env.get("RICEBOWL_DE_SHELL_CHILD") == "1"):
        if env.get("RICEBOWL_DE_PANEL") in ("native", "waybar"):
            return env["RICEBOWL_DE_PANEL"]
    return "unknown"


def _total(values: list[int | None]) -> int | None:
    return sum(v for v in values if v is not None) if values and all(v is not None for v in values) else None


def measure(profile: str, *, seconds: float = 10.0,
            reader: Callable[[], tuple[ProcessSample, ...]] = scan_processes,
            sleep: Callable[[float], None] = time.sleep,
            clock: Callable[[], float] = time.monotonic,
            ticks_per_second: int | None = None,
            environment: Mapping[str, str] | None = None) -> dict[str, object]:
    if profile not in PROFILES or not 1 <= seconds <= 120:
        raise ValueError("Select a known profile and a sample duration of 1–120 seconds")
    ticks = os.sysconf("SC_CLK_TCK") if ticks_per_second is None else ticks_per_second
    if ticks <= 0:
        raise ValueError("Kernel clock resolution is invalid")
    env = os.environ if environment is None else environment
    first = { (p.pid, p.start_ticks): p for p in reader() if p.role in PROFILES[profile] }
    begin = clock()
    sleep(seconds)
    elapsed = clock() - begin
    if elapsed <= 0:
        raise ValueError("Nonpositive sample duration")
    last = { (p.pid, p.start_ticks): p for p in reader() if p.role in PROFILES[profile] }
    matched = set(first) & set(last)
    cpu = sum(max(0, last[key].cpu_ticks - first[key].cpu_ticks) for key in matched)
    switches = _total([last[key].switches - first[key].switches
                       if first[key].switches is not None and last[key].switches is not None
                       else None for key in matched])
    wakeups = _total([last[key].wakeups - first[key].wakeups
                      if first[key].wakeups is not None and last[key].wakeups is not None
                      else None for key in matched])
    current = list(last.values())
    actual = actual_profile(env)
    return {
        "schema_version": 1, "profile_requested": profile, "profile_observed": actual,
        "profile_matches": actual == profile, "read_only": True,
        "hardware_accepted": False, "idle_confirmed": False,
        "cold_login_to_ready_ms": None,
        "elapsed_s": round(elapsed, 3),
        "process_scope": "same-uid-comm-matches-not-exclusive-session",
        "process_count": len(current), "stable_process_count": len(matched),
        "rss_kib": _total([p.rss_kib for p in current]),
        "pss_kib": _total([p.pss_kib for p in current]),
        # 100% = one logical core. Only processes present in both samples are
        # included; a restarted process is not silently counted as CPU-free.
        "cpu_percent_one_core": round(100 * cpu / (ticks * elapsed), 3),
        "context_switches_per_s": round(switches / elapsed, 3) if switches is not None else None,
        "kernel_wakeups_per_s": round(wakeups / elapsed, 3) if wakeups is not None else None,
        "process_restart_or_exit_detected": set(first) != set(last),
        "notes": [
            "Kernel wakeups only when /proc/PID/sched exports nr_wakeups; "
            "context switches are not wakeups",
            "A per-user process-name sample cannot prove session membership",
            "Cold greeter-to-ready timing and idle status require manual on-device observation",
            "Compare three separately captured profiles on identical hardware and workload",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=tuple(PROFILES), required=True)
    parser.add_argument("--seconds", type=float, default=10)
    args = parser.parse_args(argv)
    try:
        report = measure(args.profile, seconds=args.seconds)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2))
    return 0 if report["profile_matches"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
