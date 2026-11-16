#!/usr/bin/env python3
"""Opt-in, privacy-preserving first physical XP Luna Wayland QA evidence.

No session/service/display changes, no sudo, no automatic screenshots or
hardware acceptance. Screenshots are private and only taken with --capture.
Run this from a source checkout inside the native RiceBowl session.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import struct
import subprocess
import zlib
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from macrice.de.acceptance import inspect  # noqa: E402

PROCESS_NAMES = frozenset({
    "labwc", "riceplate-native", "waybar", "mako", "swayidle", "swaylock",
})
MAX_SCREENSHOT = 24 * 1024 * 1024


def process_memory(proc: Path = Path("/proc"), uid: int | None = None) -> dict[str, dict[str, int]]:
    """Snapshot same-user resident helpers; never read argv, env or network."""
    owner = os.getuid() if uid is None else uid
    totals: dict[str, dict[str, int]] = {}
    try:
        children = list(proc.iterdir())
    except OSError:
        return totals
    for child in children:
        if not child.name.isdecimal():
            continue
        try:
            name = (child / "comm").read_text(encoding="utf-8")[:64].strip()
            # Linux TASK_COMM_LEN is 16 including NUL: the native binary's
            # 16-character name appears as "riceplate-nativ" in /proc/comm.
            if name == "riceplate-nativ":
                name = "riceplate-native"
            if name not in PROCESS_NAMES:
                continue
            status = (child / "status").read_text(encoding="ascii")
            user = next(line.split()[1] for line in status.splitlines()
                        if line.startswith("Uid:"))
            if int(user) != owner:
                continue
            memory = (child / "smaps_rollup").read_text(encoding="ascii")
            fields = {}
            for line in memory.splitlines():
                if line.startswith(("Pss:", "Rss:")):
                    key, number, unit = line.split()
                    if unit == "kB":
                        fields[key[:-1].lower() + "_kib"] = int(number)
            if not fields:
                continue
            total = totals.setdefault(name, {"count": 0, "pss_kib": 0, "rss_kib": 0})
            total["count"] += 1
            for key in ("pss_kib", "rss_kib"):
                total[key] += fields.get(key, 0)
        except (OSError, ValueError, StopIteration, UnicodeError):
            continue
    return dict(sorted(totals.items()))


def write_private(path: Path, payload: bytes) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            fd = -1
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def prepare_directory(path: Path) -> Path:
    """Require an existing owner-controlled parent and a new private output."""
    if not path.is_absolute():
        raise ValueError("--output must be an absolute path")
    parent = path.parent
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError("output parent must be an owned, non-writable-by-others directory")
    os.mkdir(path, 0o700)  # Fail if it already exists; never overwrite evidence.
    return path


def validate_png(png: bytes) -> None:
    """Verify the whole bounded PNG container, not merely its magic bytes.

    grim normally emits a small, conventional PNG. A header-only or truncated
    capture must not become a successful QA receipt. Walk all chunks without
    decompressing attacker-controlled image data or allocating extra frames.
    """
    if not (33 <= len(png) <= MAX_SCREENSHOT) or not png.startswith(
        b"\\x89PNG\\r\\n\\x1a\\n"
    ):
        raise RuntimeError("invalid-png")

    offset = 8
    seen_idat = False
    idat_finished = False
    view = memoryview(png)
    while offset < len(png):
        if len(png) - offset < 12:
            raise RuntimeError("invalid-png")
        length = struct.unpack_from(">I", png, offset)[0]
        end = offset + 12 + length
        if end > len(png):
            raise RuntimeError("invalid-png")
        kind = png[offset + 4:offset + 8]
        if not all(65 <= byte <= 90 or 97 <= byte <= 122 for byte in kind):
            raise RuntimeError("invalid-png")
        expected_crc = struct.unpack_from(">I", png, offset + 8 + length)[0]
        actual_crc = zlib.crc32(view[offset + 4:offset + 8 + length])
        if expected_crc != actual_crc:
            raise RuntimeError("invalid-png")

        if offset == 8:
            if kind != b"IHDR" or length != 13:
                raise RuntimeError("invalid-png")
            width, height, depth, color, compression, filtering, interlace = (
                struct.unpack_from(">IIBBBBB", png, offset + 8)
            )
            if not (0 < width <= 32768 and 0 < height <= 32768):
                raise RuntimeError("invalid-dimensions")
            valid_depths = {
                0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8),
                4: (8, 16), 6: (8, 16),
            }
            if (depth not in valid_depths.get(color, ())
                    or compression != 0 or filtering != 0 or interlace not in (0, 1)):
                raise RuntimeError("invalid-png")
        elif kind == b"IHDR":
            raise RuntimeError("invalid-png")
        elif kind == b"IDAT":
            if idat_finished:
                raise RuntimeError("invalid-png")
            seen_idat = True
        elif kind == b"IEND":
            if length != 0 or not seen_idat or end != len(png):
                raise RuntimeError("invalid-png")
            return
        elif seen_idat:
            idat_finished = True
        offset = end
    raise RuntimeError("invalid-png")


def grab_frame(*, run=subprocess.run, binary: str | None = None) -> bytes:
    """Only call after a deliberate --capture in an observed native session."""
    grim = binary if binary is not None else shutil.which("grim")
    if not grim:
        raise RuntimeError("grim-unavailable")
    try:
        result = run([grim, "-"], capture_output=True, timeout=8, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("grim-failed") from exc
    png = result.stdout
    validate_png(png)
    return png


def build_report(*, acceptance=None, resources=None) -> dict[str, object]:
    preflight = inspect() if acceptance is None else acceptance
    usage = process_memory() if resources is None else resources
    return {
        "schema_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "target_rice": "xp-luna-columns (operator must verify visually)",
        "session_preflight": preflight.as_dict(),
        "resource_snapshot": {"scope": "same-UID process memory at one instant",
                              "not_idle_cpu_or_cold_start_measurement": True,
                              "processes": usage},
        "screenshot": {"requested": False, "captured": False},
        "hardware_accepted": False,
        "physical_tests_automatically_passed": False,
    }


def create_bundle(output: Path, *, capture: bool = False, acceptance=None,
                  resources=None, run=subprocess.run) -> dict[str, object]:
    report = build_report(acceptance=acceptance, resources=resources)
    folder = prepare_directory(output)
    if capture:
        report["screenshot"] = {"requested": True, "captured": False}
        if report["session_preflight"]["ready_for_manual_checks"]:
            try:
                image = grab_frame(run=run)
                write_private(folder / "native-frame.png", image)
                report["screenshot"] = {
                    "requested": True, "captured": True, "bytes": len(image),
                    "sha256": hashlib.sha256(image).hexdigest(),
                    "privacy": "private-local-only; inspect before sharing",
                }
            except RuntimeError as exc:
                report["screenshot"] = {"requested": True, "captured": False,
                                        "error": str(exc)}
        else:
            report["screenshot"] = {"requested": True, "captured": False,
                                    "error": "not-a-ready-native-session"}
    write_private(folder / "report.json",
                  (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="New, absolute, private evidence directory; must not exist")
    parser.add_argument("--capture", action="store_true",
                        help="Explicitly capture current screen, which may contain private data")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = create_bundle(args.output, capture=args.capture)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    screenshot = report["screenshot"]
    if args.json:
        print(json.dumps({
            "ready_for_manual_checks": report["session_preflight"]["ready_for_manual_checks"],
            "screenshot_captured": screenshot["captured"],
            "hardware_accepted": False,
            "manual_check_count": len(report["session_preflight"]["manual_checks"]),
        }))
    else:
        print("Private evidence written. Hardware approval: NO.")
        print(f"Session ready for manual checks: {report['session_preflight']['ready_for_manual_checks']}")
        print(f"Screenshot captured by explicit request: {screenshot['captured']}")
    return 0 if not args.capture or screenshot["captured"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
