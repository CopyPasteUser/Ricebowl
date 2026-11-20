"""Independent, negative-heavy verification for SG7 real labwc resource evidence."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.verify_sg7_resource_receipts import EvidenceError, main, verify

SHA = "a" * 40
BASELINE = {
    "pid": 101, "start_ticks": 1001, "pss_kib": 24000,
    "rss_kib": 36000, "fds": 8, "threads": 2,
}
LIMITS = {"pss_kib": 32768, "rss_kib": 32768, "fds": 24, "threads": 4}


class SG7ResourceReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sg7-resource-")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        for cycle in (1, 2, 3):
            after = {
                **BASELINE, "pid": 101 + cycle, "start_ticks": 1001 + cycle,
                "pss_kib": 24000 + cycle * 100,
                "rss_kib": 36000 + cycle * 80,
                "fds": 8 + cycle, "threads": 2,
            }
            growth = {key: after[key] - BASELINE[key] for key in LIMITS}
            row = {
                "ok": True, "hardware_accepted": False,
                "same_process": False, "expected_process_replacement": True,
                "baseline": BASELINE, "after": after, "growth": growth,
                "limits": LIMITS,
            }
            self.write(cycle, row)
            self.write_cpu(cycle, after)
        (self.folder / "resource-growth.json").write_bytes(self.path(3).read_bytes())

    def path(self, cycle):
        return self.folder / f"resource-growth-cycle-{cycle}.json"

    def read(self, cycle):
        return json.loads(self.path(cycle).read_text())

    def write(self, cycle, row):
        self.path(cycle).write_text(json.dumps(row, sort_keys=True) + "\n")

    def cpu_path(self, cycle):
        return self.folder / f"resource-cpu-cycle-{cycle}.json"

    def write_cpu(self, cycle, after):
        # Synthetic unit fixture only; the CI script records real /proc time.
        tick_delta = cycle * 2
        self.cpu_path(cycle).write_text(json.dumps({
            "pid": after["pid"], "start_ticks": after["start_ticks"],
            "cpu_delta_ticks": tick_delta,
            "clock_ticks_per_second": 100, "elapsed_ns": 500_000_000,
            "cpu_core_percent": float(4 * cycle),
            "pss_kib": after["pss_kib"], "rss_kib": after["rss_kib"],
            "fds": after["fds"], "threads": after["threads"],
            "software_ci_only": True, "hardware_accepted": False,
        }) + "\n")

    def test_three_real_cycle_receipts_generate_source_bound_manifest(self):
        result = verify(self.folder, SHA)
        self.assertEqual(result["source_commit"], SHA)
        self.assertEqual(result["real_labwc_cycles"], 3)
        self.assertEqual(result["max_observed_growth"]["pss_kib"], 300)
        self.assertEqual(result["max_observed_growth"]["fds"], 3)
        self.assertFalse(result["hardware_accepted"])
        self.assertTrue(result["software_ci_only"])
        self.assertEqual(len(result["receipt_sha256"]), 7)
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["cpu_observed_cycles"], 3)
        self.assertEqual(result["max_cpu_core_percent"], 12.0)
        self.assertEqual(main(["--directory", str(self.folder), "--source-commit", SHA]), 0)
        manifest = json.loads((self.folder / "sg7-resource-acceptance.json").read_text())
        self.assertEqual(manifest, result)
        # Re-runs may not silently overwrite an earlier evidence receipt.
        self.assertEqual(main(["--directory", str(self.folder), "--source-commit", SHA]), 1)

    def test_missing_and_symlinked_receipts_are_not_trusted(self):
        self.path(2).unlink()
        with self.assertRaisesRegex(EvidenceError, "Missing"):
            verify(self.folder, SHA)
        self.path(2).symlink_to(self.path(3))
        with self.assertRaisesRegex(EvidenceError, "symlinked"):
            verify(self.folder, SHA)

    def test_reject_forged_or_invalid_source_and_final_copy(self):
        with self.assertRaisesRegex(EvidenceError, "source SHA"):
            verify(self.folder, "not-a-commit")
        (self.folder / "resource-growth.json").write_text("{}")
        with self.assertRaises(EvidenceError):
            verify(self.folder, SHA)

    def test_reject_counter_and_process_identity_forgery(self):
        base = self.read(2)
        cases = (
            ("fake hardware acceptance", lambda r: r.update(hardware_accepted=True)),
            ("missing process switch", lambda r: r.update(same_process=True)),
            ("fake ok flag", lambda r: r.update(ok=False)),
            ("invented growth", lambda r: r["growth"].update(pss_kib=0)),
            ("excess footprint", lambda r: (r["after"].update(pss_kib=68000),
                                           r["growth"].update(pss_kib=44000))),
            ("untrusted limits", lambda r: r["limits"].update(pss_kib=999999)),
            ("integer bool spoof", lambda r: r["growth"].update(fds=True)),
            ("baseline change", lambda r: r["baseline"].update(rss_kib=36001)),
            ("reused PID/start", lambda r: r["after"].update(pid=102, start_ticks=1002)),
        )
        for label, mutate in cases:
            with self.subTest(label=label):
                row = json.loads(json.dumps(base))
                mutate(row)
                self.write(2, row)
                with self.assertRaises(EvidenceError):
                    verify(self.folder, SHA)
        self.write(2, base)

    def test_cpu_receipt_identity_time_and_flag_forgery_fail_closed(self):
        source = json.loads(self.cpu_path(2).read_text())
        cases = (
            ("different process", lambda r: r.update(pid=999)),
            ("start-time PID reuse", lambda r: r.update(start_ticks=9999)),
            ("fake CPU", lambda r: r.update(cpu_core_percent=0.0)),
            ("negative ticks", lambda r: r.update(cpu_delta_ticks=-1)),
            ("boolean clock", lambda r: r.update(clock_ticks_per_second=True)),
            ("tiny sampling window", lambda r: r.update(elapsed_ns=1)),
            ("hardware claim", lambda r: r.update(hardware_accepted=True)),
            ("nonfinite CPU", lambda r: r.update(cpu_core_percent=float('nan'))),
            ("extra field", lambda r: r.update(fake='unknown')),
        )
        for label, mutate in cases:
            with self.subTest(label=label):
                row = json.loads(json.dumps(source))
                mutate(row)
                self.cpu_path(2).write_text(json.dumps(row))
                with self.assertRaises(EvidenceError):
                    verify(self.folder, SHA)
        self.cpu_path(2).write_text(json.dumps(source))
        self.cpu_path(2).unlink()
        with self.assertRaisesRegex(EvidenceError, "Missing"):
            verify(self.folder, SHA)
        self.cpu_path(2).symlink_to(self.cpu_path(3))
        with self.assertRaisesRegex(EvidenceError, "symlinked"):
            verify(self.folder, SHA)

    def test_reject_duplicate_fields_and_oversized_receipts(self):
        self.path(1).write_text('{"ok": true, "ok": false}')
        with self.assertRaisesRegex(EvidenceError, "Malformed resource receipt"):
            verify(self.folder, SHA)
        self.path(1).write_bytes(b"x" * 8193)
        with self.assertRaisesRegex(EvidenceError, "Malformed resource receipt"):
            verify(self.folder, SHA)


if __name__ == "__main__":
    unittest.main()
