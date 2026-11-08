"""RiceBowl 0.7 migration, theming and launcher regression tests."""

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from macrice.installer import (_check_entrypoints, _write_entrypoints,
                               project_root, InstallationError)
from macrice.thunar import (_block, _legacy_block, PALETTES,
                           START, END, plan_css)


class RiceBowlReleaseTests(unittest.TestCase):
    def test_macos_css_remains_identical(self):
        for style in ("night", "day"):
            with self.subTest(style=style):
                self.assertEqual(_block(style), _legacy_block(style))

    def test_each_non_macos_thunar_style_is_distinct_and_scoped(self):
        styles = ("aero", "ten-dark", "ten-light", "winxp",
                  "winclassic", "chromeos", "frutiger")
        rendered = [_block(name) for name in styles]
        self.assertEqual(len(set(rendered)), len(styles))
        for name, css in zip(styles, rendered):
            with self.subTest(style=name):
                self.assertIn("window.thunar toolbar", css)
                self.assertIn("window.thunar .path-bar button", css)
                self.assertEqual(css.count(START), 1)
                self.assertEqual(css.count(END), 1)

    def test_legacy_06_css_upgrades_without_discarding_custom_css(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            css = root / "gtk-3.0" / "gtk.css"
            css.parent.mkdir(parents=True)
            user_rules = "/* user customization */\nlabel { font-weight: bold; }\n\n"
            css.write_text(user_rules + _legacy_block("winxp"))
            result = plan_css("frutiger", root)
            self.assertEqual(result["before"], css.read_text())
            self.assertEqual(result["after"], user_rules + _block("frutiger"))

    def test_user_edited_owned_block_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            css = root / "gtk-3.0" / "gtk.css"
            css.parent.mkdir(parents=True)
            css.write_text(_legacy_block("winxp").replace("#e0ecff", "#010101"))
            with self.assertRaisesRegex(ValueError, "customized"):
                plan_css("winxp", root)

    def test_ricebowl_icon_is_valid_svg(self):
        icon = project_root() / "assets/ricebowl-symbolic.svg"
        svg = ET.parse(icon).getroot()
        self.assertTrue(svg.tag.endswith("svg"))
        self.assertEqual(svg.attrib["viewBox"], "0 0 128 128")

    def test_new_launcher_and_legacy_commands_coexist(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with mock.patch("macrice.installer.bin_home", return_value=root / "bin"), \
                 mock.patch("macrice.installer.data_home", return_value=root / "data"):
                _write_entrypoints(project_root())
                _check_entrypoints()
                self.assertIn("hub", (root / "bin/ricebowl").read_text())
                self.assertIn("hub", (root / "bin/ricehub").read_text())
                self.assertTrue((root / "bin/macrice").exists())
                self.assertIn("Name=RiceBowl", (root / "data/applications/ricebowl.desktop").read_text())
                creator = (root / "data/applications/ricebowl-creator.desktop").read_text()
                self.assertIn("Name=Rice Creator", creator)
                self.assertIn('Exec="' + str(root / "bin/ricebowl") + '" creator', creator)
                self.assertIn("  creator)", (root / "bin/ricebowl").read_text())
                self.assertIn("NoDisplay=true", (root / "data/applications/ricehub.desktop").read_text())
                (root / "bin/ricebowl").write_text("#!/bin/sh\nexec /tmp/unmanaged\n")
                with self.assertRaises(InstallationError):
                    _check_entrypoints()


if __name__ == "__main__":
    unittest.main()
