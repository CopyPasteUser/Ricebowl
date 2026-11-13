"""Read-only Mint hardware acceptance reports never infer a passed physical test."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from macrice.de import acceptance
from scripts.wayland_acceptance_report import create_report, load_sample, METRICS


def fixture(profile):
    return {
        "schema_version": 1, "profile_requested": profile,
        "profile_observed": profile, "profile_matches": True,
        "process_scope": "same-uid-comm-matches-not-exclusive-session",
        "process_count": 4, "elapsed_s": 10,
        "read_only": True, "hardware_accepted": False, "idle_confirmed": False,
        "rss_kib": 5000, "pss_kib": 2000,
        "cpu_percent_one_core": 2.5,
        "context_switches_per_s": None, "kernel_wakeups_per_s": None,
        "some_user_secret": "UNTRUSTED-PROBE-NOTES",
    }


class HardwareReportTests(unittest.TestCase):
    def _report(self, sources=None):
        accepted = acceptance.inspect(environment={"XDG_SESSION_TYPE": "x11"},
                                      which=lambda _: None)
        reliability = {"schema_version": 1, "recovery": {"state": "clean"}}
        return create_report(sources, acceptance_probe=accepted,
                             reliability_probe=reliability)

    def test_without_real_samples_hardware_remains_pending(self):
        result = self._report()
        self.assertFalse(result["hardware_accepted"])
        self.assertEqual(result["comparison_quality"], "incomplete")
        self.assertEqual(result["resource_comparison"], {})
        self.assertEqual(set(result["resource_samples"]), {"native", "waybar", "xfce"})
        self.assertTrue(all(value is None for value in result["resource_samples"].values()))
        self.assertTrue(all(x["status"] == "pending" for x in result["acceptance"]["manual_checks"]))

    def test_all_three_profiles_get_arithmetic_but_not_hardware_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            sources = {}
            for name in ("native", "waybar", "xfce"):
                file = Path(temp) / (name + ".json")
                sample = fixture(name)
                if name == "native":
                    sample["pss_kib"] = 1200
                file.write_text(json.dumps(sample))
                sources[name] = load_sample(file, profile=name)
            result = self._report(sources)
            self.assertEqual(result["resource_comparison"]["native_minus_xfce"]["pss_kib"], -800)
            self.assertIsNone(result["resource_comparison"]["native_minus_xfce"]["kernel_wakeups_per_s"])
            self.assertFalse(result["hardware_accepted"])
            self.assertNotIn("UNTRUSTED-PROBE-NOTES", json.dumps(result))
            self.assertIn("unverified", result["comparison_quality"])
            for entry in result["resource_samples"].values():
                self.assertFalse(entry["idle_confirmed"])
                self.assertIsNone(entry["cold_login_to_ready_ms"])

    def test_malformed_stale_mislabelled_and_unavailable_samples_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "native.json"
            good = fixture("native")
            mutations = [
                {"profile_observed": "xfce"},
                {"profile_matches": False},
                {"hardware_accepted": True},
                {"elapsed_s": 0},
                {"process_count": 0},
                {"rss_kib": -1},
                {"pss_kib": "many"},
                {"cpu_percent_one_core": float("nan")},
            ]
            for changes in mutations:
                with self.subTest(changes=changes):
                    path.write_text(json.dumps(good | changes))
                    with self.assertRaises(ValueError):
                        load_sample(path, profile="native")
            path.write_text(json.dumps(good))
            alias = Path(directory) / "alias.json"
            alias.symlink_to(path)
            with self.assertRaises(ValueError):
                load_sample(alias, profile="native")
            with self.assertRaises(ValueError):
                load_sample(Path("relative.json"), profile="native")
            path.write_bytes(b"{" + b"x" * 100_000)
            with self.assertRaises(ValueError):
                load_sample(path, profile="native")
            self.assertEqual(METRICS[0], "rss_kib")

    def test_rejects_unexpected_profile_in_comparison(self):
        with self.assertRaises(ValueError):
            self._report({"fake": {}})


if __name__ == "__main__":
    unittest.main()
