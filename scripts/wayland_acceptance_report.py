#!/usr/bin/env python3
"""Read-only Mint 22 acceptance dossier; never automatically approves hardware."""

from __future__ import annotations

import argparse
import json
import math
import os
import stat
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from macrice.de import acceptance, reliability

MAX_SAMPLE_BYTES = 65_536
PROFILES = ("native", "waybar", "xfce")
METRICS = ("rss_kib", "pss_kib", "cpu_percent_one_core",
           "context_switches_per_s", "kernel_wakeups_per_s")


def load_sample(path: Path, *, profile: str) -> dict[str, object]:
    """Validate provenance and the bounded numeric subset, never trust claims."""
    if not path.is_absolute():
        raise ValueError(f"{profile}: sample must have an absolute path")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as stream:
            meta = os.fstat(stream.fileno())
            if not stat.S_ISREG(meta.st_mode) or meta.st_size > MAX_SAMPLE_BYTES:
                raise ValueError(f"{profile}: sample is not a bounded regular file")
            raw = stream.read(MAX_SAMPLE_BYTES + 1)
        if len(raw) > MAX_SAMPLE_BYTES:
            raise ValueError(f"{profile}: sample exceeds size limit")
        data = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{profile}: sample cannot be safely parsed") from exc
    if (type(data) is not dict or data.get("schema_version") != 1
            or data.get("profile_requested") != profile
            or data.get("profile_observed") != profile
            or data.get("profile_matches") is not True
            or data.get("read_only") is not True
            or data.get("hardware_accepted") is not False
            or data.get("process_scope") != "same-uid-comm-matches-not-exclusive-session"
            or type(data.get("process_count")) is not int
            or data["process_count"] <= 0
            or type(data.get("elapsed_s")) not in (int, float)
            or not math.isfinite(data["elapsed_s"]) or data["elapsed_s"] < 1):
        raise ValueError(f"{profile}: sample is unverified, empty or from a mismatched session")
    for name in METRICS:
        value = data.get(name)
        if value is not None and (type(value) not in (int, float)
                                  or not math.isfinite(value) or value < 0):
            raise ValueError(f"{profile}: invalid {name} measurement")
    # Retain only bounded, non-identifying fields; never embed arbitrary notes.
    return {"profile": profile, "process_count": data["process_count"],
            "elapsed_s": data["elapsed_s"],
            **{metric: data.get(metric) for metric in METRICS},
            "cold_login_to_ready_ms": None,
            "idle_confirmed": False}


def create_report(samples: dict[str, dict[str, object]] | None = None, *,
                  acceptance_probe=None, reliability_probe=None) -> dict[str, Any]:
    """Assemble a reproducible checklist without pretending CI was on Mint hardware."""
    a = acceptance.inspect() if acceptance_probe is None else acceptance_probe
    r = reliability.inspect() if reliability_probe is None else reliability_probe
    data = samples if samples is not None else {}
    if set(data) - set(PROFILES):
        raise ValueError("Only native, waybar and xfce measurements are supported")
    differences: dict[str, dict[str, float | None]] = {}
    if len(data) == 3:
        for key in ("native", "waybar"):
            differences[f"{key}_minus_xfce"] = {}
            for metric in METRICS:
                left, right = data[key][metric], data["xfce"][metric]
                differences[f"{key}_minus_xfce"][metric] = (
                    round(float(left) - float(right), 3)
                    if left is not None and right is not None else None)
    return {
        "report_version": 1, "target": "Linux Mint 22 / physical Wayland opt-in",
        "read_only": True, "hardware_accepted": False,
        "headless_ci_is_hardware_acceptance": False,
        "acceptance": a.as_dict(), "reliability": r,
        "resource_samples": {profile: data.get(profile) for profile in PROFILES},
        "resource_comparison": differences,
        "comparison_quality": ("sampled-process-names-only; same-machine-and-idle-unverified"
                               if len(data) == 3 else "incomplete"),
        "manual_evidence_pending": [
            "Physical cold greeter-to-first-usable-panel timing (3 runs each profile)",
            "Check XFCE fallback after native failure and normal log out",
            "Lock-before-suspend, lock-guard crash, resume and lid closure",
            "Monitor mode rollback, scale, hotplug and compositor restart",
            "Keyboard, accessibility, portals, DBus loss and app launch",
            "Same-hardware, same-workload idle sampling after settling",
            "Upgrade, downgrade and purge preserve user recipes, backups and XFCE",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for profile in PROFILES:
        parser.add_argument(f"--{profile}-sample", type=Path,
                            help=f"Absolute JSON produced in the real {profile} session")
    args = parser.parse_args(argv)
    try:
        samples = {}
        for profile in PROFILES:
            source = getattr(args, f"{profile}_sample")
            if source is not None:
                samples[profile] = load_sample(source, profile=profile)
        report = create_report(samples)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
