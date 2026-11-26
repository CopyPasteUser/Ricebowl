#!/usr/bin/env python3
"""Sampler and summariser for scripts/soak_riceplate_resources.sh (SG7 WP7.2).

  soak_resource_sampler.py sample --root-pid PID --out CSV --phase-file FILE
                                  --stop-file FILE [--interval 10]
      Every INTERVAL seconds append one CSV row per tracked process in the
      process tree below PID: PSS (/proc/PID/smaps_rollup), RSS, utime+stime
      ticks, thread and fd counts. Own-user /proc only, read-only, no daemon.
  soak_resource_sampler.py summary --csv CSV [--warmup 60] [--json OUT]
      Per tracked process: start / settled / end PSS, least-squares and
      Theil-Sen slope per hour after warm-up, the same for the late half and for
      the interaction window, idle and interaction CPU %, restarts. Prints a table.

This is a *headless local* measurement tool. It does not read hardware power,
GPU or display counters and its numbers are not a hardware benchmark.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# comm (15 chars max) -> reported role. Everything else in the tree (the test
# clients, shells, sleep, the SNI fixture) is deliberately not measured.
TRACKED = {
    "riceplate-nativ": "riceplate-native",
    "labwc": "labwc",
    "mako": "mako",
    "swaybg": "swaybg",
    "dbus-daemon": "dbus-daemon",
    "at-spi-bus-laun": "at-spi-bus-launcher",
    "at-spi2-registr": "at-spi2-registryd",
}
FIELDS = ("t_s", "phase", "role", "pid", "start_ticks", "pss_kib", "rss_kib",
          "cpu_ticks", "threads", "fds")
IDLE_PHASES = ("idle1", "idle2", "idle")
LEAK_SLOPE_KIB_PER_HOUR = 2048.0  # flag threshold, not a pass/fail contract


class SamplerError(RuntimeError):
    pass


@dataclass(frozen=True)
class Reading:
    role: str
    pid: int
    start_ticks: int
    pss_kib: int
    rss_kib: int
    cpu_ticks: int
    threads: int
    fds: int


def parse_stat(raw: str) -> tuple[int, int, int, int]:
    """(ppid, cpu_ticks, threads, start_ticks) of /proc/PID/stat, comm-safe."""
    _, marker, suffix = raw.rpartition(") ")
    fields = suffix.split()
    if not marker or len(fields) < 20 or fields[0] not in "RSDTZIXtWKP":
        raise SamplerError("unparseable /proc stat")
    try:
        ppid, user, system, threads, start = (
            int(fields[i]) for i in (1, 11, 12, 17, 19))
    except ValueError as exc:
        raise SamplerError("non-numeric /proc stat field") from exc
    if min(ppid, user, system, threads) < 0 or start <= 0:
        raise SamplerError("invalid /proc stat counters")
    return ppid, user + system, threads, start


def parse_rollup(raw: str) -> tuple[int, int]:
    """(pss_kib, rss_kib) from smaps_rollup; each counter must appear once."""
    values = {}
    for label in ("Pss", "Rss"):
        found = re.findall(rf"(?m)^{label}:\s+([0-9]+) kB\s*$", raw)
        if len(found) != 1:
            raise SamplerError(f"missing or ambiguous {label}")
        values[label] = int(found[0])
    return values["Pss"], values["Rss"]


def _read(path: Path) -> str:
    with open(path, encoding="utf-8", errors="replace") as stream:
        return stream.read()


def descendants(root: int, proc: Path = Path("/proc")) -> list[int]:
    """root plus every process below it (live scan; races are tolerated)."""
    children: dict[int, list[int]] = {}
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            ppid = parse_stat(_read(entry / "stat"))[0]
        except (OSError, SamplerError):
            continue
        children.setdefault(ppid, []).append(int(entry.name))
    found, queue = [], [root]
    while queue:
        pid = queue.pop()
        found.append(pid)
        queue.extend(children.get(pid, ()))
    return found


def read_process(pid: int, proc: Path = Path("/proc")) -> Reading | None:
    base = proc / str(pid)
    try:
        comm = _read(base / "comm").strip()
        role = TRACKED.get(comm)
        if role is None:
            return None
        _, cpu, threads, start = parse_stat(_read(base / "stat"))
        pss, rss = parse_rollup(_read(base / "smaps_rollup"))
        fds = len(os.listdir(base / "fd"))
    except (OSError, SamplerError):
        return None  # exited between the scan and the read
    return Reading(role, pid, start, pss, rss, cpu, threads, fds)


def snapshot(root: int, proc: Path = Path("/proc")) -> list[Reading]:
    own = os.getpid()
    rows = []
    for pid in descendants(root, proc):
        if pid == own:
            continue
        reading = read_process(pid, proc)
        if reading is not None:
            rows.append(reading)
    return sorted(rows, key=lambda r: (r.role, r.pid))


def run_sampler(options) -> int:
    started = time.monotonic()
    phase_file, stop_file = Path(options.phase_file), Path(options.stop_file)
    out = Path(options.out)
    new = not out.exists()
    with open(out, "a", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        if new:
            writer.writerow(FIELDS)
        while True:
            stopping = stop_file.exists()
            now = time.monotonic() - started
            try:
                phase = phase_file.read_text(encoding="utf-8").strip() or "unknown"
            except OSError:
                phase = "unknown"
            for r in snapshot(options.root_pid):
                writer.writerow((f"{now:.1f}", phase, r.role, r.pid, r.start_ticks,
                                 r.pss_kib, r.rss_kib, r.cpu_ticks, r.threads, r.fds))
            stream.flush()
            if stopping:  # one final sample is written after the stop request
                return 0
            time.sleep(max(0.0, options.interval - ((time.monotonic() - started) % options.interval)))


# --------------------------------------------------------------------------
# summary maths (pure, unit-tested)
# --------------------------------------------------------------------------
def least_squares_slope(points: list[tuple[float, float]]) -> float | None:
    """Slope of y over x (y units per x unit); None without two distinct x."""
    if len(points) < 2:
        return None
    mean_x = sum(x for x, _ in points) / len(points)
    mean_y = sum(y for _, y in points) / len(points)
    denominator = sum((x - mean_x) ** 2 for x, _ in points)
    if denominator == 0:
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in points) / denominator


def theil_sen_slope(points: list[tuple[float, float]]) -> float | None:
    """Median pairwise slope: robust against single GC/allocator spikes."""
    slopes = [(b[1] - a[1]) / (b[0] - a[0])
              for index, a in enumerate(points) for b in points[index + 1:]
              if b[0] != a[0]]
    return statistics.median(slopes) if slopes else None


def cpu_percent(samples: list[dict], phases: tuple[str, ...], clk_tck: int) -> float | None:
    """CPU % of one process over consecutive same-process sample pairs that
    both lie in `phases`. None when there is no such interval."""
    ticks = seconds = 0.0
    for earlier, later in zip(samples, samples[1:]):
        if earlier["phase"] not in phases or later["phase"] not in phases:
            continue
        step = later["t_s"] - earlier["t_s"]
        delta = later["cpu_ticks"] - earlier["cpu_ticks"]
        if step <= 0 or delta < 0:
            continue
        ticks += delta
        seconds += step
    return None if seconds == 0 else 100.0 * (ticks / clk_tck) / seconds


def load_rows(path: Path) -> list[dict]:
    rows = []
    with open(path, newline="", encoding="utf-8") as stream:
        for raw in csv.DictReader(stream):
            try:
                rows.append({
                    "t_s": float(raw["t_s"]), "phase": raw["phase"], "role": raw["role"],
                    "pid": int(raw["pid"]), "start_ticks": int(raw["start_ticks"]),
                    "pss_kib": int(raw["pss_kib"]), "rss_kib": int(raw["rss_kib"]),
                    "cpu_ticks": int(raw["cpu_ticks"]), "threads": int(raw["threads"]),
                    "fds": int(raw["fds"])})
            except (KeyError, ValueError) as exc:
                raise SamplerError(f"malformed CSV row: {raw!r}") from exc
    return rows


def summarize(rows: list[dict], *, clk_tck: int, warmup_s: float = 60.0,
              leak_threshold: float = LEAK_SLOPE_KIB_PER_HOUR) -> dict:
    """Per role summary. A role with several identities (restart) is reported
    for its LAST identity, with `identities` > 1 as the restart count + 1."""
    result: dict[str, dict] = {}
    for role in sorted({r["role"] for r in rows}):
        mine = [r for r in rows if r["role"] == role]
        identities = sorted({(r["pid"], r["start_ticks"]) for r in mine})
        latest = max(identities, key=lambda ident: min(
            r["t_s"] for r in mine if (r["pid"], r["start_ticks"]) == ident))
        series = [r for r in mine if (r["pid"], r["start_ticks"]) == latest]
        series.sort(key=lambda r: r["t_s"])
        after = [r for r in series if r["t_s"] >= warmup_s]
        interact = [r for r in after if r["phase"] == "interact"]
        window = [r for r in after if warmup_s <= r["t_s"] < 2 * warmup_s]

        def kib_per_hour(points, fit):
            slope = fit([(r["t_s"], float(r["pss_kib"])) for r in points])
            return None if slope is None else slope * 3600.0

        start = series[0]["pss_kib"]
        settled = (statistics.median(r["pss_kib"] for r in window) if window
                   else (after[0]["pss_kib"] if after else start))
        tail = series[-3:]
        end = statistics.median(r["pss_kib"] for r in tail)
        ls = kib_per_hour(after, least_squares_slope)
        sen = kib_per_hour(after, theil_sen_slope)
        # A one-time cache fill (first menu, first popup) levels off; a leak
        # keeps growing. The late half of the post-warm-up samples separates them.
        late_from = after[0]["t_s"] + (after[-1]["t_s"] - after[0]["t_s"]) / 2 if after else 0
        late = [r for r in after if r["t_s"] >= late_from]
        late_sen = kib_per_hour(late, theil_sen_slope) if len(late) >= 4 else None
        entry = {
            "samples": len(series),
            "span_s": round(series[-1]["t_s"] - series[0]["t_s"], 1),
            "identities": len(identities),
            "pss_start_kib": start,
            "pss_settled_kib": settled,
            "pss_end_kib": end,
            "pss_max_kib": max(r["pss_kib"] for r in series),
            "slope_kib_per_hour_ls": None if ls is None else round(ls, 1),
            "slope_kib_per_hour_theil_sen": None if sen is None else round(sen, 1),
            "slope_late_kib_per_hour_theil_sen": None if late_sen is None else round(late_sen, 1),
            "slope_interact_kib_per_hour_theil_sen": (
                None if (v := kib_per_hour(interact, theil_sen_slope)) is None else round(v, 1)),
            "cpu_idle_percent": cpu_percent(series, IDLE_PHASES, clk_tck),
            "cpu_interact_percent": cpu_percent(series, ("interact",), clk_tck),
            "threads_start": series[0]["threads"], "threads_end": series[-1]["threads"],
            "fds_start": series[0]["fds"], "fds_end": series[-1]["fds"],
        }
        for key in ("cpu_idle_percent", "cpu_interact_percent"):
            if entry[key] is not None:
                entry[key] = round(entry[key], 3)
        # A growth flag needs every estimator above the threshold (whole run,
        # robust whole run, and the late half) plus real growth between settled
        # and end, so a noisy estimator or a one-time cache fill cannot flag.
        entry["growth_flag"] = bool(
            ls is not None and sen is not None and late_sen is not None
            and ls > leak_threshold and sen > leak_threshold and late_sen > leak_threshold
            and entry["pss_end_kib"] - settled > 256)
        result[role] = entry
    return result


def format_table(summary: dict) -> str:
    def cell(value, spec="{}"):
        return "-" if value is None else spec.format(value)

    lines = [f"{'process':<22}{'start':>9}{'settled':>9}{'end':>9}{'max':>9}"
             f"{'KiB/h LS':>10}{'KiB/h TS':>10}{'TS late':>10}"
             f"{'idle %':>9}{'act %':>9}{'thr':>5}{'fds':>5}  flag"]
    for role, e in summary.items():
        lines.append(
            f"{role:<22}{e['pss_start_kib']:>9}{e['pss_settled_kib']:>9.0f}"
            f"{e['pss_end_kib']:>9.0f}{e['pss_max_kib']:>9}"
            f"{cell(e['slope_kib_per_hour_ls'], '{:.0f}'):>10}"
            f"{cell(e['slope_kib_per_hour_theil_sen'], '{:.0f}'):>10}"
            f"{cell(e['slope_late_kib_per_hour_theil_sen'], '{:.0f}'):>10}"
            f"{cell(e['cpu_idle_percent'], '{:.3f}'):>9}"
            f"{cell(e['cpu_interact_percent'], '{:.3f}'):>9}"
            f"{e['threads_end']:>5}{e['fds_end']:>5}  "
            + ("GROWTH" if e["growth_flag"] else "ok")
            + (f" (restarted x{e['identities'] - 1})" if e["identities"] > 1 else ""))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sample = sub.add_parser("sample")
    sample.add_argument("--root-pid", type=int, required=True)
    sample.add_argument("--out", required=True)
    sample.add_argument("--phase-file", required=True)
    sample.add_argument("--stop-file", required=True)
    sample.add_argument("--interval", type=float, default=10.0)
    summary = sub.add_parser("summary")
    summary.add_argument("--csv", required=True, type=Path)
    summary.add_argument("--warmup", type=float, default=60.0)
    summary.add_argument("--json", type=Path)
    summary.add_argument("--leak-threshold", type=float, default=LEAK_SLOPE_KIB_PER_HOUR)
    options = parser.parse_args(argv)
    if options.command == "sample":
        if options.interval < 1:
            parser.error("--interval must be at least 1 second")
        return run_sampler(options)
    rows = load_rows(options.csv)
    if not rows:
        print("FAIL: no samples", file=sys.stderr)
        return 1
    result = summarize(rows, clk_tck=os.sysconf("SC_CLK_TCK"), warmup_s=options.warmup,
                       leak_threshold=options.leak_threshold)
    print(format_table(result))
    if options.json:
        options.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                                encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
