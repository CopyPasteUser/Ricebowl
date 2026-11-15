"""Quick-action recipe is data-only and its command vocabulary is constrained."""

import json
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

from macrice.de import recipes


RECIPE = Path(__file__).parents[1] / "examples/wayland/quick-controls.json"


class NativeQuickActionsTests(unittest.TestCase):
    def test_bundled_quick_actions_load_through_recipe_validator(self):
        parsed = recipes.parse(RECIPE.read_bytes())
        self.assertEqual(parsed.schema_version, 4)
        self.assertEqual(parsed.menu[1][1].actions,
                         ("wifi-toggle", "audio-mute", "audio-up", "audio-down"))
        self.assertEqual(parsed.menu[1][2].actions,
                         ("notifications", "lock", "logout"))
        self.assertEqual(parsed.menu[1][3].actions, ("bluetooth-toggle",))
        root = ET.fromstring(recipes.labwc_menu(parsed)).find("menu")
        self.assertEqual([group.attrib["label"] for group in root.findall("menu")],
                         ["Applications", "Session"])

    def test_untrusted_custom_commands_are_never_a_valid_action(self):
        value = json.loads(RECIPE.read_text())
        value["menu"]["groups"][1]["actions"][0] = "sh -c nmcli networking off"
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(value).encode())

    def test_ricepop_is_native_only_and_not_a_recipe_defined_command(self):
        original = recipes.parse(RECIPE.read_bytes())
        xml = recipes.labwc_menu(original)
        self.assertNotIn("notifications", xml)
        self.assertNotIn("makoctl", xml)
        invalid = json.loads(RECIPE.read_text())
        invalid["menu"]["groups"][2]["actions"][0] = "makoctl dismiss --all"
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(invalid).encode())


if __name__ == "__main__":
    unittest.main()
