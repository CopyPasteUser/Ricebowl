"""Rice Creator must fit a 1366x768 output once a draft is loaded (SG4 WP4.2).

Found by the real-labwc Creator smoke: with a draft loaded the unscrolled editing
panes demanded about 1530x1030 px, so the window ran past the right and bottom
edges of a 1366x768 output (the right inspector and the toolbar's Render/Export
buttons were clipped). The panes now scroll; toolbar and status line stay fixed.
Skips without GTK or a display.
"""
import os
import tempfile
import time
import unittest
from unittest import mock

from macrice import creator_gui


class InitialSizeTests(unittest.TestCase):
    def test_default_is_clamped_to_the_output_but_never_below_the_minimum_request(self):
        self.assertEqual(creator_gui.initial_window_size(1920, 1080), (1280, 820))
        self.assertEqual(creator_gui.initial_window_size(1366, 768), (1280, 696))
        self.assertEqual(creator_gui.initial_window_size(1280, 720), (1256, 648))
        self.assertEqual(creator_gui.initial_window_size(800, 600), (820, 560))


class DraftWindowFitsTests(unittest.TestCase):
    def setUp(self):
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            from gi.repository import GLib, Gtk
        except (ImportError, ValueError):
            self.skipTest("GTK introspection typelib is not installed")
        if not Gtk.init_check([])[0]:
            self.skipTest("GTK display is unavailable")
        self.Gtk, self.GLib = Gtk, GLib
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = mock.patch.dict(os.environ, {
            "XDG_STATE_HOME": tmp.name + "/state", "XDG_CONFIG_HOME": tmp.name + "/config",
            "XDG_DATA_HOME": tmp.name + "/data", "XDG_CACHE_HOME": tmp.name + "/cache"})
        env.start()
        self.addCleanup(env.stop)

    def pump(self, limit=300):
        context = self.GLib.MainContext.default()
        for _ in range(limit):
            while context.pending():
                context.iteration(False)
            time.sleep(0.002)

    def test_minimum_size_with_a_draft_fits_a_1366x768_output(self):
        results = {}

        def fake_run(app, _argv):
            app.emit("activate")
            window = next(item for item in self.Gtk.Window.list_toplevels()
                          if item.get_title() == "Rice Creator · RiceBowl")
            try:
                window._create("heritage-composer")
                self.pump()
                self.assertIsNotNone(window.info, "the template draft did not load")
                results["width"] = window.get_preferred_width().minimum_width
                results["height"] = window.get_preferred_height().minimum_height
                scroller = window.main.get_ancestor(self.Gtk.ScrolledWindow)
                results["scrolled"] = scroller is not None
                results["menu_items_visible"] = all(
                    button.get_visible() for button in (window.install_btn, window.fork_btn,
                                                        window.apply_btn, window.restore_btn))
                results["direction"] = window.wayland_btn.get_direction()
                results["position"] = window.wayland_menu.get_position()
                # Toolbar actions and the status line must stay reachable (fixed).
                results["fixed"] = all(widget.get_ancestor(self.Gtk.ScrolledWindow) is None
                                       for widget in (window.save_btn, window.render_btn,
                                                      window.export_btn, window.status))
            finally:
                window.destroy()
            return 0

        with mock.patch.object(self.Gtk.Application, "run", fake_run):
            creator_gui.run()
        self.assertTrue(results["scrolled"], "editing panes must scroll")
        self.assertTrue(results["fixed"], "toolbar and status must stay outside the scroller")
        self.assertTrue(results["menu_items_visible"],
                        "the Install / switch popover content was never shown (empty bubble)")
        # The handoff menu button is at the foot of the sidebar: it must open upward.
        self.assertEqual(results["direction"], self.Gtk.ArrowType.UP)
        self.assertEqual(results["position"], self.Gtk.PositionType.TOP)
        self.assertLessEqual(results["width"], 1366, results)
        self.assertLessEqual(results["height"], 768 - 72, results)


if __name__ == "__main__":
    unittest.main()
