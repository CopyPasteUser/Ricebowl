"""Creator -> validated recipe -> declared native contract, without activation."""

import json
import hashlib
import os
import subprocess
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
    def setUp(self):
        # A public Git checkout uses 0644; intentionally do not weaken
        # recipes.load's owner-private file requirement for Creator previews.
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.demos = []
        for example in DEMOS:
            source = Path(temporary.name) / example.name
            source.write_bytes(example.read_bytes())
            source.chmod(0o600)
            self.demos.append(source)

    def test_two_distinct_composer_rices_have_real_allowlisted_interactions(self):
        results = [parity.describe(str(path)) for path in self.demos]
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
        results = [parity.describe(str(path)) for path in self.demos]
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
            self.assertEqual(
                report["known_keyboard_access_gaps"],
                ["/panel/sections/end/3", "/panel/sections/end/4"],
            )
            self.assertTrue(all(row["keyboard_access_gap"] is False
                                for row in report["components"]
                                if row["kind"] == "widget" and
                                row["binding"] in ("launcher", "tasks")))


    def test_schema_v3_panel_composition_does_not_require_v4_responsive_keys(self):
        source_fixture = ROOT / "tests/fixtures/riceplate-nested-v3.json"
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "nested-v3.json"
            source.write_bytes(source_fixture.read_bytes())
            source.chmod(0o600)
            report = parity.describe(str(source))
        self.assertEqual(report["recipe"]["schema_version"], 3)
        self.assertTrue(any(row["area"] == "panel-wide" for row in report["components"]))
        self.assertFalse(any(row["area"] == "panel-compact" for row in report["components"]))
        self.assertTrue(all(case["panel_mode"] == "wide"
                            for case in report["output_cases"]))

    def test_menu_control_state_contract_matches_native_shared_feedback(self):
        source_fixture = ROOT / "examples/wayland/quick-controls.json"
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "controls.json"
            source.write_bytes(source_fixture.read_bytes())
            source.chmod(0o600)
            report = parity.describe(str(source))
        menu = [row for row in report["components"] if row["area"] == "menu"]
        controls = [row for row in menu if row["binding"] in recipes.PANEL_CONTROLS]
        self.assertEqual({row["binding"] for row in controls},
                         {"wifi-toggle", "bluetooth-toggle", "audio-mute",
                          "audio-up", "audio-down"})
        for row in controls:
            self.assertTrue(row["interactive"])
            self.assertTrue(row["verified_control_feedback"])
            self.assertEqual(row["state_contract"],
                             ["unavailable", "ready", "applying", "busy", "failed"])
            self.assertEqual(row["allowed_action"], row["binding"])
        for row in menu:
            if row["binding"] not in recipes.PANEL_CONTROLS:
                self.assertFalse(row["verified_control_feedback"])

    def test_declarative_shortcut_widget_overlap_is_a_review_warning(self):
        payload = json.loads(DEMOS[0].read_text())
        payload["composition"]["widgets"][0]["x"] = payload["desktop"]["icons"][0]["x"]
        payload["composition"]["widgets"][0]["y"] = payload["desktop"]["icons"][0]["y"]
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "overlapping.json"
            source.write_text(json.dumps(payload))
            source.chmod(0o600)
            report = parity.describe(str(source))
            warning = next(
                item for item in report["output_cases"][2]["declared_geometry_warnings"]
                if item["code"] == "declared-element-overlap"
            )
        self.assertEqual(warning["path"], "/desktop/icons/0")
        self.assertEqual(warning["other_path"], "/composition/widgets/0")
        self.assertEqual(report["native_render_execution"], "not_performed")

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
                for source in self.demos:
                    result = parity.describe(str(source))
                    self.assertEqual(result["recipe"]["semantic_sha256"],
                                     review.review(str(source))["summary"]["semantic_sha256"])
                self.assertFalse(config.exists())
                start.assert_not_called()
                select.assert_not_called()

    @unittest.skipIf(Image is None, "Pillow is not installed")
    def test_creator_gallery_publishes_only_complete_verified_matrix(self):
        from scripts import verify_wayland_creator_examples as gallery

        def fake_run(command, **_kwargs):
            source = Path(command[command.index("--recipe") + 1])
            screenshot = Path(command[command.index("--output") + 1])
            width = int(command[command.index("--width") + 1])
            height = int(command[command.index("--height") + 1])
            recipe = recipes.parse(source.read_bytes())
            color = (25, 82, 152) if recipe.recipe_id.startswith("heritage") else (35, 163, 90)
            Image.new("RGB", (width, height), color).save(screenshot)
            return type("Result", (), {"stdout": json.dumps({
                "ok": True, "creator_contract_version": 1,
                "render": {
                    "recipe": {"semantic_sha256":
                        review._semantic_hash(review._manifest(recipe))},
                    "source": "isolated-headless-labwc-native-riceplate",
                    "output": {"sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest()},
                },
            })})()

        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "gallery"
            target.mkdir()
            if target.stat().st_uid == 0:
                self.skipTest("Native gallery intentionally refuses root sessions")
            with (mock.patch.object(gallery.os, "geteuid", return_value=target.stat().st_uid),
                  mock.patch.object(gallery.shutil, "which", return_value="/usr/bin/dbus-run-session"),
                  mock.patch.object(gallery.subprocess, "check_output",
                                    return_value="test-commit-sha\n"),
                  mock.patch.object(gallery.subprocess, "run", side_effect=fake_run),
                  mock.patch.object(gallery, "compare",
                                    return_value={"layout_issues": [], "regions": []})):
                result = gallery.build_gallery(target, names=gallery.COMPOSERS)
            self.assertEqual(len(result["captures"]), 2 * len(gallery.SIZES))
            self.assertEqual(len(list(target.glob("*.png"))), 2 * len(gallery.SIZES))
            self.assertEqual(result["source_commit"], "test-commit-sha")
            self.assertEqual(json.loads((target / "manifest.json").read_text()), result)
            self.assertFalse(any(name.name.startswith(".ricebowl-gallery-stage")
                                 for name in target.iterdir()))

    @unittest.skipIf(Image is None, "Pillow is not installed")
    def test_failed_creator_render_never_publishes_partial_gallery(self):
        from scripts import verify_wayland_creator_examples as gallery

        calls = 0

        def fake_run(command, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise subprocess.CalledProcessError(7, command)
            source = Path(command[command.index("--recipe") + 1])
            screenshot = Path(command[command.index("--output") + 1])
            width = int(command[command.index("--width") + 1])
            height = int(command[command.index("--height") + 1])
            recipe = recipes.parse(source.read_bytes())
            Image.new("RGB", (width, height), "#123456").save(screenshot)
            return type("Result", (), {"stdout": json.dumps({
                "ok": True, "creator_contract_version": 1,
                "render": {
                    "recipe": {"semantic_sha256":
                        review._semantic_hash(review._manifest(recipe))},
                    "source": "isolated-headless-labwc-native-riceplate",
                    "output": {"sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest()},
                },
            })})()

        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "gallery"
            target.mkdir()
            if target.stat().st_uid == 0:
                self.skipTest("Native gallery intentionally refuses root sessions")
            with (mock.patch.object(gallery.os, "geteuid", return_value=target.stat().st_uid),
                  mock.patch.object(gallery.shutil, "which", return_value="/usr/bin/dbus-run-session"),
                  mock.patch.object(gallery.subprocess, "check_output",
                                    return_value="test-commit-sha\n"),
                  mock.patch.object(gallery.subprocess, "run", side_effect=fake_run),
                  mock.patch.object(gallery, "compare",
                                    return_value={"layout_issues": [], "regions": []})):
                with self.assertRaises(subprocess.CalledProcessError):
                    gallery.build_gallery(target, names=gallery.COMPOSERS)
            self.assertEqual(list(target.iterdir()), [],
                             "A failed second render must leave no partially published PNGs")
            self.assertEqual(calls, 2)

    def test_native_gallery_composer_selection_is_opt_in_and_allowlisted(self):
        from scripts import verify_wayland_creator_examples as gallery

        self.assertEqual(gallery.COMPOSERS,
                         ("heritage-composer-v10", "orbit-composer-v10"))
        self.assertEqual(len(gallery.NAMES), 4, "Existing gallery must not change")
        self.assertTrue(set(gallery.COMPOSERS).isdisjoint(gallery.NAMES))
        self.assertTrue(set(gallery.COMPOSERS) <= set(gallery.SCHEMAS))
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            for names in ((), ("invalid-script",),
                          ("heritage-composer-v10", "heritage-composer-v10")):
                with self.subTest(names=names), self.assertRaisesRegex(
                        ValueError, "known validated"):
                    gallery.build_gallery(output, names=names)
            self.assertEqual(list(output.iterdir()), [])

    def test_standard_de_cli_reports_parity_without_starting_wayland(self):
        from macrice.cli import main as cli

        source = str(self.demos[0])
        with (mock.patch("macrice.de.session.start") as start,
              mock.patch("macrice.de.recipes.change_selection") as selection,
              mock.patch("builtins.print") as printer):
            self.assertEqual(cli(["de", "creator-parity", "--recipe", source,
                                  "--json"]), 0)
            result = json.loads(printer.call_args.args[0])
            self.assertTrue(result["ok"])
            self.assertEqual(result["parity"]["recipe"]["id"], "heritage-composer-v10")
            self.assertEqual(result["parity"]["native_render_execution"], "not_performed")
            printer.reset_mock()
            self.assertEqual(cli(["de", "creator-parity", "--json"]), 1)
            self.assertEqual(cli(["de", "creator-parity", "--recipe", source,
                                  "--compare", "classic", "--json"]), 1)
        start.assert_not_called()
        selection.assert_not_called()

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
