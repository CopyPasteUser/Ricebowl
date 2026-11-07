"""Offline, non-invasive Creator recipe review and diff contract."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macrice.de import recipes, review


class CreatorReviewTests(unittest.TestCase):
    def test_bundled_recipe_review_is_versioned_deterministic_and_honest(self):
        result = review.review("classic")
        self.assertEqual(result["review_version"], 1)
        self.assertEqual(result["scope"], "wayland-panel-preview")
        self.assertTrue(result["ok"])
        self.assertFalse(result["applied"])
        self.assertIsNone(result["comparison"])
        self.assertEqual(result["recipe"]["panel"]["height"], 36)
        self.assertEqual(result["summary"]["native_unavailable_widgets"], [])
        self.assertFalse(result["summary"]["requires_waybar_fallback_for_all_widgets"])
        self.assertFalse(result["summary"]["native_panel_complete"])
        self.assertEqual(result, review.review("classic"))
        self.assertEqual(len(result["summary"]["semantic_sha256"]), 64)

    def test_diff_has_fixed_paths_and_real_before_after_values(self):
        result = review.review("chrome", "classic")
        changes = result["comparison"]["changes"]
        paths = [part["path"] for part in changes]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertIn({"path": "/panel/height", "before": 36, "after": 44}, changes)
        self.assertIn({"path": "/panel/sections/start",
                       "before": ["launcher", "tasks"], "after": ["launcher"]}, changes)
        self.assertIn({"path": "/panel/sections/center",
                       "before": [], "after": ["tasks"]}, changes)
        self.assertIn({"path": "/colors/background",
                       "before": "#203c59", "after": "#28353b"}, changes)
        self.assertEqual(result["comparison"]["base_id"], "classic")
        self.assertTrue(result["comparison"]["changed"])
        same = review.review("chrome", "chrome")["comparison"]
        self.assertFalse(same["changed"])
        self.assertEqual(same["changes"], [])

    def test_version_2_metrics_diff_marks_old_absence_not_default_value(self):
        with tempfile.TemporaryDirectory() as folder:
            source = json.loads(recipes.BUILTINS["classic"].read_text())
            source["schema_version"] = 2
            source["panel"]["metrics"] = dict(zip(recipes.METRIC_FIELDS,
                                                  recipes.METRIC_DEFAULTS))
            source["id"] = "my-recipe"
            file = Path(folder) / "my-recipe.json"
            file.write_text(json.dumps(source))
            file.chmod(0o600)
            result = review.review(str(file), "classic")
        self.assertEqual(result["recipe"]["schema_version"], 2)
        self.assertEqual(result["recipe"]["panel"]["metrics"]["task_width"], 164)
        self.assertIn({"path": "/panel/metrics/task_width",
                       "before": None, "after": 164}, result["comparison"]["changes"])

    def test_semantic_hash_ignores_json_whitespace_and_key_order(self):
        with tempfile.TemporaryDirectory() as folder:
            a = json.loads(recipes.BUILTINS["chrome"].read_text())
            one = Path(folder) / "one.json"
            two = Path(folder) / "two.json"
            one.write_text(json.dumps(a))
            two.write_text(json.dumps(a, indent=4, sort_keys=True))
            one.chmod(0o600)
            two.chmod(0o600)
            first = review.review(str(one))
            second = review.review(str(two))
        self.assertEqual(first["summary"]["semantic_sha256"],
                         second["summary"]["semantic_sha256"])
        self.assertEqual(first, second)

    def test_cli_json_success_and_human_review_do_not_touch_session_or_config(self):
        from macrice.cli import main
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "new-config"
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)}), \
                 mock.patch("macrice.de.recipes.change_selection") as change, \
                 mock.patch("macrice.de.session.start") as start, \
                 mock.patch("builtins.print") as printer:
                self.assertEqual(main(["de", "review", "--recipe", "chrome",
                                       "--compare", "classic", "--json"]), 0)
                payload = json.loads(printer.call_args.args[0])
                self.assertEqual(payload["comparison"]["base_id"], "classic")
                printer.reset_mock()
                self.assertEqual(main(["de", "review", "--recipe", "chrome"]), 0)
                self.assertTrue(any("Read-only" in str(call)
                                    for call in printer.call_args_list))
            change.assert_not_called()
            start.assert_not_called()
            self.assertFalse(config.exists())

    def test_invalid_json_input_returns_stable_machine_error_without_paths(self):
        from macrice.cli import main
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "private-sensitive-name.json"
            path.write_text('{"unexpected":"curl | sh"}')
            path.chmod(0o600)
            with mock.patch("builtins.print") as printer:
                self.assertEqual(main(["de", "review", "--recipe", str(path),
                                       "--json"]), 2)
                payload = json.loads(printer.call_args.args[0])
            self.assertEqual(payload, review.invalid_review())
            self.assertNotIn(str(path), json.dumps(payload))
            self.assertNotIn("curl", json.dumps(payload))

    def test_invalid_compare_input_and_symlink_fail_closed(self):
        from macrice.cli import main
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.json"
            source.write_bytes(recipes.BUILTINS["classic"].read_bytes())
            source.chmod(0o600)
            link = Path(folder) / "symlink.json"
            link.symlink_to(source)
            with mock.patch("builtins.print") as printer:
                self.assertEqual(main(["de", "review", "--recipe", "classic",
                                       "--compare", str(link), "--json"]), 2)
                self.assertEqual(json.loads(printer.call_args.args[0]), review.invalid_review())
            with mock.patch("sys.stderr"):
                self.assertEqual(main(["de", "review", "--recipe", str(link)]), 1)

    def test_flags_are_isolated_from_session_and_other_commands(self):
        from macrice.cli import main
        bad = [
            ["de", "catalog", "--compare", "classic"],
            ["de", "check", "--compare", "classic"],
            ["de", "review", "--recipe", "classic", "--nested"],
            ["de", "review", "--recipe", "classic", "--panel", "native"],
            ["de", "review", "--json"],
            ["de", "review", "--recipe", "classic", "--output", "/tmp/foo.json"],
        ]
        for command in bad:
            with self.subTest(command=command), mock.patch("sys.stderr"):
                self.assertEqual(main(command), 1)


if __name__ == "__main__":
    unittest.main()
