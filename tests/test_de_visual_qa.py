"""Deterministic screenshot comparisons, never invented preview screenshots."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from PIL import Image
except ImportError:
    Image = None

from scripts.compare_wayland_captures import compare, main
from macrice.de.visual_qa import compare as installed_compare, create_baseline


@unittest.skipIf(Image is None, "Optional Pillow is not installed in this runtime")
class WaylandVisualQaTests(unittest.TestCase):
    def test_script_and_installed_cli_share_exact_same_engine(self):
        self.assertIs(compare, installed_compare)

    def test_native_smoke_embedded_shell_remains_literal(self):
        """Prevent quotes from prematurely closing the `sh -c` payload."""
        source = (Path(__file__).parent.parent /
                  "scripts/smoke_riceplate_native.sh").read_text(encoding="utf-8")
        embedded = source.split("dbus-run-session -- sh -eu -c '", 1)[1].split(
            "' sh \"$source_root\"", 1)[0]
        self.assertNotIn("'", embedded)

    def _private_recipe(self, directory: Path, *, bottom: bool = False) -> Path:
        source = Path(__file__).parent / "fixtures/riceplate-desktop-v5.json"
        data = json.loads(source.read_text(encoding="utf-8"))
        if bottom:
            data["panel"]["position"] = "bottom"
            data["desktop"]["icons"][0].update(x=600, y=700)
        path = directory / "recipe.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        path.chmod(0o600)
        return path

    def test_identical_real_pngs_are_reported_as_identical(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "capture.png"
            Image.new("RGB", (32, 24), "#1357ab").save(path)
            result = compare(path, path)
            self.assertTrue(result["identical"])
            self.assertEqual(result["changed_pixel_ratio"], 0)
            self.assertEqual(result["size"], {"width": 32, "height": 24})
            self.assertEqual(result["perceptual_or_functional_accuracy"], "not_measured")

    def test_changes_are_measured_not_reported_as_fake_accuracy(self):
        with tempfile.TemporaryDirectory() as folder:
            reference = Path(folder) / "reference.png"
            actual = Path(folder) / "actual.png"
            Image.new("RGB", (10, 10), "#000000").save(reference)
            image = Image.new("RGB", (10, 10), "#000000")
            for x in range(5):
                for y in range(10):
                    image.putpixel((x, y), (255, 255, 255))
            image.save(actual)
            result = compare(reference, actual, threshold=24)
            self.assertEqual(result["changed_pixel_ratio"], .5)
            self.assertEqual(result["mean_absolute_rgb_error"], 127.5)
            self.assertFalse(result["identical"])

    def test_two_way_tolerance_ignores_tiny_offsets_but_not_disappearing_shapes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reference, actual = root / "reference.png", root / "actual.png"
            first = Image.new("RGB", (24, 24), "black")
            for y in range(5, 19):
                first.putpixel((10, y), (240, 240, 240))
            first.save(reference)
            second = Image.new("RGB", (24, 24), "black")
            for y in range(5, 19):
                second.putpixel((11, y), (240, 240, 240))
            second.save(actual)
            heatmap = root / "tolerant.png"
            report = compare(reference, actual, tolerance_radius=1, tolerant_heatmap=heatmap)
            self.assertEqual(report["comparison_version"], 3)
            self.assertGreater(report["changed_pixel_ratio"], 0)
            self.assertEqual(report["tolerance"]["changed_pixel_ratio"], 0)
            with Image.open(heatmap) as image:
                self.assertEqual(image.getbbox(), None)
            second = Image.new("RGB", (24, 24), "black")
            second.save(actual)
            report = compare(reference, actual, tolerance_radius=1)
            self.assertGreater(report["tolerance"]["changed_pixel_ratio"], 0)
            with self.assertRaisesRegex(ValueError, "Tolerance radius"):
                compare(reference, actual, tolerance_radius=3)

    def test_explicit_baseline_is_private_pinned_and_rejects_real_regressions(self):
        from macrice.cli import main as cli

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            recipe = self._private_recipe(root)
            reference, actual = root / "ref.png", root / "actual.png"
            baseline = root / "approved.json"
            Image.new("RGB", (1024, 768), "#101010").save(reference)
            Image.new("RGB", (1024, 768), "#101010").save(actual)
            cmd = ["de", "visual-baseline", "--reference", str(reference),
                   "--recipe", str(recipe), "--output", str(baseline), "--json"]
            with mock.patch("builtins.print") as printer:
                self.assertEqual(cli(cmd), 1, "A baseline must be explicitly approved")
                self.assertEqual(cli(cmd + ["--approve-reference"]), 0)
            self.assertEqual(baseline.stat().st_mode & 0o777, 0o600)
            approved = json.loads(baseline.read_text())
            self.assertEqual(approved["policy"]["tolerance_radius"], 1)
            result = installed_compare(reference, actual, recipe_token=str(recipe),
                                       baseline=baseline)
            self.assertTrue(result["baseline"]["passed"])
            self.assertEqual(result["comparison_version"], 3)
            with mock.patch("builtins.print") as printer:
                self.assertEqual(cli(cmd + ["--approve-reference"]), 2)
                self.assertEqual(json.loads(printer.call_args.args[0])["error"]["code"],
                                 "invalid_baseline_input")

            image = Image.new("RGB", (1024, 768), "#101010")
            for x in range(100, 270):
                for y in range(100, 270):
                    image.putpixel((x, y), (255, 255, 255))
            image.save(actual)
            with mock.patch("builtins.print") as printer:
                self.assertEqual(cli(["de", "visual-compare", "--reference", str(reference),
                                      "--actual", str(actual), "--recipe", str(recipe),
                                      "--baseline", str(baseline), "--json"]), 3)
                report = json.loads(printer.call_args.args[0])
            self.assertFalse(report["ok"])
            self.assertFalse(report["visual_qa"]["baseline"]["passed"])
            self.assertGreater(report["visual_qa"]["baseline"]["changed_pixel_ratio"], .01)

            Image.new("RGB", (1024, 768), "#141414").save(reference)
            with self.assertRaisesRegex(ValueError, "no longer matches"):
                installed_compare(reference, actual, recipe_token=str(recipe),
                                  baseline=baseline)
            Image.new("RGB", (1024, 768), "#101010").save(reference)
            reference_before = baseline.read_bytes()
            source = json.loads(recipe.read_text())
            source["name"] = "Changed after approval"
            recipe.write_text(json.dumps(source))
            with self.assertRaisesRegex(ValueError, "no longer matches"):
                installed_compare(reference, actual, recipe_token=str(recipe),
                                  baseline=baseline)
            self.assertEqual(baseline.read_bytes(), reference_before)

    def test_malformed_or_symlinked_baseline_is_rejected_without_diagnostics(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            recipe = self._private_recipe(root)
            ref = root / "ref.png"
            Image.new("RGB", (1024, 768), "black").save(ref)
            baseline = root / "approved.json"
            create_baseline(ref, str(recipe), baseline)
            link = root / "symlink.json"
            link.symlink_to(baseline)
            artifact = root / "not-created.png"
            with self.assertRaises(ValueError):
                installed_compare(ref, ref, recipe_token=str(recipe), baseline=link,
                                  heatmap=artifact)
            self.assertFalse(artifact.exists())
            baseline.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "owner-private"):
                installed_compare(ref, ref, recipe_token=str(recipe), baseline=baseline)
            baseline.chmod(0o600)
            damaged = json.loads(baseline.read_text())
            damaged["policy"]["max_changed_ratio"] = float("nan")
            baseline.write_text(json.dumps(damaged))
            with self.assertRaisesRegex(ValueError, "policy is invalid"):
                installed_compare(ref, ref, recipe_token=str(recipe), baseline=baseline)
            self.assertFalse(artifact.exists())

    def test_dimension_mismatch_and_corrupt_images_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            a = Path(folder) / "a.png"
            b = Path(folder) / "b.png"
            Image.new("RGB", (10, 10)).save(a)
            Image.new("RGB", (11, 10)).save(b)
            with self.assertRaisesRegex(ValueError, "dimensions differ"):
                compare(a, b)
            b.write_text("not a screenshot")
            self.assertEqual(main([str(a), str(b)]), 2)
            with self.assertRaisesRegex(ValueError, "Threshold"):
                compare(a, a, threshold=256)

    def test_validated_rice_regions_report_pixel_changes_and_clipped_icons(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            source = self._private_recipe(directory)
            reference, actual = directory / "reference.png", directory / "actual.png"
            Image.new("RGB", (200, 260), "#223344").save(reference)
            image = Image.new("RGB", (200, 260), "#223344")
            image.putpixel((40, 105), (255, 255, 255))
            image.save(actual)
            result = compare(reference, actual, recipe_token=str(source))
            self.assertEqual(result["comparison_version"], 2)
            self.assertEqual(result["recipe"]["id"], "mockup-desktop")
            self.assertEqual(len(result["recipe"]["semantic_sha256"]), 64)
            regions = {item["id"]: item for item in result["regions"]}
            self.assertEqual(regions["panel"]["expected_rect"]["height"], 40)
            self.assertTrue(regions["panel"]["identical"])
            self.assertFalse(regions["desktop-icon-1"]["identical"])
            self.assertGreater(regions["desktop-icon-2"]["visible_fraction"], 0)
            self.assertLess(regions["desktop-icon-2"]["visible_fraction"], 1)
            self.assertEqual(regions["desktop-icon-3"]["visible_fraction"], round(48 / 104, 6))
            self.assertEqual({item["code"] for item in result["layout_issues"]},
                             {"icon_outside_output"})

    def test_bottom_panel_collision_is_reported_without_changing_recipe(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            source = self._private_recipe(directory, bottom=True)
            path = directory / "capture.png"
            Image.new("RGB", (800, 768), "#123456").save(path)
            before = source.read_bytes()
            result = compare(path, path, recipe_token=str(source))
            self.assertEqual(result["regions"][0]["expected_rect"]["y"], 728)
            self.assertEqual({item["code"] for item in result["layout_issues"]},
                             {"icon_outside_output", "icon_overlaps_panel"})
            self.assertEqual(source.read_bytes(), before)
            self.assertTrue(result["identical"])

    def test_overlay_and_heatmap_are_private_and_never_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            ref, current = directory / "ref.png", directory / "current.png"
            overlay, heatmap = directory / "overlay.png", directory / "heatmap.png"
            Image.new("RGB", (12, 12), "#000000").save(ref)
            Image.new("RGB", (12, 12), "#ffffff").save(current)
            result = compare(ref, current, overlay=overlay, heatmap=heatmap)
            self.assertEqual(result["overlay"], str(overlay))
            for path in (overlay, heatmap):
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                with Image.open(path) as image:
                    self.assertEqual(image.size, (12, 12))
            with Image.open(heatmap) as image:
                self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))
            with self.assertRaisesRegex(ValueError, "exists"):
                compare(ref, current, overlay=overlay)
            self.assertTrue(overlay.exists())
            with self.assertRaisesRegex(ValueError, "distinct"):
                compare(ref, current, overlay=directory / "same.png",
                        heatmap=directory / "same.png")
            only = directory / "new.png"
            with self.assertRaisesRegex(ValueError, "exists"):
                compare(ref, current, overlay=only, heatmap=heatmap)
            self.assertFalse(only.exists(), "Partial diagnostics must be rolled back")

    def test_invalid_recipe_is_rejected_before_saving_diagnostics(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            ref = directory / "reference.png"
            Image.new("RGB", (12, 12)).save(ref)
            output = directory / "overlay.png"
            with self.assertRaisesRegex(ValueError, "Invalid or unsafe recipe"):
                compare(ref, ref, recipe_token=str(directory / "missing.json"), overlay=output)
            self.assertFalse(output.exists())

    def test_cli_recipe_and_artifacts_return_machine_readable_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            source = self._private_recipe(directory)
            ref, overlay = directory / "reference.png", directory / "overlay.png"
            Image.new("RGB", (1024, 768)).save(ref)
            from unittest.mock import patch
            with patch("builtins.print") as printer:
                code = main([str(ref), str(ref), "--recipe", str(source),
                             "--overlay", str(overlay)])
            self.assertEqual(code, 0)
            report = json.loads(printer.call_args.args[0])
            self.assertEqual(report["recipe"]["schema_version"], 5)
            self.assertEqual(report["overlay"], str(overlay))
            self.assertEqual(report["layout_issues"], [])

    def test_installed_creator_cli_reports_versioned_real_capture_diagnostics(self):
        from macrice.cli import main as cli
        from macrice.de.creator_contract import describe_visual_qa

        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            source = self._private_recipe(directory)
            before = source.read_bytes()
            ref, actual = directory / "reference.png", directory / "actual.png"
            overlay, heatmap = directory / "overlay.png", directory / "heatmap.png"
            Image.new("RGB", (1024, 768), "#000000").save(ref)
            Image.new("RGB", (1024, 768), "#121212").save(actual)
            args = ["de", "visual-compare", "--reference", str(ref),
                    "--actual", str(actual), "--recipe", str(source),
                    "--overlay", str(overlay), "--heatmap", str(heatmap), "--json"]
            with mock.patch("macrice.de.session.start") as start, \
                 mock.patch("macrice.de.recipes.change_selection") as selection, \
                 mock.patch("builtins.print") as printer:
                self.assertEqual(cli(args), 0)
            payload = json.loads(printer.call_args.args[0])
            self.assertEqual(payload["creator_contract_version"],
                             describe_visual_qa()["contract_version"])
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["applied"])
            self.assertEqual(payload["visual_qa"]["comparison_version"], 2)
            self.assertEqual(payload["visual_qa"]["layout_issues"], [])
            self.assertEqual(payload["visual_qa"]["size"], {"width": 1024, "height": 768})
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(overlay.stat().st_mode & 0o777, 0o600)
            self.assertEqual(heatmap.stat().st_mode & 0o777, 0o600)
            start.assert_not_called()
            selection.assert_not_called()

    def test_installed_creator_cli_fails_closed_without_leaking_private_paths(self):
        from macrice.cli import main as cli

        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            ref = directory / "private-reference.png"
            actual = directory / "private-secret-capture.png"
            target = directory / "unwanted-overlay.png"
            Image.new("RGB", (10, 10)).save(ref)
            actual.write_text("not a PNG")
            args = ["de", "visual-compare", "--reference", str(ref),
                    "--actual", str(actual), "--overlay", str(target), "--json"]
            with mock.patch("builtins.print") as printer:
                self.assertEqual(cli(args), 2)
            failed = json.loads(printer.call_args.args[0])
            self.assertEqual(failed["error"]["code"], "invalid_visual_input")
            self.assertFalse(failed["ok"])
            self.assertFalse(failed["applied"])
            self.assertNotIn(folder, json.dumps(failed))
            self.assertFalse(target.exists())
            for invalid in (["--threshold", "256"], ["--threshold", "-1"]):
                with self.subTest(invalid=invalid), mock.patch("builtins.print") as printer:
                    self.assertEqual(cli(["de", "visual-compare", "--reference", str(ref),
                                          "--actual", str(ref), "--json", *invalid]), 2)
                    self.assertEqual(json.loads(printer.call_args.args[0])["error"]["code"],
                                     "invalid_visual_input")

    def test_visual_flags_are_isolated_from_other_de_actions(self):
        from macrice.cli import main as cli

        for arguments in (["de", "catalog", "--reference", "/tmp/not-used.png"],
                          ["de", "check", "--heatmap", "/tmp/not-used.png"],
                          ["de", "catalog", "--tolerance-radius", "1"],
                          ["de", "visual-compare", "--reference", "/tmp/a.png",
                           "--actual", "/tmp/b.png", "--baseline", "/tmp/gate.json",
                           "--threshold", "24"],
                          ["de", "visual-baseline", "--reference", "/tmp/a.png",
                           "--recipe", "classic", "--output", "/tmp/gate.json"],
                          ["de", "catalog", "--approve-reference"],
                          ["de", "review", "--recipe", "classic", "--threshold", "10"],
                          ["de", "visual-compare", "--actual", "/tmp/a.png"],
                          ["de", "visual-compare", "--reference", "/tmp/a.png",
                           "--actual", "/tmp/b.png", "--nested"],
                          ["de", "visual-compare", "--reference", "/tmp/a.png",
                           "--actual", "/tmp/b.png", "--panel", "native"]):
            with self.subTest(arguments=arguments), mock.patch("sys.stderr"):
                self.assertEqual(cli(arguments), 1)


if __name__ == "__main__":
    unittest.main()
