"""XP Luna system UI navigation and lifecycle regressions.

Real GTK cases run under Xvfb in CI. No desktop defaults or backend state are
changed; the renderer and service adapters are the production ones.
"""
from __future__ import annotations

import os
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from macrice.de import settings


class LunaSystemUXTests(unittest.TestCase):
    def test_worker_submission_race_releases_permit_without_fake_success(self):
        window = settings.RiceSpiceWindow.__new__(settings.RiceSpiceWindow)
        window.worker_slots = threading.BoundedSemaphore(1)
        window.executor = mock.Mock()
        window.executor.submit.side_effect = RuntimeError("executor closed")
        window.busy = False
        window.closed = False
        window.generation = 4
        window._state = mock.Mock()
        window._background(lambda: "ignored", lambda _result: None)
        self.assertFalse(window.busy)
        self.assertTrue(window.worker_slots.acquire(blocking=False))
        self.assertIn("closing", window._state.call_args.args[0])
        window.worker_slots.release()

    def test_luna_css_has_no_second_titlebar_and_keeps_native_focus_ring(self):
        css = settings.LUNA_CSS.decode("utf-8")
        self.assertIn("never a second window-manager caption", css)
        self.assertIn(".ricespice-luna button:focus", css)
        self.assertIn("outline-color: #f0a23b", css)
        self.assertNotIn("background-image: linear-gradient(to bottom, #2864b8", css)

    def test_real_gtk_history_back_forward_search_and_branching(self):
        try:
            Gtk, Gdk, GLib = settings._gtk_modules()
        except (ValueError, ImportError):
            self.skipTest("GTK3 unavailable")
        if not Gtk.init_check([])[0]:
            self.skipTest("Graphical GTK session unavailable")
        with tempfile.TemporaryDirectory() as private, \
             mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": private,
                                           "XDG_STATE_HOME": private}), \
             mock.patch.object(settings.RiceSpiceWindow, "_audio", autospec=True):
            window = settings.RiceSpiceWindow(Gtk, Gdk, GLib, page="home", luna=True)
            try:
                self.assertEqual(window.luna_history, [("home", "categories")])
                self.assertFalse(window.luna_back.get_sensitive())
                self.assertFalse(window.luna_forward.get_sensitive())
                window.show_category("sound")
                window.show_page("audio")
                self.assertEqual(window.page, "audio")
                self.assertEqual(window.luna_history[-2:], [
                    ("category", "sound"), ("audio", "")])
                window.luna_back.clicked()
                self.assertEqual(window.page, "category")
                self.assertIn("Sounds", window.breadcrumb.get_text())
                window.luna_back.clicked()
                self.assertEqual(window.page, "home")
                self.assertTrue(window.luna_forward.get_sensitive())
                window.luna_forward.clicked()
                self.assertEqual(window.page, "category")
                window.luna_forward.clicked()
                self.assertEqual(window.page, "audio")
                self.assertFalse(window.luna_forward.get_sensitive())

                # A new branch invalidates the stale forward history.
                window.luna_back.clicked()
                window.show_home()
                self.assertFalse(window.luna_forward.get_sensitive())

                window.search_entry.set_text("spea")
                window.search_entry.set_text("speaker")
                self.assertEqual(window.page, "search")
                self.assertEqual(window.luna_history[-1], ("search", "speaker"))
                self.assertEqual(window.luna_history.count(("search", "speaker")), 1)
                window.luna_back.clicked()
                self.assertEqual(window.page, "home")
                window.luna_forward.clicked()
                self.assertEqual(window.page, "search")
                self.assertEqual(window.search_entry.get_text(), "speaker")
                self.assertIn("audio", settings.luna_search_matches("speaker"))

                # History actions are explicit; keyboard shortcuts use them
                # but never dispatch a saved settings mutation.
                event = SimpleNamespace(keyval=Gdk.KEY_Left,
                     state=Gdk.ModifierType.MOD1_MASK)
                self.assertTrue(window._luna_key_press(window.window, event))
                self.assertEqual(window.page, "home")
                event.keyval = Gdk.KEY_Right
                self.assertTrue(window._luna_key_press(window.window, event))
                self.assertEqual(window.page, "search")
                for _ in range(40):
                    window.show_home()
                    window.show_category("sound")
                self.assertLessEqual(len(window.luna_history), 32)
            finally:
                GLib.timeout_add(30, lambda: (window.window.destroy(), False)[1])
                Gtk.main()
            self.assertTrue(window.closed)

    def test_x11_control_panel_real_category_navigation_and_history(self):
        try:
            Gtk, Gdk, GLib = settings._gtk_modules()
        except (ValueError, ImportError):
            self.skipTest("GTK3 unavailable")
        if not Gtk.init_check([])[0]:
            self.skipTest("Graphical GTK session unavailable")
        from macrice import luna_control_panel

        class Shell:
            _luna_settings_positioned = False
            def _class(self, widget, name):
                widget.get_style_context().add_class(name)
                return widget
            def _icon(self, _name, _size):
                return Gtk.Image.new_from_icon_name("preferences-system",
                                                    Gtk.IconSize.MENU)
            def _desktop_rect(self):
                return SimpleNamespace(x=0, y=0, width=1024, height=768)
            def _hide_actions(self):
                return None
            def _open_tool(self, _command):
                raise AssertionError("Navigation must not launch tools")
            def _action_key(self, _event):
                return False
            def _queue_volume_change(self, *_args):
                return None
            def _toggle_output_mute(self, *_args):
                return None

        shell = Shell()
        with mock.patch("macrice.window_geometry.restore_and_track", return_value=True):
            widget = luna_control_panel.build(shell, Gtk, Gdk)
        widget.show_all()
        try:
            self.assertFalse(shell.luna_control_back_tool.get_sensitive())
            shell.luna_control_show_category("Network and Internet Connections")
            self.assertEqual(shell.luna_control_stack.get_visible_child_name(), "detail")
            self.assertTrue(shell.luna_control_back_tool.get_sensitive())
            shell.luna_control_back_tool.clicked()
            self.assertEqual(shell.luna_control_stack.get_visible_child_name(), "categories")
            shell.luna_control_forward_tool.clicked()
            self.assertEqual(shell.luna_control_stack.get_visible_child_name(), "detail")
            shell.luna_control_search.set_text("mouse")
            self.assertEqual(shell.luna_control_stack.get_visible_child_name(), "search")
            shell.luna_control_back_tool.clicked()
            self.assertEqual(shell.luna_control_stack.get_visible_child_name(), "detail")
            shell.luna_control_forward_tool.clicked()
            self.assertEqual(shell.luna_control_stack.get_visible_child_name(), "search")
            self.assertEqual(shell.luna_control_search.get_text(), "mouse")
            shell.luna_control_show_home("classic")
            self.assertEqual(shell.luna_control_stack.get_visible_child_name(), "classic")
            self.assertFalse(shell.luna_control_forward_tool.get_sensitive())
            self.assertLessEqual(len(shell.luna_control_history), 32)
        finally:
            widget.destroy()

    def test_help_topics_open_real_control_panel_only_when_available(self):
        from macrice import luna_help, luna_control_panel
        self.assertEqual(
            set(luna_help.TOPIC_DESTINATIONS.values()) -
            set(luna_control_panel.LUNA_TASKS), set())
        self.assertEqual(luna_help.TOPIC_DESTINATIONS["Connecting to networks"],
                         "Network and Internet Connections")
        self.assertNotIn("Start menu", luna_help.TOPIC_DESTINATIONS)
        self.assertNotIn("No installed tool", luna_help.TOPIC_DESTINATIONS)

    def test_default_gtk_chrome_and_recipe_are_not_changed(self):
        self.assertIn(".ricespice-window", settings.CSS.decode())
        self.assertEqual(settings.LUNA_CONTROL_CATEGORIES[2][0], "sound")
        self.assertEqual(settings.luna_category_pages("sound"),
                         ("audio", "notifications"))


if __name__ == "__main__":
    unittest.main()
