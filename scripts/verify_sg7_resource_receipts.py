#!/usr/bin/env python3
"""Verify native labwc resource receipts and bind them to the CI source SHA.

This is independent post-processing of real compositor smoke output, not a
synthetic benchmark, production monitor, or physical hardware sign-off.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import math
import sys
from pathlib import Path

if __package__:
    from .ci_wayland_resource_smoke import LIMITS, Sample
    from .sg7_safe_receipt_io import read_regular_bytes
    from .sg7_dossier_io import DossierWriteError, publish_dossier
else:
    from ci_wayland_resource_smoke import LIMITS, Sample
    from sg7_safe_receipt_io import read_regular_bytes
    from sg7_dossier_io import DossierWriteError, publish_dossier

CYCLES = 3
FIELDS = frozenset(Sample.__dataclass_fields__)
COUNTERS = frozenset(LIMITS)
CPU_FIELDS = frozenset({
    'pid', 'start_ticks', 'cpu_delta_ticks', 'clock_ticks_per_second',
    'elapsed_ns', 'cpu_core_percent', 'pss_kib', 'rss_kib', 'fds', 'threads',
    'software_ci_only', 'hardware_accepted',
})
RECEIPT_FIELDS = frozenset({
    "ok", "hardware_accepted", "same_process",
    "expected_process_replacement", "baseline", "after", "growth", "limits",
})


class EvidenceError(ValueError):
    """Missing, malformed or misleading compositor resource evidence."""


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError(f"Duplicate resource evidence key: {key}")
        result[key] = value
    return result


def _read(path: Path) -> tuple[dict, str]:
    if path.is_symlink() or not path.is_file():
        raise EvidenceError(f"Missing or symlinked resource receipt: {path.name}")
    try:
        data = read_regular_bytes(path, limit=8192)
        if not 0 < len(data) <= 8192:
            raise EvidenceError(f"Empty or oversized resource receipt: {path.name}")
        obj = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise EvidenceError(f"Malformed resource receipt: {path.name}") from exc
    if type(obj) is not dict or set(obj) != RECEIPT_FIELDS:
        raise EvidenceError(f"Unexpected resource receipt schema: {path.name}")
    return obj, hashlib.sha256(data).hexdigest()


def _cpu_receipt(path: Path, baseline: dict, after: dict, cycle: int) -> tuple[float, str, dict[str, int]]:
    if path.is_symlink() or not path.is_file():
        raise EvidenceError(f"Missing or symlinked CPU receipt: cycle {cycle}")
    try:
        data = read_regular_bytes(path, limit=4096)
        if not 0 < len(data) <= 4096:
            raise EvidenceError(f"Oversized CPU receipt: cycle {cycle}")
        row = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise EvidenceError(f"Malformed CPU receipt: cycle {cycle}") from exc
    if (type(row) is not dict or set(row) != CPU_FIELDS
            or row['software_ci_only'] is not True
            or row['hardware_accepted'] is not False):
        raise EvidenceError(f"Untrusted CPU receipt schema: cycle {cycle}")
    integer_keys = CPU_FIELDS - frozenset({
        'cpu_core_percent', 'software_ci_only', 'hardware_accepted'})
    if any(type(row[k]) is not int or row[k] < 0 for k in integer_keys):
        raise EvidenceError(f"Invalid CPU counter: cycle {cycle}")
    if (row['pid'] != after['pid'] or row['start_ticks'] != after['start_ticks']
            or row['clock_ticks_per_second'] <= 0
            or not 200_000_000 <= row['elapsed_ns'] <= 10_000_000_000
            or type(row['cpu_core_percent']) is not float
            or not math.isfinite(row['cpu_core_percent'])
            or row['cpu_core_percent'] < 0):
        raise EvidenceError(f"CPU measurement does not match native cycle {cycle}")
    expected = round(100.0 * row['cpu_delta_ticks'] * 1_000_000_000 /
                     (row['clock_ticks_per_second'] * row['elapsed_ns']), 3)
    if row['cpu_core_percent'] != expected:
        raise EvidenceError(f"CPU report does not match /proc ticks: cycle {cycle}")
    # The settled CPU sample is taken after the immediate switch snapshot.
    # Treat its memory/FD/thread counters as independent growth evidence,
    # not merely decorative metadata that could conceal later regressions.
    cpu_growth = {key: row[key] - baseline[key] for key in LIMITS}
    if any(cpu_growth[key] > LIMITS[key] for key in LIMITS):
        raise EvidenceError(f"CPU sample resource growth exceeds CI limits: cycle {cycle}")
    return row['cpu_core_percent'], hashlib.sha256(data).hexdigest(), cpu_growth


def _sample(value: object, label: str) -> dict[str, int]:
    if type(value) is not dict or set(value) != FIELDS:
        raise EvidenceError(f"Missing resource sample fields: {label}")
    if any(type(v) is not int or v < 0 for v in value.values()):
        raise EvidenceError(f"Invalid resource sample counter: {label}")
    if value["pid"] <= 0 or value["start_ticks"] <= 0:
        raise EvidenceError(f"Invalid process identity: {label}")
    return value


def _check(row: dict, cycle: int) -> tuple[dict, dict, dict]:
    if (row["ok"] is not True or row["hardware_accepted"] is not False
            or row["same_process"] is not False
            or row["expected_process_replacement"] is not True):
        raise EvidenceError(f"Unaccepted or misleading resource comparison: cycle {cycle}")
    baseline = _sample(row["baseline"], f"cycle {cycle} baseline")
    after = _sample(row["after"], f"cycle {cycle} after")
    if ((baseline["pid"], baseline["start_ticks"])
            == (after["pid"], after["start_ticks"])):
        raise EvidenceError(f"Missing native process replacement: cycle {cycle}")
    growth = row["growth"]
    limits = row["limits"]
    if (type(growth) is not dict or set(growth) != COUNTERS
            or any(type(v) is not int for v in growth.values())
            or type(limits) is not dict or set(limits) != COUNTERS
            or any(type(v) is not int for v in limits.values())
            or limits != LIMITS):
        raise EvidenceError(f"Untrusted resource growth or limits: cycle {cycle}")
    for key in LIMITS:
        if growth[key] != after[key] - baseline[key] or growth[key] > LIMITS[key]:
            raise EvidenceError(f"Invalid resource growth {key}: cycle {cycle}")
    return baseline, after, growth


def verify(directory: Path, source_commit: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise EvidenceError("Missing exact 40-character source SHA")
    if directory.is_symlink() or not directory.is_dir():
        raise EvidenceError("Missing native compositor resource evidence directory")
    baseline = None
    last = None
    observed = set()
    digests = {}
    maxima = {key: None for key in LIMITS}
    max_cpu_core_percent = 0.0
    for cycle in range(1, CYCLES + 1):
        label = f"resource-growth-cycle-{cycle}.json"
        row, digest = _read(directory / label)
        before, after, growth = _check(row, cycle)
        if baseline is None:
            baseline = before
        elif before != baseline:
            raise EvidenceError(f"Different resource baseline: cycle {cycle}")
        identity = (after["pid"], after["start_ticks"])
        if identity in observed:
            raise EvidenceError(f"Repeated native process identity: cycle {cycle}")
        observed.add(identity)
        digests[label] = digest
        cpu_label = f"resource-cpu-cycle-{cycle}.json"
        measured_cpu, cpu_digest, cpu_growth = _cpu_receipt(directory / cpu_label, before, after, cycle)
        digests[cpu_label] = cpu_digest
        max_cpu_core_percent = max(max_cpu_core_percent, measured_cpu)
        maxima = {
            key: max(growth[key], cpu_growth[key]) if maxima[key] is None
            else max(maxima[key], growth[key], cpu_growth[key])
            for key in LIMITS
        }
        last = row
    legacy, legacy_digest = _read(directory / "resource-growth.json")
    if legacy != last:
        raise EvidenceError("Final resource receipt differs from cycle three")
    digests["resource-growth.json"] = legacy_digest
    return {
        "schema_version": 2,
        "source_commit": source_commit,
        "software_ci_only": True,
        "hardware_accepted": False,
        "real_labwc_cycles": CYCLES,
        "cpu_observed_cycles": CYCLES,
        "max_cpu_core_percent": max_cpu_core_percent,
        "cpu_is_ci_sample_not_long_run_or_hardware": True,
        "baseline": baseline,
        "max_observed_growth": maxima,
        "limits": dict(LIMITS),
        "receipt_sha256": digests,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args(argv)
    try:
        report = verify(args.directory, args.source_commit)
        target = args.directory / "sg7-resource-acceptance.json"
        # Publication is atomic and exclusive: no partial JSON report on error.
        publish_dossier(target, report)
    except (DossierWriteError, EvidenceError, OSError) as exc:
        print(f"SG7 resource evidence: BLOCKED — {exc}", file=sys.stderr)
        return 1
    print(f"Verified {CYCLES} real labwc switch, CPU and teardown receipts for {args.source_commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
