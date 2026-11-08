"""Schema-v6 panel buttons have real, strictly allowlisted native and fallback bindings."""

import json
import tempfile
import unittest
from pathlib import Path

from macrice.de import catalog, drafts, recipes, review


FIXTURE = Path(__file__).parent / "fixtures/riceplate-actions-v6.json"


class PanelActionTests(unittest.TestCase):
    def test_native_and_waybar_share_safe_action_recipe(self):
        data = json.loads(FIXTURE.read_text())
        parsed = recipes.parse(FIXTURE.read_bytes())
        self.assertEqual(parsed.schema_version, 6)
        self.assertEqual(review._manifest(parsed), data)
        self.assertEqual(parsed.sections[0], ("launcher", "tasks"))
        normal, normal_css = recipes.waybar_config(parsed, screen_width=1280)
        wide = json.loads(normal)
        buttons = [value for key, value in wide.items() if key.startswith("custom/rice-action-")]
        self.assertEqual({item["on-click"] for item in buttons},
                         {"foot", "ricebowl de settings"})
        self.assertTrue(all("exec" not in item for item in buttons))
        self.assertIn("border-radius: 6px", normal_css)
        compact, _ = recipes.waybar_config(parsed, screen_width=600)
        compact_buttons = [value for key, value in json.loads(compact).items()
                           if key.startswith("custom/rice-action-")]
        self.assertEqual([item["on-click"] for item in compact_buttons],
                         ["ricebowl de settings"])

    def test_rejects_unknown_scripts_labels_and_unsupported_legacy_schema(self):
        original = json.loads(FIXTURE.read_text())
        invalid = [
            {"type": "action", "id": "bash -c echo owned", "label": "Tools"},
            {"type": "action", "id": "logout", "label": "Logout"},
            {"type": "action", "id": "terminal", "label": "<unsafe>"},
            {"type": "action", "id": "terminal", "label": "A" * 17},
            {"type": "action", "id": "terminal", "label": "Terminal", "command": "echo 1"},
            {"type": "action", "id": "terminal", "label": None},
        ]
        for node in invalid:
            with self.subTest(node=node):
                data = json.loads(FIXTURE.read_text())
                data["panel"]["layout"]["start"][0]["children"][1] = node
                with self.assertRaises(recipes.RecipeError):
                    recipes.parse(json.dumps(data).encode())
        original["schema_version"] = 5
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(original).encode())

    def test_duplicate_actions_and_compact_label_drift_fail_closed(self):
        data = json.loads(FIXTURE.read_text())
        data["panel"]["layout"]["end"].append(
            {"type": "action", "id": "terminal", "label": "Terminal"})
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(data).encode())
        data = json.loads(FIXTURE.read_text())
        data["responsive"]["compact_layout"]["end"][0]["label"] = "Prefs"
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(data).encode())

    def test_catalog_declares_fixed_action_binding_without_custom_commands(self):
        info = catalog.describe()
        node = info["recipe"]["nested_layout"]["node_types"]["action"]
        self.assertEqual(node["known_ids"], sorted(recipes.PANEL_ACTIONS))
        self.assertTrue(node["interactive"])
        self.assertEqual(node["since_schema"], 6)
        self.assertEqual(node["max_characters"], 16)
        self.assertFalse(info["recipe"]["custom_commands"])

    def test_creator_draft_edits_revalidate_action_nodes_and_legacy_rejects(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = root / "recipe.json"
            patch = root / "edit.json"
            output = root / "edited.json"
            original.write_bytes(FIXTURE.read_bytes())
            original.chmod(0o600)
            patch.write_text(json.dumps({"edit_version": 1, "operations": [{
                "op": "set", "path": "/panel/layout/end", "value": [
                    {"type": "action", "id": "lock", "label": "Lock"},
                    {"type": "widget", "id": "clock"},
                ],
            }]}))
            draft = drafts.create_edit(recipe_token=str(original), edit_source=patch,
                                       destination=output)
            self.assertEqual(draft["recipe_id"], "mockup-actions")
            self.assertEqual(review._manifest(recipes.load(str(output)))["panel"]["layout"]["end"][0],
                             {"type": "action", "id": "lock", "label": "Lock"})
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            data = json.loads(FIXTURE.read_text())
            data["schema_version"] = 5
            data["panel"]["layout"]["start"][0]["children"].pop(1)
            data["panel"]["layout"]["end"].pop(0)
            data["responsive"]["compact_layout"]["end"].pop(0)
            data["responsive"]["compact_layout"]["end"].append(
                {"type": "widget", "id": "clock"})
            original.write_text(json.dumps(data))
            with self.assertRaises(drafts.DraftError):
                drafts.create_edit(recipe_token=str(original), edit_source=patch,
                                   destination=root / "legacy.json")


if __name__ == "__main__":
    unittest.main()
