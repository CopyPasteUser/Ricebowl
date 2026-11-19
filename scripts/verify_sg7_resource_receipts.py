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
import sys
from pathlib import Path

if __package__:
    from .ci_wayland_resource_smoke import LIMITS, Sample
else:
    from ci_wayland_resource_smoke import LIMITS, Sample

CYCLES = 3
FIELDS = frozenset(Sample.__dataclass_fields__)
COUNTERS = frozenset(LIMITS)
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
        data = path.read_bytes()
        if not 0 < len(data) <= 8192:
            raise EvidenceError(f"Empty or oversized resource receipt: {path.name}")
        obj = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise EvidenceError(f"Malformed resource receipt: {path.name}") from exc
    if type(obj) is not dict or set(obj) != RECEIPT_FIELDS:
        raise EvidenceError(f"Unexpected resource receipt schema: {path.name}")
    return obj, hashlib.sha256(data).hexdigest()


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
        maxima = {key: growth[key] if maxima[key] is None
                  else max(maxima[key], growth[key]) for key in LIMITS}
        last = row
    legacy, legacy_digest = _read(directory / "resource-growth.json")
    if legacy != last:
        raise EvidenceError("Final resource receipt differs from cycle three")
    digests["resource-growth.json"] = legacy_digest
    return {
        "schema_version": 1,
        "source_commit": source_commit,
        "software_ci_only": True,
        "hardware_accepted": False,
        "real_labwc_cycles": CYCLES,
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
        # Never overwrite or follow a pre-existing proof file.
        with target.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except (EvidenceError, OSError) as exc:
        print(f"SG7 resource evidence: BLOCKED — {exc}", file=sys.stderr)
        return 1
    print(f"Verified {CYCLES} real labwc switch receipts for {args.source_commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
