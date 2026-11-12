"""Resource profiles and on-demand measurements do not touch a real desktop."""

import json
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from macrice.cli import main
from macrice.performance import (PROFILES, _component, _desktop_component, apply_profile,
                                desktop_session_report, measure_processes, summarize_samples)


class PerformanceTests(unittest.TestCase):
    def test_profiles_only_change_selected_control_center_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config/macos-control-center/config.json"
            config.parent.mkdir(parents=True)
            previous = {"theme": "midnight", "poll_seconds": 13,
                        "devices": [{"name": "Personal NAS"}], "resource_profile": "balanced"}
            config.write_text(json.dumps(previous))
            backup = apply_profile("light", config_root=root / "config", data_root=root / "data")
            updated = json.loads(config.read_text())
            self.assertEqual(updated["poll_seconds"], 13)
            self.assertEqual(updated["devices"], previous["devices"])
            self.assertEqual(updated["theme"], "midnight")
            self.assertEqual(updated["resource_profile"], "light")
            self.assertFalse(updated["media_thumbnail"])
            self.assertEqual(json.loads((backup / "control-center-config.json").read_text()), previous)
            self.assertEqual((backup / "control-center-config.json").stat().st_mode & 0o777, 0o600)

    def test_visual_maps_to_existing_responsive_policy(self):
        self.assertEqual(PROFILES["visual"]["resource_profile"], "responsive")

    def test_does_not_follow_symlinked_preferences(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config/macos-control-center/config.json"
            config.parent.mkdir(parents=True)
            personal = root / "other.json"
            personal.write_text('{"theme":"light"}')
            config.symlink_to(personal)
            with self.assertRaises(ValueError):
                apply_profile("light", config_root=root / "config", data_root=root / "data")
            self.assertEqual(personal.read_text(), '{"theme":"light"}')

    def test_process_classifier_is_bounded_to_known_components(self):
        self.assertEqual(_component(["/usr/bin/python3", "-m", "macmenu", "--toggle"]), "MacMenu")
        self.assertEqual(_component(["/usr/bin/python3", "/tmp/macbar.py"]), "MacBar")
        self.assertEqual(_component(["/usr/bin/plank"]), "Plank")
        self.assertIsNone(_component(["/usr/bin/python3", "myservice.py", "macmenu"]))
        self.assertEqual(_component(["/usr/bin/python3", "/opt/ricebowl/launcher.py",
                                     "frutiger-shell"]), "RiceBowl Frutiger Aero")
        self.assertEqual(_component(["/usr/bin/python3", "/opt/ricebowl/launcher.py",
                                     "winxp-shell"]), "RiceBowl XP Luna")
        self.assertEqual(_component(["/usr/bin/python3", "/opt/ricebowl/launcher.py",
                                     "windows10-shell"]), "RiceBowl Windows 10")
        self.assertIsNone(_component(["/usr/bin/python3", "/tmp/unrelated.py",
                                            "frutiger-shell"]))

    def test_proc_report_includes_threads_without_background_monitor(self):
        with tempfile.TemporaryDirectory() as tmp:
            process = Path(tmp) / "23591"
            process.mkdir()
            (process / "cmdline").write_bytes(
                b"/usr/bin/python3\0/opt/ricebowl/launcher.py\0chromeos-shell\0")
            (process / "smaps_rollup").write_text("Pss: 16384 kB\n")
            (process / "status").write_text("Name:\tpython3\nThreads:\t4\n")
            report = measure_processes(proc_root=Path(tmp), sample_ms=50)
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]["name"], "RiceBowl ChromeOS")
        self.assertEqual(report[0]["pss_kib"], 16384)
        self.assertEqual(report[0]["threads"], 4)

    def test_empty_proc_report_is_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(measure_processes(proc_root=Path(tmp)), [])

    def test_xfce_role_classifier_never_matches_arbitrary_arguments(self):
        self.assertEqual(_desktop_component(["/usr/bin/xfwm4"]), ("xfwm4", "core"))
        self.assertEqual(_desktop_component(["/usr/lib/xfce4/xfce4-power-manager"]),
                         ("xfce4-power-manager", "shared"))
        self.assertEqual(_desktop_component(["/usr/bin/xfce4-panel"]),
                         ("xfce4-panel", "replaceable"))
        self.assertIsNone(_desktop_component(["/usr/bin/python3", "/tmp/xfce4-panel.py"]))

    def test_wayland_role_classifier_tracks_real_executables_only(self):
        self.assertEqual(_desktop_component(["/usr/bin/labwc", "--config-dir", "/tmp/config"]),
                         ("labwc", "compositor"))
        self.assertEqual(_desktop_component(["/usr/bin/waybar"]), ("waybar", "panel"))
        self.assertEqual(_desktop_component(["/home/user/.cargo/bin/riceplate-native"]),
                         ("riceplate-native", "panel"))
        self.assertEqual(_desktop_component(["/usr/bin/swaybg"]), ("swaybg", "wallpaper"))
        self.assertIsNone(_desktop_component(["/usr/bin/python3", "--recipe", "labwc"]))

    def test_desktop_inventory_requires_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc = root / "23591"
            proc.mkdir()
            (proc / "cmdline").write_bytes(b"/usr/bin/xfce4-panel\0")
            (proc / "smaps_rollup").write_text("Pss: 8192 kB\n")
            (proc / "status").write_text("Threads:\t2\n")
            self.assertEqual(measure_processes(proc_root=root), [])
            result = measure_processes(proc_root=root, sample_ms=50, include_desktop=True)
        self.assertEqual([(row["name"], row["role"]) for row in result],
                         [("xfce4-panel", "replaceable")])
        self.assertEqual(result[0]["pss_kib"], 8192)
        self.assertNotIn("argv", result[0])

    def test_desktop_report_identifies_duplicate_panels_without_stopping_anything(self):
        def proc(name, pid, role, pss=1024):
            return {"name": name, "pid": pid, "role": role,
                    "pss_kib": pss, "cpu_percent": 0, "threads": 2}

        report = desktop_session_report([[proc("RiceBowl XP Luna", 1, "ricebowl"),
                                          proc("xfce4-panel", 2, "replaceable"),
                                          proc("xfwm4", 3, "core"),
                                          proc("Plank", 4, "dock")]])
        self.assertEqual(len(report["warnings"]), 2)
        self.assertTrue(any("xfce4-panel" in w for w in report["warnings"]))
        self.assertTrue(any("Plank" in w for w in report["warnings"]))
        self.assertEqual(report["xfce_pss_kib"], 2048)
        self.assertEqual(next(item["role"] for item in report["components"]
                              if item["name"] == "Plank"), "dock")

    def test_desktop_report_marks_partial_xfce_measurements_unknown(self):
        report = desktop_session_report([[{"name": "xfsettingsd", "pid": 8,
                                          "role": "core", "pss_kib": None,
                                          "cpu_percent": None, "threads": None}]])
        self.assertIsNone(report["xfce_pss_kib"])
        self.assertEqual(report["warnings"], [])

    def test_wayland_totals_are_partial_when_counters_are_missing(self):
        def process(name, pid, pss):
            return {"name": name, "pid": pid, "role": "panel",
                    "pss_kib": pss, "cpu_percent": 0, "threads": 1}

        report = desktop_session_report([[process("labwc", 1, 1000),
                                          process("waybar", 2, 2000),
                                          process("xfwm4", 3, 3000)]])
        self.assertEqual(report["wayland_pss_kib"], 3000)
        self.assertEqual(report["xfce_pss_kib"], 3000)
        self.assertIn("not an isolated single-session", report["scope_note"])

        report = desktop_session_report([[process("labwc", 1, None),
                                          process("waybar", 2, 2000)]])
        self.assertIsNone(report["wayland_pss_kib"])
        self.assertIsNone(report["xfce_pss_kib"])

    def test_wayland_session_inventory_excludes_other_full_and_nested_logins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = "/run/user/1000/ricebowl-current"
            for pid, executable, config, nested in (
                (101, "labwc", session, "0"),
                (102, "riceplate-native", session, "0"),
                (103, "labwc", "/run/user/1000/ricebowl-other", "0"),
                (104, "waybar", session, "1"),
                (105, "xfce4-panel", None, "0"),
            ):
                proc = root / str(pid)
                proc.mkdir()
                (proc / "cmdline").write_bytes(f"/usr/bin/{executable}\0".encode())
                (proc / "status").write_text("Threads:\t2\n")
                (proc / "smaps_rollup").write_text("Pss: 1000 kB\n")
                markers = (["RICEBOWL_DE_SHELL_CHILD=1", f"RICEBOWL_DE_NESTED={nested}",
                            f"RICEBOWL_DE_SESSION_CONFIG={config}"] if config else [])
                (proc / "environ").write_bytes(("\0".join(markers) + "\0").encode())

            unfiltered = measure_processes(proc_root=root, sample_ms=50, include_desktop=True)
            scoped = measure_processes(proc_root=root, sample_ms=50,
                                       include_desktop=True, session_config=session)
        self.assertEqual(len(unfiltered), 5)
        self.assertEqual({item["pid"] for item in scoped}, {101, 102})
        report = desktop_session_report([scoped], session_config=session)
        self.assertEqual(report["wayland_pss_kib"], 2000)
        self.assertIsNone(report["xfce_pss_kib"])
        self.assertEqual(report["scope"], "current-wayland-session")
        self.assertIn("only recognized components", report["scope_note"])

    def test_wayland_session_inventory_fails_closed_on_unreadable_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp) / "101"
            proc.mkdir()
            (proc / "cmdline").write_bytes(b"/usr/bin/labwc\0")
            # No environ: never count this as the current session by inference.
            self.assertEqual(measure_processes(proc_root=Path(tmp), sample_ms=50,
                                               include_desktop=True,
                                               session_config="/run/user/1000/current"), [])

    def test_cli_wayland_session_mode_requires_full_marked_session(self):
        env = {"RICEBOWL_DE_SHELL_CHILD": "1", "RICEBOWL_DE_NESTED": "0",
               "XDG_SESSION_TYPE": "wayland",
               "RICEBOWL_DE_SESSION_CONFIG": "/run/user/1000/ricebowl-current"}
        with mock.patch.dict(os.environ, env):
            with mock.patch("macrice.performance.measure_processes", return_value=[]) as measure:
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["performance", "desktop", "--wayland-session",
                                           "--samples", "2", "--json"]), 0)
                report = json.loads(output.getvalue())
                self.assertEqual(report["scope"], "current-wayland-session")
                measure.assert_has_calls([mock.call(include_desktop=True,
                                                    session_config=env["RICEBOWL_DE_SESSION_CONFIG"])] * 2)

            with mock.patch.dict(os.environ, {"RICEBOWL_DE_NESTED": "1"}):
                with mock.patch("macrice.performance.measure_processes") as measure:
                    self.assertEqual(main(["performance", "desktop", "--wayland-session"]), 1)
                    measure.assert_not_called()
            self.assertEqual(main(["performance", "report", "--wayland-session"]), 1)

    def test_simultaneous_native_and_waybar_panels_are_only_warned_about(self):
        rows = [{"name": name, "pid": index, "role": "panel", "pss_kib": 100,
                 "cpu_percent": 0, "threads": 1} for index, name in enumerate(
                     ("labwc", "waybar", "riceplate-native"), 1)]
        report = desktop_session_report([rows])
        self.assertEqual(report["wayland_pss_kib"], 300)
        self.assertEqual(len(report["warnings"]), 1)
        self.assertIn("nested previews may be intentional", report["warnings"][0])

    def test_duplicate_instances_of_one_rice_are_reported(self):
        row = {"name": "RiceBowl Windows 7", "role": "ricebowl",
               "pss_kib": 100, "cpu_percent": 0, "threads": 1}
        report = desktop_session_report([[dict(row, pid=5), dict(row, pid=6)]])
        self.assertTrue(any("Multiple RiceBowl" in warning for warning in report["warnings"]))

    def test_cli_desktop_json_is_read_only_and_keeps_plain_report_separate(self):
        empty = []
        with mock.patch("macrice.performance.measure_processes", return_value=empty) as measure:
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["performance", "desktop", "--samples", "2", "--json"]), 0)
            report = json.loads(output.getvalue())
            self.assertEqual(report["warnings"], [])
            self.assertIsNone(report["xfce_pss_kib"])
            self.assertEqual(measure.call_count, 2)
            measure.assert_has_calls([mock.call(include_desktop=True)] * 2)
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["performance", "report", "--samples", "1", "--json"]), 0)
            self.assertNotIn("warnings", json.loads(output.getvalue()))
            measure.assert_called_with()

    def test_on_demand_medians_do_not_double_count_duplicate_process_observations(self):
        samples = [
            [{"name": "RiceBowl ChromeOS", "pid": 12, "pss_kib": 1000,
              "cpu_percent": 2, "threads": 3}],
            [{"name": "RiceBowl ChromeOS", "pid": 12, "pss_kib": 3000,
              "cpu_percent": 4, "threads": 3}],
            [{"name": "RiceBowl ChromeOS", "pid": 12, "pss_kib": None,
              "cpu_percent": None, "threads": None}],
        ]
        result = summarize_samples(samples)
        self.assertEqual(result["total_pss_kib"], 2000)
        self.assertEqual(result["total_cpu_percent"], 3)
        self.assertEqual(result["components"][0]["observations"], 3)
        self.assertTrue(result["partial"])  # One sample lacked counters.

    def test_missing_proc_counters_are_not_faked_as_zero(self):
        result = summarize_samples([[{"name": "Plank", "pid": 29, "pss_kib": None,
                                      "cpu_percent": None, "threads": 1}]])
        self.assertIsNone(result["total_pss_kib"])
        self.assertIsNone(result["total_cpu_percent"])
        self.assertTrue(result["partial"])

    def test_process_restart_does_not_add_two_sequential_processes_to_total(self):
        first = {"name": "Plank", "pid": 12, "pss_kib": 3000,
                 "cpu_percent": 1, "threads": 2}
        restarted = {"name": "Plank", "pid": 45, "pss_kib": 4000,
                     "cpu_percent": 3, "threads": 2}
        result = summarize_samples([[first], [restarted]])
        self.assertEqual(result["total_pss_kib"], 3500)
        self.assertEqual(result["total_cpu_percent"], 2)
        self.assertEqual(len(result["components"]), 2)


if __name__ == "__main__":
    unittest.main()
