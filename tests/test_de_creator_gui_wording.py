"""SG7 WP7.3: Rice Creator's user-visible unavailable/error wording, in a real window.

``creator_gui.run()`` builds the real ``CreatorWindow``; only
``Gtk.Application.run`` is replaced so the test can drive the window it made.
The backends that would fail (live session, interactive preview, renderer,
reference store) are replaced by raising their real error types. Skips without
GTK or a display.
"""
import os
import tempfile
import time
import unittest
from unittest import mock

from macrice import creator_gui
from macrice.de import creator_activation, creator_interactive, creator_reference


class CreatorWordingTests(unittest.TestCase):
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

    def pump(self, condition, limit=600):
        context = self.GLib.MainContext.default()
        for _ in range(limit):
            while context.pending():
                context.iteration(False)
            if condition():
                return True
            time.sleep(0.005)
        return condition()

    def with_window(self, body):
        def fake_run(app, _argv):
            app.emit("activate")
            window = next(item for item in self.Gtk.Window.list_toplevels()
                          if item.get_title() == "Rice Creator \u00b7 RiceBowl")
            try:
                body(window)
            finally:
                window.destroy()
            return 0

        with mock.patch.object(self.Gtk.Application, "run", fake_run):
            creator_gui.run()

    def test_native_preview_failure_says_editing_still_works_and_is_an_error(self):
        def body(window):
            window._render_generation = 3
            window._render_complete(3, None, None, "labwc is not installed")
            self.assertEqual(window.preview_caption.get_text(),
                             "Native preview unavailable. Draft editing still works.")
            self.assertEqual(window.status.get_text(),
                             "Render failed: labwc is not installed. "
                             "Check labwc, grim and native RicePlate.")
            self.assertIn("creator-error", window.status.get_style_context().list_classes())

        self.with_window(body)

    def test_live_change_unavailable_is_shown_and_clears_busy(self):
        def body(window):
            with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-test"}), \
                    mock.patch.object(creator_activation, "inspect_restore",
                                      side_effect=creator_activation.ActivationError(
                                          "No live RiceBowl session")):
                window._live_action("restore")
                self.assertTrue(self.pump(lambda: window.status.get_text() ==
                                          "Live change unavailable: No live RiceBowl session"),
                                window.status.get_text())
            self.assertFalse(window._busy)
            self.assertIn("creator-error", window.status.get_style_context().list_classes())

        self.with_window(body)

    def test_interactive_test_unavailable_is_shown_and_starts_nothing(self):
        def body(window):
            window._create("heritage")
            self.assertIsNotNone(window.info)
            with mock.patch.object(creator_interactive, "launch",
                                   side_effect=creator_interactive.InteractivePreviewError(
                                       "A graphical display is required")):
                window._interactive(None)
            self.assertEqual(window.status.get_text(),
                             "Interactive test unavailable: A graphical display is required")
            self.assertIsNone(window._interactive_session)

        self.with_window(body)

    def test_missing_reference_is_stated_and_asks_for_a_new_png(self):
        def body(window):
            window._create("heritage")
            with mock.patch.object(creator_reference, "selected",
                                   side_effect=creator_reference.ReferenceError(
                                       "reference image changed")):
                window._load(window.info, reset_history=True)
            self.assertEqual(window.reference_info.get_text(),
                             "Reference unavailable: reference image changed. "
                             "Select a new PNG.")

        self.with_window(body)


if __name__ == "__main__":
    unittest.main()
