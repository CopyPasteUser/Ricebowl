"""Exercise the published OS-inspired and original Creator recipes as data."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from macrice.de import recipes, review, pack


EXAMPLES = Path(__file__).resolve().parents[1] / "examples/wayland"


class CreatorExamplesTests(unittest.TestCase):
    def test_both_examples_use_the_exact_native_recipe_contract(self):
        fingerprints = set()
        for name in ("heritage-workstation", "orbit-atelier"):
            with self.subTest(name=name):
                path = EXAMPLES / f"{name}.json"
                data = json.loads(path.read_text(encoding="utf-8"))
                recipe = recipes.parse(path.read_bytes())
                self.assertEqual(recipe.recipe_id, name)
                self.assertEqual(recipe.schema_version, 5)
                self.assertEqual(set(data), {
                    "schema_version", "id", "name", "panel", "colors",
                    "menu", "desktop", "tokens", "responsive"})
                self.assertTrue(recipe.desktop_icons)
                self.assertTrue(recipe.layout)
                self.assertTrue(recipe.compact)
                self.assertEqual(
                    {icon.action for icon in recipe.desktop_icons},
                    {"applications", "terminal", "lock"},
                )
                self.assertEqual(
                    {action for group in recipe.menu[1] for action in group.actions},
                    {"applications", "terminal", "lock", "logout"},
                )
                fingerprints.add(review._semantic_hash(review._manifest(recipe)))
        self.assertEqual(len(fingerprints), 2)

    def test_examples_demonstrate_distinct_shell_compositions(self):
        classic = recipes.parse((EXAMPLES / "heritage-workstation.json").read_bytes())
        original = recipes.parse((EXAMPLES / "orbit-atelier.json").read_bytes())
        self.assertEqual(classic.position, "bottom")
        self.assertEqual(original.position, "top")
        self.assertNotEqual(classic.wallpaper, original.wallpaper)
        self.assertNotEqual(classic.layout, original.layout)
        self.assertNotEqual(classic.colors, original.colors)
        self.assertNotEqual(classic.compact, original.compact)

    def test_two_modern_examples_are_distinct_validated_v10_rices(self):
        classic = recipes.parse((EXAMPLES / "heritage-modern-v10.json").read_bytes())
        original = recipes.parse((EXAMPLES / "orbit-studio-v10.json").read_bytes())
        self.assertEqual((classic.schema_version, original.schema_version), (10, 10))
        self.assertEqual(classic.position, "bottom")
        self.assertEqual(original.position, "top")
        self.assertEqual(classic.menu_presentation, "tabs")
        self.assertEqual(original.menu_presentation, "sidebar")
        self.assertNotEqual(classic.layout, original.layout)
        self.assertNotEqual(classic.colors, original.colors)
        self.assertNotEqual(classic.compact, original.compact)
        self.assertNotEqual(classic.appearance, original.appearance)
        self.assertEqual((classic.appearance.font_scale, classic.appearance.font_weight),
                         (1, "regular"))
        self.assertEqual((original.appearance.font_scale, original.appearance.font_weight),
                         (2, "bold"))
        self.assertEqual(classic.composition.widgets[0].kind, "text")
        self.assertEqual(original.composition.widgets[0].kind, "text")
        self.assertTrue(all(comp.role in ("status", "action") for comp in classic.components))
        self.assertTrue(all(comp.role in ("status", "action") for comp in original.components))
        self.assertEqual({comp.binding for comp in classic.components if comp.role == "action"},
                         {"wifi-toggle"})
        self.assertEqual({comp.binding for comp in original.components if comp.role == "action"},
                         {"wifi-toggle"})
        self.assertNotEqual(review._semantic_hash(review._manifest(classic)),
                            review._semantic_hash(review._manifest(original)))
        for recipe in (classic, original):
            with self.subTest(recipe=recipe.recipe_id):
                wide, css = recipes.waybar_config(recipe, screen_width=1366)
                compact, _ = recipes.waybar_config(recipe, screen_width=640)
                status_module = ("pulseaudio" if recipe.recipe_id == "heritage-modern-v10"
                                 else "network")
                self.assertIn(f'"{status_module}"', wide)
                self.assertIn('"wlr/taskbar"', compact)
                self.assertNotIn('"on-click": "nmcli', wide)
                self.assertIn("window#waybar", css)

    def test_luna_columns_are_data_only_and_backwards_compatible(self):
        source = json.loads((EXAMPLES / "xp-luna-columns.json").read_text())
        recipe = recipes.parse(json.dumps(source).encode("utf-8"))
        self.assertEqual(recipe.recipe_id, "xp-luna-columns")
        self.assertEqual(recipe.schema_version, 12)
        self.assertEqual(recipe.menu_presentation, "columns")
        self.assertEqual([group.title for group in recipe.menu[1]],
                         ["Programs", "System", "Session"])
        legacy = recipes.parse((EXAMPLES / "xp-luna.json").read_bytes())
        self.assertEqual(legacy.menu_presentation, "sidebar")
        for mutate in (
            lambda data: data["menu"].update(presentation="unsupported"),
            lambda data: data.update(schema_version=11),
            lambda data: data["menu"]["groups"].pop(),
            lambda data: data["menu"]["groups"][1].update(content=[]),
            lambda data: data["menu"]["groups"][2]["actions"].append("audio-up"),
        ):
            modified = json.loads(json.dumps(source))
            mutate(modified)
            with self.assertRaises(recipes.RecipeError):
                recipes.parse(json.dumps(modified).encode("utf-8"))

    def test_modern_examples_roundtrip_as_safe_ricepacks(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            for name in ("heritage-modern-v10", "orbit-studio-v10"):
                with self.subTest(recipe=name):
                    source = Path(folder) / f"{name}.json"
                    source.write_bytes((EXAMPLES / f"{name}.json").read_bytes())
                    source.chmod(0o600)
                    archive = Path(folder) / f"{name}.ricepack"
                    pack.export_pack(str(source), archive)
                    inspected = pack.inspect_pack(archive)
                    self.assertTrue(inspected["ok"])
                    self.assertFalse(inspected["applied"])


if __name__ == "__main__":
    unittest.main()
