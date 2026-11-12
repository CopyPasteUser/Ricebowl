"""XP Luna Wayland rice: data-only styling, safe action bindings and schema parity."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from macrice.de import catalog, creator_schema, drafts, recipes, review


LUNA = Path(__file__).resolve().parents[1] / "examples/wayland/xp-luna.json"


class WaylandLunaTests(unittest.TestCase):
    def setUp(self):
        self.source = json.loads(LUNA.read_text(encoding="utf-8"))

    def test_real_luna_recipe_roundtrips_and_preserves_x11(self):
        parsed = recipes.parse(LUNA.read_bytes())
        self.assertEqual(parsed.recipe_id, "xp-luna")
        self.assertEqual(parsed.schema_version, 12)
        self.assertEqual(review._manifest(parsed), self.source)
        self.assertEqual(parsed.launcher.label, "start")
        self.assertEqual(parsed.launcher.background, "#398c29")
        self.assertEqual(parsed.menu_palette.background, "#fffdf1")
        self.assertEqual(parsed.colors[0], "#245ed3")
        self.assertTrue(recipes.wallpaper_path(parsed).is_file())
        self.assertEqual(recipes.wallpaper_path(parsed).name, "luna-hills.jpg")
        self.assertEqual(parsed.menu_presentation, "sidebar")
        self.assertTrue({"applications", "terminal", "lock", "logout"}.issubset({
            action for group in parsed.menu[1] for action in group.actions
        }))
        self.assertEqual(parsed.compact[0], 1024)

    def test_columns_recipe_and_creator_contract(self):
        path = LUNA.with_name("xp-luna-columns.json")
        parsed = recipes.parse(path.read_bytes())
        self.assertEqual(parsed.recipe_id, "xp-luna-columns")
        self.assertEqual(parsed.menu_presentation, "columns")
        self.assertEqual(review._manifest(parsed),
                         json.loads(path.read_text(encoding="utf-8")))
        self.assertEqual([item.title for item in parsed.menu[1]],
                         ["Programs", "Places", "Session"])
        self.assertEqual(parsed.menu[1][1].actions,
                         ("documents", "computer", "pictures", "music", "settings", "notifications",
                          "help", "run"))
        self.assertEqual(len(parsed.desktop_icons), 7)
        self.assertEqual([icon.action for icon in parsed.desktop_icons], [
            "computer", "documents", "network", "trash",
            "applications", "terminal", "lock",
        ])
        self.assertEqual(next(icon.label for icon in parsed.desktop_icons
                              if icon.action == "trash"), "Recycle Bin")
        schema = creator_schema.describe(12)
        properties = schema["properties"]["operations"]["items"]["oneOf"]
        edit = {operation["properties"]["path"]["const"]: operation
                for operation in properties if "const" in operation["properties"]["path"]}
        icon_actions = edit["/desktop/icons"]["properties"]["value"]["items"][
            "properties"]["action"]["enum"]
        self.assertTrue({"trash", "computer", "documents", "network"} <= set(icon_actions))
        # The native trash art is drawn in-engine, not an arbitrary fourth
        # imported image that the three-slot Rust artwork loader cannot read.
        artwork_keys = set(edit["/artwork/icons"]["properties"]["value"]["properties"])
        self.assertEqual(artwork_keys, {"applications", "terminal", "lock"})
        self.assertNotIn("/artwork/icons/trash", edit)
        invalid_icon = json.loads(path.read_text(encoding="utf-8"))
        invalid_icon["desktop"]["icons"][-1]["action"] = "trash; rm -rf"
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(invalid_icon).encode("utf-8"))
        # Ten right-side hits fit; a third session action must still fail.
        self.assertTrue({"pictures", "music", "run", "help"} <= recipes.MENU_ACTIONS)
        self.assertFalse({"pictures", "music"} & recipes.ICON_ACTIONS)
        self.assertEqual(edit["/menu/groups"]["properties"]["value"]
                         ["items"]["properties"]["actions"]["maxItems"], 8)
        overflowing = json.loads(path.read_text(encoding="utf-8"))
        overflowing["menu"]["groups"][2]["actions"] = [
            "lock", "logout", "wifi-toggle", "audio-mute"]
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(overflowing).encode("utf-8"))
        unthemed = json.loads(path.read_text(encoding="utf-8"))
        del unthemed["menu"]["colors"]
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(unthemed).encode("utf-8"))
        self.assertEqual(catalog.describe()["recipe"]["schema_versions"][-1], 12)
        self.assertIn("columns", catalog.describe()["recipe"]["menu"]["presentation"]["variants"]
                      if "menu" in catalog.describe()["recipe"] else
                      json.dumps(catalog.describe()))
        edit_schema = creator_schema.describe(12)
        previous = creator_schema.describe(11)
        def presentation_values(schema):
            variants = schema["properties"]["operations"]["items"]["oneOf"]
            return next(item["properties"]["value"]["enum"] for item in variants
                        if item["properties"]["path"].get("const") == "/menu/presentation")
        self.assertIn("columns", presentation_values(edit_schema))
        self.assertNotIn("columns", presentation_values(previous))
        self.assertTrue(drafts._allowed_value("/menu/presentation", "columns", 12))
        self.assertFalse(drafts._allowed_value("/menu/presentation", "columns", 11))

    def test_waybar_fallback_keeps_real_click_and_separate_task_colors(self):
        parsed = recipes.parse(LUNA.read_bytes())
        wide, css = recipes.waybar_config(parsed, screen_width=1366)
        compact, small_css = recipes.waybar_config(parsed, screen_width=800)
        self.assertEqual(json.loads(wide)["custom/rice-launcher"]["format"], "start")
        self.assertEqual(json.loads(wide)["custom/rice-launcher"]["on-click"], "fuzzel")
        self.assertIn("background: #398c29", css)
        self.assertIn("#taskbar button.active { background: #17469b; }", css)
        self.assertIn("border-radius: 16px", css)
        self.assertIn("background: #398c29", small_css)
        self.assertIn("battery", json.dumps(json.loads(compact)["modules-right"]))
        self.assertNotIn("network", json.dumps(json.loads(compact)["modules-right"]))

    def test_v12_visual_fields_are_bounded_and_forbidden_in_v11(self):
        self.assertEqual(catalog.describe()["recipe"]["schema_versions"][-1], 12)
        bad = copy.deepcopy(self.source)
        bad["schema_version"] = 11
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(bad).encode())
        for path, value in (
            (("panel", "launcher", "label"), "start; /bin/sh"),
            (("panel", "launcher", "radius"), 21),
            (("panel", "launcher", "background"), "url(file:///etc/passwd)"),
            (("menu", "colors", "foreground"), "#zzzzzz"),
            (("menu", "colors", "selection"), None),
        ):
            with self.subTest(path=path):
                data = copy.deepcopy(self.source)
                data[path[0]][path[1]][path[2]] = value
                with self.assertRaises(recipes.RecipeError):
                    recipes.parse(json.dumps(data).encode())

    def test_creator_can_validate_style_edit_without_installing(self):
        parsed = recipes.parse(LUNA.read_bytes())
        visual_schema = creator_schema.describe(12)
        self.assertEqual(visual_schema["x-ricebowl-recipe-version"], 12)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "luna.json"
            edit = Path(directory) / "edit.json"
            source.write_bytes(LUNA.read_bytes())
            source.chmod(0o600)
            edit.write_text(json.dumps({"edit_version": 1, "operations": [
                {"op": "set", "path": "/panel/launcher/background", "value": "#2c8d23"}
            ]}), encoding="utf-8")
            edit.chmod(0o600)
            report = drafts.check_edit(recipe_token=str(source), edit_source=edit)
            self.assertTrue(report["ok"])
            self.assertFalse(report["applied"])
            self.assertEqual(parsed.launcher.background, "#398c29")


if __name__ == "__main__":
    unittest.main()
