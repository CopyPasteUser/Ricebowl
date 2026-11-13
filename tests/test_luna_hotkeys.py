"""Native XP Luna keybindings are private, bounded and reversible."""

import os
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from macrice.de import luna_hotkeys, recipes, session


ROOT = Path(__file__).resolve().parents[1]
LUNA = ROOT / "examples/wayland/xp-luna-columns.json"


class LunaHotkeyTests(unittest.TestCase):
    def test_exact_fixed_commands_and_no_shell_expansion(self):
        raw = (session.resources() / "labwc/rc.xml").read_text()
        result = luna_hotkeys.render(raw, True)
        commands = luna_hotkeys.commands(result)
        self.assertEqual(commands["W-d"], "riceplate-native --desktop-command show-desktop")
        self.assertEqual(commands["W-e"], "riceplate-native --desktop-command explorer")
        self.assertEqual(commands["W-r"], "riceplate-native --desktop-command run")
        self.assertEqual(commands["W-l"], "ricebowl de lock")
        self.assertEqual(commands["W-Return"], "foot")
        self.assertEqual(commands["Print"], "ricebowl de shot --clipboard")
        self.assertEqual(set(commands) - set(luna_hotkeys.commands(raw)),
                         {"W-d", "W-e", "W-r"})
        self.assertEqual(luna_hotkeys.render(result, True), result)
        # XML serialization deliberately discards the original declaration
        # and comments; compare effective bindings rather than whitespace.
        restored = luna_hotkeys.without_shortcuts(result)
        self.assertEqual(luna_hotkeys.commands(restored),
                         luna_hotkeys.commands(raw))
        self.assertEqual(luna_hotkeys.commands(luna_hotkeys.render(result, False)),
                         luna_hotkeys.commands(raw))
        # ET parser is never used to execute a recipe supplied string.
        self.assertNotIn("sh -c", result)
        self.assertNotIn("bash", result)

    def test_only_private_native_luna_session_receives_bindings(self):
        luna = recipes.parse(LUNA.read_bytes())
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            os.chmod(runtime, 0o700)
            classic = session._custom_labwc_config(None, temp, native_luna_hotkeys=True)
            waybar = session._custom_labwc_config(luna, temp, native_luna_hotkeys=False)
            native = session._custom_labwc_config(luna, temp, native_luna_hotkeys=True)
            for directory in (classic, waybar, native):
                self.assertEqual(directory.parent, runtime)
                self.assertTrue((directory / ".ricebowl-managed").is_file())
            for directory in (classic, waybar):
                cmds = luna_hotkeys.commands((directory / "rc.xml").read_text())
                self.assertNotIn("W-d", cmds)
                self.assertNotIn("W-r", cmds)
            rc = native / "rc.xml"
            self.assertEqual(rc.stat().st_mode & 0o777, 0o600)
            self.assertEqual(luna_hotkeys.commands(rc.read_text())["W-r"],
                             "riceplate-native --desktop-command run")
            session._cleanup_labwc_config({
                "RICEBOWL_DE_SESSION_CONFIG": str(native),
                "XDG_RUNTIME_DIR": temp,
            })
            self.assertFalse(native.exists())
            self.assertTrue(classic.exists())
            self.assertTrue(waybar.exists())

    def test_preferences_and_existing_session_bindings_survive_roundtrip(self):
        raw = (session.resources() / "labwc/rc.xml").read_text()
        root = ET.fromstring(raw)
        keyboard = root.find("keyboard")
        ET.SubElement(ET.SubElement(keyboard, "keybind", key="C-Home"),
                      "action", name="Execute", command="true")
        ET.SubElement(keyboard, "repeatRate").text = "37"
        custom = ET.tostring(root, encoding="unicode")
        compiled = luna_hotkeys.render(custom, True)
        restored = luna_hotkeys.without_shortcuts(compiled)
        self.assertEqual(luna_hotkeys.commands(restored)["C-Home"], "true")
        self.assertEqual(ET.fromstring(restored).findtext("keyboard/repeatRate"), "37")
        self.assertNotIn("W-d", luna_hotkeys.commands(restored))

    def test_bounded_and_invalid_session_xml_fails_closed(self):
        for content in ("<other/>", "<labwc_config><keyboard>", "a" * 70_000):
            with self.subTest(data=content[:30]), self.assertRaises(
                    (ValueError, ET.ParseError)):
                luna_hotkeys.render(content, True)


if __name__ == "__main__":
    unittest.main()
