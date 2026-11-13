"""Regression/failure-injection tests for read-only standalone reliability tools."""

from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from macrice.cli import main
from macrice.de import reliability
from scripts.measure_wayland_resources import actual_profile, measure


def sample(pid=123, role="compositor", cpu=100, rss=1024, pss=512,
           switches=200, wakeups=80, start=7):
    return reliability.ProcessSample(pid, role, start, cpu, rss, pss, switches, wakeups)


class ReadOnlySessionReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.env = {
            "XDG_SESSION_TYPE": "wayland",
            "XDG_CURRENT_DESKTOP": reliability.DESKTOP_NAME,
            "RICEBOWL_DE_SHELL_CHILD": "1",
            "RICEBOWL_DE_PANEL": "native",
            "RICEBOWL_DE_NESTED": "0",
            "DBUS_SESSION_BUS_ADDRESS": "private-credentials",
            "SOME_SECRET": "PRIVATE_WIFI_DATA",
        }

    def test_xfce_and_unmarked_sessions_skip_process_protocol_capture(self):
        for delta in ({"XDG_SESSION_TYPE": "x11"}, {"RICEBOWL_DE_SHELL_CHILD": "0"},
                      {"XDG_CURRENT_DESKTOP": "XFCE"}):
            with self.subTest(delta=delta):
                def forbidden(*args, **kwargs):
                    raise AssertionError("must not query unrelated compositor")
                report = reliability.inspect(
                    environment=self.env | delta, run=forbidden,
                    socket_probe=forbidden, samples=(sample(),),
                    which=lambda _: None, recovery={"ok": True, "pending": False})
                self.assertIsNone(report["processes"])
                self.assertEqual(report["protocols"]["probe"], "not-run")
                self.assertFalse(report["hardware_accepted"])
                self.assertEqual(report["process_scope"], "not-probed")

    def test_native_protocols_are_reported_from_allowlisted_names_only(self):
        leaked = "VERY_PRIVATE_WINDOW_TITLE"
        output = (f"interface: 'wl_compositor', version: 6\n"
                  f"interface: 'xdg_wm_base', version: 6\n"
                  f"interface: 'zwlr_layer_shell_v1', version: 4\n"
                  f"title: {leaked}")
        commands = []
        def run(*args, **kwargs):
            commands.append((args, kwargs))
            return subprocess.CompletedProcess(args[0], 0, output, "")
        report = reliability.inspect(
            environment=self.env, which=lambda x: f"/usr/bin/{x}",
            run=run, socket_probe=lambda _: "present",
            samples=(sample(), sample(124, "native-panel", pss=None)),
            recovery={"ok": True, "pending": True, "owner_running": False,
                      "error": leaked})
        self.assertTrue(all(report["protocols"]["required"].values()))
        self.assertEqual(report["protocols"]["probe"], "observed")
        self.assertEqual(report["recovery"]["state"], "pending")
        self.assertEqual(report["recovery"]["owner_running"], False)
        self.assertEqual(report["processes"]["compositor"]["pss_kib"], 512)
        self.assertIsNone(report["processes"]["native-panel"]["pss_kib"])
        self.assertEqual(report["process_scope"], "same-uid-not-session-attributed")
        self.assertNotIn(leaked, json.dumps(report))
        self.assertNotIn("PRIVATE_WIFI_DATA", json.dumps(report))
        self.assertNotIn("private-credentials", json.dumps(report))
        self.assertEqual(len(commands), 2)
        self.assertLessEqual(commands[0][1]["timeout"], 3)

    def test_protocol_names_in_window_titles_are_not_registry_advertisements(self):
        text = ("title: zwlr_layer_shell_v1 wl_compositor xdg_wm_base\\n"
                "unrelated: zwlr_foreign_toplevel_manager_v1")
        report = reliability.inspect(
            environment=self.env, which=lambda x: x,
            run=lambda args, **kw: subprocess.CompletedProcess(args, 0, text, ""),
            socket_probe=lambda _: "present", samples=(),
            recovery={"ok": True, "pending": False})
        self.assertEqual(report["protocols"]["probe"], "observed")
        self.assertTrue(all(value is False for value in
                            report["protocols"]["required"].values()))

    def test_disconnected_dbus_is_reported_without_service_mutation(self):
        calls = []
        def runner(args, **kwargs):
            calls.append(args)
            if args[0] == "dbus-send":
                return subprocess.CompletedProcess(args, 1, "", "private bus error")
            return subprocess.CompletedProcess(args, 0,
                                               "interface: 'wl_compositor'\\n", "")
        report = reliability.inspect(
            environment=self.env, which=lambda x: x, run=runner,
            socket_probe=lambda _: "present", samples=(),
            recovery={"ok": True, "pending": False})
        self.assertEqual(report["session_bus"]["probe"], "unreachable")
        self.assertTrue(report["session_bus"]["address_declared"])
        self.assertEqual(report["protocols"]["probe"], "observed")
        self.assertNotIn("private bus error", json.dumps(report))
        self.assertEqual(sum(x[0] == "dbus-send" for x in calls), 1)
        # No user service is started, restarted or configured by a Ping.
        self.assertTrue(all("org.freedesktop.DBus.Peer.Ping" in call
                            for call in calls if call[0] == "dbus-send"))

    def test_missing_lock_and_backend_never_claim_ready(self):
        present = {"labwc", "waybar", "foot", "fuzzel", "swaylock", "riceplate-native"}
        report = reliability.inspect(
            environment=self.env, which=lambda x: x if x in present else None,
            run=lambda *a, **kw: (_ for _ in ()).throw(AssertionError("no discovery")),
            socket_probe=lambda _: "missing", samples=(),
            recovery={"ok": False, "pending": None, "error": {"message": "do not print"}})
        self.assertIn("swayidle", report["required_missing"])
        self.assertEqual(report["protocols"]["probe"], "not-run")
        self.assertEqual(report["recovery"]["state"], "unsafe")
        self.assertFalse(report["hardware_accepted"])
        self.assertIsNone(report["processes"]["lock-guard"]["pss_kib"])

    def test_failed_or_oversized_wayland_info_is_bounded_and_not_treated_as_missing(self):
        failures = [
            lambda *a, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired("wayland-info", 3)),
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 1, "BAD", ""),
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, "x" * 70_000, ""),
        ]
        for runner in failures:
            with self.subTest(runner=runner):
                report = reliability.inspect(
                    environment=self.env, which=lambda x: x,
                    run=runner, socket_probe=lambda _: "present", samples=(),
                    recovery={"ok": True, "pending": False})
                self.assertEqual(report["protocols"]["probe"], "unavailable")
                self.assertTrue(all(v is None for v in report["protocols"]["required"].values()))

    def test_proc_sampler_ignores_other_users_and_corrupt_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            valid = root / "101"
            valid.mkdir()
            uid = os.getuid()
            status = (f"Name:\twaybar\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n"
                      "VmRSS:\t2048 kB\nvoluntary_ctxt_switches:\t11\n"
                      "nonvoluntary_ctxt_switches:\t7\n")
            (valid / "status").write_text(status)
            numbers = ["0"] * 24
            numbers[11], numbers[12], numbers[19] = "14", "5", "100000"
            (valid / "stat").write_text("101 (waybar) " + " ".join(numbers))
            (valid / "smaps_rollup").write_text("Pss:\t1024 kB\n")
            (valid / "sched").write_text("waybar (101, #threads: 1)\nnr_wakeups   : 22\n")
            foreign = root / "102"
            foreign.mkdir()
            (foreign / "status").write_text(status.replace(
                f"Uid:\t{uid}", f"Uid:\t{uid + 1}"))
            corrupt = root / "103"
            corrupt.mkdir()
            (corrupt / "status").write_text(status)
            (corrupt / "stat").write_text("bad stat")
            observed = reliability.scan_processes(proc_root=root, uid=uid)
            self.assertEqual(len(observed), 1)
            self.assertEqual(observed[0].pid, 101)
            self.assertEqual(observed[0].role, "fallback-panel")
            self.assertEqual((observed[0].rss_kib, observed[0].pss_kib), (2048, 1024))
            self.assertEqual((observed[0].switches, observed[0].wakeups), (18, 22))
            (valid / "smaps_rollup").unlink()
            (valid / "sched").unlink()
            observed = reliability.scan_processes(proc_root=root, uid=uid)
            self.assertIsNone(observed[0].pss_kib)
            self.assertIsNone(observed[0].wakeups)

    def test_cli_flags_and_json_are_read_only(self):
        stub = reliability.inspect(environment={"XDG_SESSION_TYPE": "x11"},
                                   which=lambda _: None,
                                   recovery={"ok": True, "pending": False})
        stdout = io.StringIO()
        with patch("macrice.de.reliability.inspect", return_value=stub), patch("sys.stdout", stdout):
            self.assertEqual(main(["de", "reliability", "--json"]), 0)
        self.assertEqual(json.loads(stdout.getvalue())["schema_version"], 1)
        with patch("sys.stderr", io.StringIO()):
            self.assertEqual(main(["de", "reliability", "--nested"]), 1)
            self.assertEqual(main(["de", "reliability", "--panel", "native"]), 1)


