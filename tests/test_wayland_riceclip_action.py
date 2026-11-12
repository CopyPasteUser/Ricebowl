"""A single safe RiceClip action across Creator, Waybar, labwc and RicePlate.

The GTK browser is opt-in; a menu click must not start the clipboard watcher.
No test accesses or saves the host clipboard.
"""

import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from macrice.de import catalog, creator_schema, recipes

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/riceplate-clip-actions-v6.json"


class RiceClipActionContractTests(unittest.TestCase):
    def test_native_and_fallback_action_are_fixed_and_not_a_recipe_command(self):
        parsed = recipes.parse(FIXTURE.read_bytes())
        self.assertEqual(parsed.recipe_id, "riceclip-actions")
        self.assertIn("clip-history", {action for group in parsed.menu[1]
                                        for action in group.actions})
        self.assertIn("clip-history", recipes.PANEL_ACTIONS)
        self.assertIn("clip-history", recipes.MENU_ACTIONS)
        command = "ricebowl de clip --clip-op gui"
        self.assertEqual(recipes.PANEL_ACTION_COMMANDS["clip-history"], command)
        config, _css = recipes.waybar_config(parsed, screen_width=1366)
        modules = json.loads(config)
        buttons = [entry for entry in modules.values()
                   if isinstance(entry, dict) and entry.get("on-click") == command]
        self.assertEqual(len(buttons), 1)
        menu = ET.fromstring(recipes.labwc_menu(parsed))
        items = [item for item in menu.findall(".//item")
                 if item.get("label") == "RiceClip history"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].find("action").attrib,
                         {"name": "Execute", "command": command})

    def test_creator_discovers_action_on_existing_schema_without_new_scripts(self):
        schema = creator_schema.describe(6)
        operations = schema["properties"]["operations"]["items"]["oneOf"]
        paths = {entry["properties"]["path"].get("const"): entry for entry in operations}
        # The operation references the shared JSON Schema definition; the
        # allowlist belongs in $defs, not the operation's literal properties.
        self.assertEqual(paths["/panel/layout/start"]["properties"]["value"]["items"]["$ref"],
                         "#/$defs/layout1")
        self.assertIn("clip-history", json.dumps(schema["$defs"]))
        self.assertIn("clip-history", recipes.MENU_ACTIONS)
        native = next(item for item in catalog.describe()["shell_components"]
                      if item["id"] == "native-menu")
        self.assertIn("clip-history", native["actions"])

    def test_both_different_rices_offer_browser_without_replacing_other_actions(self):
        for name in ("xp-luna.json", "heritage-modern-v10.json"):
            with self.subTest(name=name):
                data = (ROOT / "examples/wayland" / name).read_bytes()
                parsed = recipes.parse(data)
                actions = {action for group in parsed.menu[1] for action in group.actions}
                self.assertIn("clip-history", actions)
                self.assertTrue({"applications", "terminal", "lock", "logout"} <= actions)
                if name == "xp-luna.json":
                    system = next(group for group in parsed.menu[1]
                                  if group.title == "System")
                    self.assertEqual(system.actions,
                                     ("settings", "notifications", "clip-history"))
                    # Native composition must have a visible slot for the
                    # third action, not merely accept the hidden binding.
                    self.assertEqual(system.content[0].limit, 3)

    def test_invalid_commands_and_non_allowlisted_ids_fail_closed(self):
        original = json.loads(FIXTURE.read_text())
        for malformed in ("clip-history;sh", "clip-history --watch", "exec", "clip_history"):
            with self.subTest(action=malformed):
                data = json.loads(json.dumps(original))
                data["panel"]["layout"]["start"][0]["children"][1]["id"] = malformed
                with self.assertRaises(recipes.RecipeError):
                    recipes.parse(json.dumps(data).encode())
        data = json.loads(FIXTURE.read_text())
        data["panel"]["layout"]["start"][0]["children"][1]["exec"] = "sh"
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(data).encode())
        data = json.loads(FIXTURE.read_text())
        data["menu"]["groups"][1]["actions"][-1] = "clip-history;sh"
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(data).encode())


if __name__ == "__main__":
    unittest.main()
