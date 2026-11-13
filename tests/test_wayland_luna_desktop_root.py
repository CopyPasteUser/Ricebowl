"""XP Luna desktop root menu must execute only fixed native IPC requests."""
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from macrice.de import recipes

ROOT = Path(__file__).resolve().parents[1]


class LunaDesktopRootMenuTest(unittest.TestCase):
    def test_only_luna_exposes_fixed_real_desktop_actions(self):
        luna = recipes.parse((ROOT / "examples/wayland/xp-luna-columns.json").read_bytes())
        xml = ET.fromstring(recipes.labwc_menu(luna))
        group = xml.find(".//menu[@id='rice-luna-desktop']")
        self.assertIsNotNone(group)
        assert group is not None
        commands = [(node.get("label"), node.find("action").get("command"))
                    for node in group.findall("item")]
        self.assertEqual(commands, [
            ("Arrange Icons", "riceplate-native --desktop-command arrange"),
            ("New Folder", "riceplate-native --desktop-command new-folder"),
            ("Refresh", "riceplate-native --desktop-command refresh"),
            ("Properties", "riceplate-native --desktop-command properties"),
        ])
        self.assertTrue(all(node.find("action").get("name") == "Execute"
                            for node in group.findall("item")))
        generic = recipes.parse((ROOT / "macrice/de/resources/recipes/classic.json").read_bytes())
        if generic.menu is not None:
            self.assertIsNone(ET.fromstring(recipes.labwc_menu(generic))
                              .find(".//menu[@id='rice-luna-desktop']"))

    def test_native_quick_launch_actions_preserve_parser_and_rice_boundaries(self):
        parsed = recipes.parse((ROOT / "examples/wayland/xp-luna-columns.json").read_bytes())
        nodes = parsed.layout
        text = str(nodes)
        for name in ("show-desktop", "applications", "terminal"):
            self.assertIn(name, text)
        self.assertNotIn("rm -rf", recipes.labwc_menu(parsed))


if __name__ == "__main__":
    unittest.main()