class ResourceMeasurementTests(unittest.TestCase):
    def test_cpu_pss_context_switch_and_kernel_wakeup_accounting(self):
        observed = iter([
            (sample(role="native-panel", cpu=150, rss=3000, pss=1100, switches=12, wakeups=22),),
            (sample(role="native-panel", cpu=200, rss=3200, pss=1200, switches=27, wakeups=32),),
        ])
        times = iter([0.0, 2.0])
        results = measure("native", seconds=2, reader=lambda: next(observed),
                          sleep=lambda _: None, clock=lambda: next(times),
                          ticks_per_second=100,
                          environment={"XDG_SESSION_TYPE": "wayland",
                                       "RICEBOWL_DE_SHELL_CHILD": "1",
                                       "RICEBOWL_DE_PANEL": "native"})
        self.assertEqual(results["cpu_percent_one_core"], 25.0)
        self.assertEqual(results["context_switches_per_s"], 7.5)
        self.assertEqual(results["kernel_wakeups_per_s"], 5.0)
        self.assertEqual(results["pss_kib"], 1200)
        self.assertEqual(results["rss_kib"], 3200)
        self.assertTrue(results["profile_matches"])
        self.assertTrue(results["process_role_verified"])
        self.assertFalse(results["hardware_accepted"])
        self.assertIsNone(results["cold_login_to_ready_ms"])

    def test_native_label_does_not_accept_waybar_rescue_or_ambiguous_panels(self):
        env = {"XDG_SESSION_TYPE": "wayland",
               "RICEBOWL_DE_SHELL_CHILD": "1",
               "RICEBOWL_DE_PANEL": "native"}
        for records in [
            (sample(pid=41, role="fallback-panel"),),
            (sample(pid=41, role="native-panel"),
             sample(pid=42, role="fallback-panel")),
        ]:
            with self.subTest(roles=[item.role for item in records]):
                result = measure(
                    "native", seconds=1, reader=lambda: records,
                    sleep=lambda _: None, clock=iter([0., 1.]).__next__,
                    ticks_per_second=100, environment=env)
                self.assertEqual(result["profile_observed"], "native")
                self.assertFalse(result["process_role_verified"])
                self.assertFalse(result["profile_matches"])
                self.assertFalse(result["hardware_accepted"])

    def test_profile_role_must_survive_both_samples(self):
        records = iter([
            (sample(pid=41, role="native-panel"),),
            (sample(pid=42, role="fallback-panel"),),
        ])
        result = measure(
            "native", seconds=1, reader=lambda: next(records),
            sleep=lambda _: None, clock=iter([0., 1.]).__next__,
            ticks_per_second=100, environment={
                "XDG_SESSION_TYPE": "wayland",
                "RICEBOWL_DE_SHELL_CHILD": "1", "RICEBOWL_DE_PANEL": "native"})
        self.assertFalse(result["profile_matches"])
        self.assertTrue(result["process_restart_or_exit_detected"])

    def test_missing_kernel_wakeups_and_pid_reuse_are_not_fake_zero(self):
        observed = iter([
            (sample(pid=50, wakeups=None, start=11),),
            (sample(pid=50, wakeups=None, start=12),),
        ])
        times = iter([0.0, 1.0])
        result = measure("native", seconds=1, reader=lambda: next(observed),
                         sleep=lambda _: None, clock=lambda: next(times),
                         ticks_per_second=100, environment={})
        self.assertEqual(result["stable_process_count"], 0)
        self.assertTrue(result["process_restart_or_exit_detected"])
        self.assertIsNone(result["kernel_wakeups_per_s"])
        self.assertIsNone(result["context_switches_per_s"])
        self.assertFalse(result["profile_matches"])
        self.assertEqual(result["profile_observed"], "unknown")

    def test_xfce_profile_is_separate_from_wayland(self):
        self.assertEqual(actual_profile({"XDG_SESSION_TYPE": "x11",
                                         "XDG_CURRENT_DESKTOP": "XFCE"}), "xfce")
        self.assertEqual(actual_profile({"XDG_SESSION_TYPE": "wayland",
                                         "RICEBOWL_DE_PANEL": "native"}), "unknown")
        for invalid in ("unknown", "xfce2"):
            with self.assertRaises(ValueError):
                measure(invalid, seconds=1, reader=lambda: ())
        with self.assertRaises(ValueError):
            measure("native", seconds=0.0, reader=lambda: ())


if __name__ == "__main__":
    unittest.main()
