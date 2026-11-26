"""SG7 WP7.2: the soak sampler/summary maths and the soak script contract.

The 10-minute soak itself needs a compositor (scripts/soak_riceplate_resources.sh,
local only, not in CI). These tests keep its arithmetic and its safety contract
from eroding: synthetic /proc parsing, slope/CPU/flag maths (a genuine leak
series is flagged, a flat or noisy one is not), option validation and the
guarantee that the script is not wired into any workflow.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/soak_riceplate_resources.sh"
MODULE = ROOT / "scripts/soak_resource_sampler.py"
SPEC = importlib.util.spec_from_file_location("soak_resource_sampler", MODULE)
sampler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sampler
SPEC.loader.exec_module(sampler)

STAT = ("{pid} ({comm}) S {ppid} 1 1 0 -1 4194304 100 0 0 0 {utime} {stime} 0 0 20 0 "
        "{threads} 0 {start} 123456 789 18446744073709551615 0 0 0 0 0 0 0 0 0 0 0 17 0 0 0")
ROLLUP = "00400000-ffff ---p 00000000 00:00 0 [rollup]\nRss:   {rss} kB\nPss:   {pss} kB\nPrivate_Dirty: 1 kB\n"


def row(t, pss, phase="interact", cpu=0, role="riceplate-native", pid=10, start=500):
    return {"t_s": float(t), "phase": phase, "role": role, "pid": pid,
            "start_ticks": start, "pss_kib": pss, "rss_kib": pss + 100,
            "cpu_ticks": cpu, "threads": 4, "fds": 12}


class SyntheticProc(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proc = Path(self.tmp.name)

    def process(self, pid, comm, ppid, *, pss=1000, rss=2000, cpu=(7, 3), start=900,
                fds=3, threads=2):
        base = self.proc / str(pid)
        (base / "fd").mkdir(parents=True)
        for index in range(fds):
            (base / "fd" / str(index)).write_text("")
        (base / "comm").write_text(comm + "\n")
        (base / "stat").write_text(STAT.format(
            pid=pid, comm=comm, ppid=ppid, utime=cpu[0], stime=cpu[1],
            threads=threads, start=start))
        (base / "smaps_rollup").write_text(ROLLUP.format(rss=rss, pss=pss))

    def test_stat_parsing_survives_hostile_comm(self):
        raw = STAT.format(pid=5, comm="a) b (c", ppid=2, utime=11, stime=4, threads=7, start=42)
        self.assertEqual(sampler.parse_stat(raw), (2, 15, 7, 42))
        for bad in ("", "5 (x) S 1", STAT.format(pid=5, comm="x", ppid=2, utime="u", stime=1,
                                                   threads=1, start=1)):
            with self.assertRaises(sampler.SamplerError):
                sampler.parse_stat(bad)
        with self.assertRaises(sampler.SamplerError):  # start time 0 is not an identity
            sampler.parse_stat(STAT.format(pid=5, comm="x", ppid=2, utime=1, stime=1,
                                           threads=1, start=0))

    def test_rollup_needs_each_counter_exactly_once(self):
        self.assertEqual(sampler.parse_rollup(ROLLUP.format(rss=20, pss=9)), (9, 20))
        with self.assertRaises(sampler.SamplerError):
            sampler.parse_rollup("Rss: 5 kB\n")
        with self.assertRaises(sampler.SamplerError):
            sampler.parse_rollup(ROLLUP.format(rss=1, pss=1) + "Pss: 2 kB\n")

    def test_snapshot_tracks_only_the_helper_set_below_the_root(self):
        self.process(100, "dbus-run-session", 1)
        self.process(101, "riceplate-nativ", 100, pss=15000, cpu=(40, 10), threads=5, fds=9)
        self.process(102, "labwc", 100, pss=22000)
        self.process(103, "mako", 102, pss=4000)
        self.process(104, "foot", 102)             # a test client: not measured
        self.process(105, "sh", 100)               # not measured
        self.process(200, "riceplate-nativ", 1)    # another session: not below the root
        readings = sampler.snapshot(100, self.proc)
        self.assertEqual([(r.role, r.pid) for r in readings],
                         [("labwc", 102), ("mako", 103), ("riceplate-native", 101)])
        native = readings[2]
        self.assertEqual((native.pss_kib, native.cpu_ticks, native.threads, native.fds),
                         (15000, 50, 5, 9))

    def test_a_process_that_vanishes_mid_scan_is_skipped_not_fatal(self):
        self.process(100, "dbus-run-session", 1)
        self.process(101, "labwc", 100)
        (self.proc / "101" / "smaps_rollup").unlink()
        self.assertEqual(sampler.snapshot(100, self.proc), [])


class Maths(unittest.TestCase):
    def test_least_squares_and_theil_sen(self):
        line = [(t, 1000 + 2 * t) for t in range(0, 100, 10)]
        self.assertAlmostEqual(sampler.least_squares_slope(line), 2.0)
        self.assertAlmostEqual(sampler.theil_sen_slope(line), 2.0)
        self.assertIsNone(sampler.least_squares_slope([(1, 5)]))
        self.assertIsNone(sampler.theil_sen_slope([(3, 1), (3, 9)]))
        # One allocator spike barely moves Theil-Sen, which is why both are used.
        spiked = line[:5] + [(50, 9000)] + line[6:]
        self.assertAlmostEqual(sampler.theil_sen_slope(spiked), 2.0, places=0)
        self.assertGreater(sampler.least_squares_slope(spiked), 5)

    def test_cpu_percent_uses_only_phase_matching_same_process_pairs(self):
        samples = [row(0, 1, "warmup", cpu=0), row(10, 1, "idle1", cpu=50),
                   row(20, 1, "idle1", cpu=52), row(30, 1, "interact", cpu=80),
                   row(40, 1, "idle2", cpu=81), row(50, 1, "idle2", cpu=82)]
        # idle intervals: (10,20): 2 ticks / 10 s ; (40,50): 1 tick / 10 s -> 3/20 s
        idle = sampler.cpu_percent(samples, sampler.IDLE_PHASES, 100)
        self.assertAlmostEqual(idle, 100 * (3 / 100) / 20)
        self.assertIsNone(sampler.cpu_percent(samples[:1], sampler.IDLE_PHASES, 100))
        # A counter that goes backwards (identity reuse) is ignored, not negative.
        self.assertIsNone(sampler.cpu_percent(
            [row(0, 1, "idle1", cpu=9), row(10, 1, "idle1", cpu=1)], sampler.IDLE_PHASES, 100))

    def series(self, slope_kib_per_hour, *, noise=0, restarts=False):
        rows = []
        for index in range(0, 61):
            t = index * 10
            phase = ("warmup" if t < 60 else "idle1" if t < 150
                     else "interact" if t < 450 else "idle2")
            jitter = noise * ((index * 7919) % 5 - 2)
            pss = 20000 + slope_kib_per_hour * t / 3600 + jitter
            rows.append(row(t, round(pss), phase, cpu=t))
        if restarts:
            rows += [row(300, 9000, "interact", cpu=0, pid=77, start=800)]
        return rows

    def test_monotonic_growth_under_interaction_is_flagged(self):
        summary = sampler.summarize(self.series(20000), clk_tck=100, warmup_s=60)
        entry = summary["riceplate-native"]
        self.assertTrue(entry["growth_flag"], entry)
        self.assertAlmostEqual(entry["slope_kib_per_hour_ls"], 20000, delta=100)
        self.assertGreater(entry["slope_interact_kib_per_hour_theil_sen"], 19000)

    def test_flat_noisy_and_slow_series_are_not_flagged(self):
        for slope, noise in ((0, 0), (0, 40), (100, 40), (-5000, 0)):
            entry = sampler.summarize(self.series(slope, noise=noise),
                                      clk_tck=100, warmup_s=60)["riceplate-native"]
            self.assertFalse(entry["growth_flag"], (slope, noise, entry))
        shrink = sampler.summarize(self.series(-5000), clk_tck=100, warmup_s=60)
        self.assertLess(shrink["riceplate-native"]["slope_kib_per_hour_ls"], 0)

    def test_one_time_cache_fill_that_levels_off_is_not_a_leak(self):
        rows = []
        for index in range(0, 61):
            t = index * 10
            phase = ("warmup" if t < 60 else "idle1" if t < 150
                     else "interact" if t < 450 else "idle2")
            # +6 MiB while the first menus/popups allocate (t 150..240), then flat.
            pss = 20000 + (6144 * min(max(t - 150, 0), 90) / 90)
            rows.append(row(t, round(pss), phase, cpu=t))
        entry = sampler.summarize(rows, clk_tck=100, warmup_s=60)["riceplate-native"]
        self.assertGreater(entry["slope_kib_per_hour_ls"], 2048)   # whole-run slope alone would flag
        self.assertLess(abs(entry["slope_late_kib_per_hour_theil_sen"]), 1)
        self.assertFalse(entry["growth_flag"], entry)

    def test_summary_values_and_restart_reporting(self):
        entry = sampler.summarize(self.series(0), clk_tck=100, warmup_s=60)["riceplate-native"]
        self.assertEqual((entry["pss_start_kib"], entry["pss_end_kib"]), (20000, 20000))
        self.assertEqual(entry["pss_settled_kib"], 20000)
        self.assertEqual(entry["samples"], 61)
        self.assertAlmostEqual(entry["cpu_idle_percent"], 1.0)  # 1 tick per 1 s at CLK_TCK 100
        restarted = sampler.summarize(self.series(0, restarts=True), clk_tck=100,
                                      warmup_s=60)["riceplate-native"]
        self.assertEqual(restarted["identities"], 2)
        self.assertIn("restarted x1", sampler.format_table({"riceplate-native": restarted}))

    def test_csv_round_trip_rejects_malformed_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "x.csv"
            path.write_text(",".join(sampler.FIELDS) + "\n0.0,idle1,labwc,1,2,3,4,5,6,7\n")
            self.assertEqual(sampler.load_rows(path)[0]["role"], "labwc")
            path.write_text(",".join(sampler.FIELDS) + "\n0.0,idle1,labwc,1,2,x,4,5,6,7\n")
            with self.assertRaises(sampler.SamplerError):
                sampler.load_rows(path)

    def test_sampler_cli_writes_a_final_sample_after_the_stop_request(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "phase").write_text("idle1\n")
            (base / "stop").write_text("")
            out = base / "out.csv"
            code = sampler.main(["sample", "--root-pid", str(os.getpid()), "--out", str(out),
                                 "--phase-file", str(base / "phase"),
                                 "--stop-file", str(base / "stop"), "--interval", "1"])
            self.assertEqual(code, 0)
            self.assertTrue(out.read_text().startswith(",".join(sampler.FIELDS)))


class SoakScriptContract(unittest.TestCase):
    def run_script(self, **env):
        merged = dict(os.environ, **env)
        return subprocess.run(["sh", str(SCRIPT)], capture_output=True, text=True,
                              env=merged, timeout=30)

    def test_posix_syntax_and_not_wired_into_any_workflow(self):
        self.assertEqual(subprocess.run(["sh", "-n", str(SCRIPT)]).returncode, 0)
        for workflow in (ROOT / ".github/workflows").glob("*.yml"):
            text = workflow.read_text(encoding="utf-8")
            self.assertNotIn("soak_riceplate_resources", text, workflow.name)
            self.assertNotIn("soak_resource_sampler", text, workflow.name)

    def test_script_declares_the_measurement_boundary_and_the_phases(self):
        text = SCRIPT.read_text(encoding="utf-8")
        for needle in ("NOT a hardware benchmark", "smaps_rollup", "RICEBOWL_DE_NESTED=0",
                       "idle1", "interact", "idle2", "SOAK_FAIL_ON_GROWTH"):
            self.assertIn(needle, text)

    @unittest.skipIf(os.geteuid() == 0, "the soak refuses root; only checked unprivileged")
    def test_invalid_configuration_is_refused_before_anything_starts(self):
        for env, message in (({"SOAK_DURATION": "abc"}, "whole seconds"),
                             ({"SOAK_DURATION": "30", "SOAK_WARMUP": "60"}, "must cover"),
                             ({"SOAK_RICES": "chrome vim"}, "Unknown rice")):
            result = self.run_script(**env)
            self.assertEqual(result.returncode, 2, (env, result.stderr))
            self.assertIn(message, result.stderr)

    def test_root_is_refused(self):
        if os.geteuid() != 0:
            self.skipTest("only meaningful as root")
        result = self.run_script()
        self.assertEqual(result.returncode, 2)
        self.assertIn("unprivileged", result.stderr)


if __name__ == "__main__":
    unittest.main()
