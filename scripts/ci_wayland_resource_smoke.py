#!/usr/bin/env python3
"""CI-only, one-shot native Wayland process growth check (no daemon or host writes).

The caller owns a private headless compositor. Live rice switching intentionally
replaces RicePlate, so compare the newly started *single* panel's footprint
against a baseline of the same rice. This is not a cumulative leak test.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path


class ResourceSmokeError(RuntimeError):
    """The CI-only process or its accounting could not be trusted."""


@dataclass(frozen=True)
class Sample:
    pid: int
    start_ticks: int
    pss_kib: int
    rss_kib: int
    fds: int
    threads: int


def _numeric(source: str, label: str) -> int:
    matches = re.findall(rf"(?m)^{re.escape(label)}:\s*([0-9]+)(?:\s+kB)?\s*$", source)
    if len(matches) != 1:
        raise ResourceSmokeError(f"Unavailable or ambiguous {label} counter")
    return int(matches[0])


def _start_ticks(raw: str) -> int:
    # The executable name in /proc/PID/stat may contain spaces or ')' chars.
    # Field 22 (starttime) is index 19 after the closing process-name ')'.
    _, marker, suffix = raw.rpartition(") ")
    fields = suffix.split()
    if not marker or len(fields) < 20 or not fields[0] in ("R", "S", "D", "T", "Z", "I"):
        raise ResourceSmokeError("Invalid native process identity")
    try:
        ticks = int(fields[19])
    except ValueError as exc:
        raise ResourceSmokeError("Invalid native process start time") from exc
    if ticks <= 0:
        raise ResourceSmokeError("Invalid native process start time")
    return ticks


def _cpu_and_identity(raw: str) -> tuple[int, int, str]:
    """Parse Linux /proc/<pid>/stat without trusting a ')' inside comm.

    Field indices are relative to the state field (3): utime=14, stime=15,
    starttime=22. The executable PID/start-time identity prevents PID reuse.
    """
    _, marker, suffix = raw.rpartition(") ")
    fields = suffix.split()
    if not marker or len(fields) < 20 or fields[0] not in (
            "R", "S", "D", "T", "Z", "I"):
        raise ResourceSmokeError("Invalid process CPU/stat counter")
    try:
        user, system, start = (int(fields[i]) for i in (11, 12, 19))
    except ValueError as exc:
        raise ResourceSmokeError("Malformed process CPU/stat tick") from exc
    if min(user, system) < 0 or start <= 0:
        raise ResourceSmokeError("Invalid process CPU/stat tick")
    return user + system, start, fields[0]


def _old_process_alive(previous: Sample, *, proc_root: Path = Path("/proc")) -> bool:
    """Distinguish a still-running old panel from a re-used numeric PID."""
    try:
        raw = (proc_root / str(previous.pid) / "stat").read_text(encoding="ascii")
    except FileNotFoundError:
        return False
    except (OSError, UnicodeError) as exc:
        raise ResourceSmokeError("Cannot inspect prior native process") from exc
    _, start, _ = _cpu_and_identity(raw)
    return start == previous.start_ticks


def assert_old_process_gone(previous: Sample, *, proc_root: Path = Path("/proc"),
                            timeout: float = 2.0) -> None:
    """The compositor may replace its panel before the supervisor reaps it."""
    if not 0 <= timeout <= 10:
        raise ResourceSmokeError("Invalid private process cleanup timeout")
    deadline = time.monotonic() + timeout
    while _old_process_alive(previous, proc_root=proc_root):
        if time.monotonic() >= deadline:
            raise ResourceSmokeError("Previous native panel still exists after switch")
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))


def sample_cpu(binary: Path, runtime: Path, *, interval: float = 0.5,
               proc_root: Path = Path("/proc"), uid: int | None = None) -> dict:
    """Measure actual /proc CPU time for one settled native Wayland process."""
    if not 0.2 <= interval <= 5.0:
        raise ResourceSmokeError("Invalid bounded CPU sample interval")
    before = sample_native(binary, runtime, proc_root=proc_root, uid=uid)
    cpu_before, start_before, _ = _cpu_and_identity(
        (proc_root / str(before.pid) / "stat").read_text(encoding="ascii"))
    if start_before != before.start_ticks:
        raise ResourceSmokeError("CPU identity changed during initial sample")
    start_ns = time.monotonic_ns()
    time.sleep(interval)
    end_ns = time.monotonic_ns()
    after = sample_native(binary, runtime, proc_root=proc_root, uid=uid)
    cpu_after, start_after, _ = _cpu_and_identity(
        (proc_root / str(after.pid) / "stat").read_text(encoding="ascii"))
    if (before.pid, before.start_ticks) != (after.pid, after.start_ticks) \
            or start_after != after.start_ticks or cpu_after < cpu_before \
            or end_ns <= start_ns:
        raise ResourceSmokeError("Process restarted or CPU counters regressed during sample")
    hertz = os.sysconf("SC_CLK_TCK")
    if type(hertz) is not int or hertz <= 0:
        raise ResourceSmokeError("Invalid Linux CPU accounting frequency")
    delta = cpu_after - cpu_before
    percent = round(100.0 * delta * 1_000_000_000 / (hertz * (end_ns - start_ns)), 3)
    return {
        "pid": after.pid, "start_ticks": after.start_ticks,
        "cpu_delta_ticks": delta, "clock_ticks_per_second": hertz,
        "elapsed_ns": end_ns - start_ns, "cpu_core_percent": percent,
        "pss_kib": after.pss_kib, "rss_kib": after.rss_kib,
        "fds": after.fds, "threads": after.threads,
        "software_ci_only": True, "hardware_accepted": False,
    }


def _belongs_to_runtime(path: Path, runtime: Path) -> bool:
    try:
        with (path / "environ").open("rb") as stream:
            data = stream.read(65537)
        if len(data) > 65536:
            raise ResourceSmokeError("Native process environment exceeded CI bound")
        fields = [entry for entry in data.split(b"\0") if entry.startswith(b"XDG_RUNTIME_DIR=")]
        return fields == [b"XDG_RUNTIME_DIR=" + os.fsencode(runtime)]
    except (OSError, ValueError):
        return False


def sample_native(binary: Path, runtime: Path, *, proc_root: Path = Path("/proc"),
                  uid: int | None = None) -> Sample:
    if not binary.is_absolute() or not runtime.is_absolute():
        raise ResourceSmokeError("CI binary/runtime must be absolute paths")
    owner = os.geteuid() if uid is None else uid
    matches = []
    try:
        entries = list(proc_root.iterdir())
    except OSError as exc:
        raise ResourceSmokeError("Linux proc inventory unavailable") from exc
    expected_binary = binary.resolve(strict=True)
    for entry in entries:
        if not entry.name.isdecimal():
            continue
        try:
            if entry.stat().st_uid != owner:
                continue
            if (entry / "exe").resolve(strict=True) != expected_binary:
                continue
            if not _belongs_to_runtime(entry, runtime):
                continue
            matches.append(entry)
        except (OSError, RuntimeError, ValueError):
            continue  # A vanishing/nonowned process cannot be a trusted match.
    if len(matches) != 1:
        raise ResourceSmokeError("Expected exactly one private native RicePlate process")
    path = matches[0]
    try:
        before = _start_ticks((path / "stat").read_text(encoding="ascii"))
        status = (path / "status").read_text(encoding="ascii")
        rollup = (path / "smaps_rollup").read_text(encoding="ascii")
        with os.scandir(path / "fd") as descriptors:
            fds = sum(1 for _ in descriptors)
        after = _start_ticks((path / "stat").read_text(encoding="ascii"))
    except (OSError, UnicodeError) as exc:
        raise ResourceSmokeError("Native process counters unavailable") from exc
    if before != after or fds < 0:
        raise ResourceSmokeError("Native process changed during counter capture")
    return Sample(int(path.name), before, _numeric(rollup, "Pss"),
                  _numeric(status, "VmRSS"), fds, _numeric(status, "Threads"))


# Deliberately generous thresholds for a single-run, allocator-sensitive smoke.
# Hardware performance acceptance remains independent of this check.
LIMITS = {"pss_kib": 32768, "rss_kib": 32768, "fds": 24, "threads": 4}


def compare(before: Sample, after: Sample, *, expect_replaced: bool = False
            ) -> dict[str, object]:
    same_process = (before.pid, before.start_ticks) == (after.pid, after.start_ticks)
    if expect_replaced and same_process:
        raise ResourceSmokeError("Rice live-switch failed to replace native panel")
    if not expect_replaced and not same_process:
        raise ResourceSmokeError("Native panel restarted; cannot compare resource growth")
    growth = {key: getattr(after, key) - getattr(before, key) for key in LIMITS}
    excess = [key for key, value in growth.items() if value > LIMITS[key]]
    if excess:
        raise ResourceSmokeError("Native process growth exceeds CI smoke limits: "
                                 + ", ".join(excess))
    return {"ok": True, "hardware_accepted": False,
            "same_process": same_process,
            "expected_process_replacement": expect_replaced,
            "baseline": asdict(before),
            "after": asdict(after), "growth": growth, "limits": LIMITS}


def _write_private(path: Path, data: dict[str, int]) -> None:
    folder = path.parent
    try:
        info = folder.stat()
        if not (stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
                and not info.st_mode & 0o077):
            raise ResourceSmokeError("CI snapshot directory is not owner-private")
        fd, temp = tempfile.mkstemp(prefix=".riceplate-resource-", dir=folder)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    except OSError as exc:
        raise ResourceSmokeError("Could not publish private CI baseline") from exc


def _read_baseline(path: Path) -> Sample:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_size > 4096:
                raise ResourceSmokeError("Unsafe native resource baseline")
            data = json.loads(stream.read(4097))
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        raise ResourceSmokeError("Invalid native resource baseline") from exc
    if (type(data) is not dict or set(data) != set(Sample.__dataclass_fields__)
            or any(type(value) is not int or value < 0 for value in data.values())):
        raise ResourceSmokeError("Invalid native resource baseline")
    return Sample(**data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("capture", "compare", "compare-replaced", "assert-gone", "cpu-sample"))
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.mode == "cpu-sample":
            print(json.dumps(sample_cpu(args.binary, args.runtime), sort_keys=True))
            return 0
        if args.mode == "assert-gone":
            old = _read_baseline(args.baseline)
            assert_old_process_gone(old)
            current = sample_native(args.binary, args.runtime)
            if (current.pid, current.start_ticks) == (old.pid, old.start_ticks):
                raise ResourceSmokeError("Native panel was not replaced")
            print("Prior private RicePlate process reaped before new panel acceptance")
            return 0
        now = sample_native(args.binary, args.runtime)
        if args.mode == "capture":
            _write_private(args.baseline, asdict(now))
            print("Private RicePlate resource baseline captured")
        else:
            result = compare(_read_baseline(args.baseline), now,
                             expect_replaced=args.mode == "compare-replaced")
            print(json.dumps(result, sort_keys=True))
    except (ResourceSmokeError, OSError) as exc:
        print(f"RicePlate resource smoke failed: {exc}", file=__import__("sys").stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
