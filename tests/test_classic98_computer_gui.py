"""Native GTK/X11 smoke for Windows 98 Computer's second-click workflow."""

from __future__ import annotations

import os
import unittest


class Classic98ComputerGuiTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("DISPLAY"), "Requires real X11/Xvfb")
    def test_search_open_and_close_computer_browser(self):
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk, Gio
        ready = Gtk.init_check()
        if isinstance(ready, tuple):
            ready = ready[0]
        if not ready:
            self.skipTest("GTK display unavailable")

        from macrice.classic98_computer import show
        parent = Gtk.Window()

        class Shell:
            bar = parent
            _classic98_computer_dialog = None
            was_hidden = False
            opened = []

            def _hide_menu(self):
                self.was_hidden = True

            def _open_uri(self, uri):
                self.opened.append(uri)

        def descendants(widget):
            yield widget
            if isinstance(widget, Gtk.Container):
                for child in widget.get_children():
                    yield from descendants(child)

        shell = Shell()
        dialog = None
        try:
            dialog = show(shell, Gtk, Gio)
            self.assertTrue(shell.was_hidden)
            self.assertIs(show(shell, Gtk, Gio), dialog,
                          "Second invocation should present the existing window")
            widgets = list(descendants(dialog))
            search = next(w for w in widgets if isinstance(w, Gtk.SearchEntry))
            tree = next(w for w in widgets if isinstance(w, Gtk.TreeView))
            search.set_text("File System")
            self.assertEqual(len(tree.get_model()), 1)
            self.assertEqual(tree.get_model()[0][0], "File System")
            tree.get_selection().select_path(0)
            open_button = dialog.get_widget_for_response(Gtk.ResponseType.OK)
            self.assertTrue(open_button.get_sensitive())
            dialog.response(Gtk.ResponseType.OK)
            self.assertEqual(shell.opened, ["file:///"])
            dialog.response(Gtk.ResponseType.CLOSE)
            self.assertIsNone(shell._classic98_computer_dialog)
        finally:
            if shell._classic98_computer_dialog is not None:
                shell._classic98_computer_dialog.destroy()
            parent.destroy()


if __name__ == "__main__":
    unittest.main()
