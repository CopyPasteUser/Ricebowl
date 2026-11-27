"""The Creator keeps collapsed GtkExpander bodies out of the keyboard Tab chain.

Found by the real-labwc keyboard traversal (scripts/sg4_creator_gui_roundtrip_driver.py
`keyboard`): the bodies of the collapsed REFERENCE MAPPING / REGION QA expanders stayed in GTK's
focus chain, so Tab stopped five times on invisible controls (arrow keys then changed hidden
spin buttons).
"""
import re
import unittest
from pathlib import Path

import macrice.creator_gui as creator_gui

SOURCE = Path(creator_gui.__file__)


class CollapsedExpanderBodies(unittest.TestCase):
    def setUp(self):
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk
        except (ImportError, ValueError):
            self.skipTest("GTK introspection typelib is not installed")
        if not Gtk.init_check([])[0]:
            self.skipTest("GTK display is unavailable")
        self.Gtk = Gtk

    def build(self, expanded):
        Gtk = self.Gtk
        expander = Gtk.Expander(label="section")
        expander.set_expanded(expanded)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        usable = Gtk.Button(label="usable")
        unusable = Gtk.Button(label="own flag off")
        unusable.set_sensitive(False)
        body.pack_start(usable, False, False, 0)
        body.pack_start(unusable, False, False, 0)
        expander.add(body)
        creator_gui.keyboard_skips_collapsed(expander, body)
        return expander, body, usable, unusable

    def test_collapsed_body_is_not_focusable_and_expanding_restores_each_childs_own_state(self):
        expander, body, usable, unusable = self.build(False)
        self.assertFalse(body.get_sensitive())
        self.assertFalse(usable.is_sensitive(), "a collapsed section's control is still in the Tab chain")
        expander.set_expanded(True)
        self.assertTrue(usable.is_sensitive())
        self.assertFalse(unusable.is_sensitive(), "expanding must not enable a control that was disabled")
        expander.set_expanded(False)
        self.assertFalse(usable.is_sensitive())

    def test_an_initially_expanded_body_stays_usable(self):
        _expander, body, usable, _unusable = self.build(True)
        self.assertTrue(body.get_sensitive())
        self.assertTrue(usable.is_sensitive())

    def test_every_expander_in_the_creator_uses_the_helper(self):
        text = SOURCE.read_text(encoding="utf-8")
        expanders = len(re.findall(r"Gtk\.Expander\(", text))
        wired = len(re.findall(r"^\s+keyboard_skips_collapsed\(", text, flags=re.M))
        self.assertGreaterEqual(expanders, 8)
        self.assertEqual(wired, expanders,
                         "a Gtk.Expander in creator_gui.py is not wired to keyboard_skips_collapsed")


if __name__ == "__main__":
    unittest.main()
