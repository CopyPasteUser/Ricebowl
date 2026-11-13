"""Luna Wayland Control Panel routing tests (no GTK or physical hardware required)."""

import unittest
from unittest import mock

from macrice.cli import main
from macrice.de import settings


class WaylandLunaSettingsTests(unittest.TestCase):
    def test_luna_control_panel_categories_are_unique_and_have_real_backends(self):
        keys = [name for name, _title, _help in settings.LUNA_SECTIONS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertIn("taskbar", keys)
        self.assertTrue(set(keys) - {"taskbar"} <=
                        {name for name, _title, _help in settings.SECTIONS})
        self.assertEqual(set(keys), set(settings.LUNA_ICONS))
        self.assertEqual(set(keys), set(settings.LUNA_ICON_FILES))
        for asset in settings.LUNA_ICON_FILES.values():
            self.assertTrue((settings.LUNA_ICON_DIR / asset).is_file(), asset)

    def test_luna_groups_cover_each_real_category_exactly_once(self):
        grouped = [key for _name, keys in settings.LUNA_GROUPS for key in keys]
        catalog = [key for key, _title, _description in settings.LUNA_SECTIONS]
        self.assertEqual(len(grouped), len(set(grouped)))
        self.assertEqual(set(grouped), set(catalog))

    def test_luna_search_uses_titles_descriptions_and_keys(self):
        self.assertEqual(settings.luna_search_matches(""), tuple(
            key for key, _title, _desc in settings.LUNA_SECTIONS))
        self.assertIn("audio", settings.luna_search_matches("sound"))
        self.assertIn("displays", settings.luna_search_matches("scaling"))
        self.assertIn("taskbar", settings.luna_search_matches("start menu"))
        self.assertIn("network", settings.luna_search_matches("WI-FI"))
        self.assertIn("network", settings.luna_search_matches("wifi"))
        self.assertIn("taskbar", settings.luna_search_matches("clock format"))
        self.assertIn("taskbar", settings.luna_search_matches("12h"))
        self.assertIn("taskbar", settings.luna_search_matches("24-hour"))
        self.assertNotIn("audio", settings.luna_search_matches("clock format"))
        self.assertEqual(settings.luna_search_matches("unavailable_fake_page"), ())

    def test_luna_without_page_opens_overview(self):
        with mock.patch("macrice.de.settings.launch") as launch:
            self.assertEqual(main(["de", "settings", "--luna"]), 0)
            launch.assert_called_once_with(page="home", luna=True)

    def test_luna_settings_page_routes_to_real_on_demand_window(self):
        with mock.patch("macrice.de.settings.launch") as launch:
            self.assertEqual(main(["de", "settings", "--luna", "--page", "audio"]), 0)
            launch.assert_called_once_with(page="audio", luna=True)

    def test_default_settings_keep_existing_presentation(self):
        with mock.patch("macrice.de.settings.launch") as launch:
            self.assertEqual(main(["de", "settings"]), 0)
            launch.assert_called_once_with()

    def test_luna_flags_do_not_leak_into_other_de_commands(self):
        with mock.patch("macrice.de.settings.launch") as launch:
            self.assertNotEqual(main(["de", "check", "--luna"]), 0)
            self.assertNotEqual(main(["de", "check", "--page", "audio"]), 0)
            launch.assert_not_called()

    def test_luna_home_is_a_real_control_panel_route(self):
        # The selector still rejects unsupported external pages.
        with mock.patch("macrice.de.settings._gtk_modules", side_effect=ImportError):
            with self.assertRaises(settings.backend.SettingsError) as error:
                settings.launch(page="home", luna=True)
        self.assertIn("GTK3", str(error.exception))

    def test_luna_gtk_home_search_and_back_navigation(self):
        try:
            Gtk, Gdk, GLib = settings._gtk_modules()
        except (ImportError, ValueError):
            self.skipTest("GTK introspection typelib unavailable")
        if not Gtk.init_check([])[0]:
            self.skipTest("GTK display unavailable")
        window = settings.RiceSpiceWindow(Gtk, Gdk, GLib, page="home", luna=True)
        self.assertEqual(window.page, "home")
        self.assertEqual(len(window.nav_buttons), len(settings.LUNA_SECTIONS))
        window.search_entry.set_text("start menu")
        self.assertEqual(window.page, "search")
        self.assertTrue(window.nav_buttons["taskbar"].get_visible())
        self.assertFalse(window.nav_buttons["bluetooth"].get_visible())
        window.nav_buttons["taskbar"].clicked()
        self.assertEqual(window.page, "taskbar")
        self.assertEqual(window.search_entry.get_text(), "")
        self.assertTrue(window.nav_buttons["bluetooth"].get_visible())
        window.show_home()
        self.assertEqual(window.page, "home")
        GLib.timeout_add(30, lambda: (window.window.destroy(), False)[1])
        Gtk.main()
        self.assertTrue(window.closed)

    def test_luna_search_enter_and_shortcuts_in_real_gtk(self):
        try:
            Gtk, Gdk, GLib = settings._gtk_modules()
        except (ImportError, ValueError):
            self.skipTest("GTK introspection typelib unavailable")
        if not Gtk.init_check([])[0]:
            self.skipTest("GTK display unavailable")
        window = settings.RiceSpiceWindow(Gtk, Gdk, GLib, page="home", luna=True)
        try:
            window.search_entry.set_text("sound")
            self.assertEqual(window.page, "search")
            window.search_entry.emit("activate")
            self.assertEqual(window.page, "audio")
            self.assertEqual(window.search_entry.get_text(), "")

            # Empty Enter must not select arbitrary settings.
            window.search_entry.emit("activate")
            self.assertEqual(window.page, "audio")

            from types import SimpleNamespace
            shortcut = SimpleNamespace(keyval=Gdk.KEY_f,
                                       state=Gdk.ModifierType.CONTROL_MASK)
            self.assertTrue(window._luna_key_press(window.window, shortcut))
            self.assertTrue(window.search_entry.is_focus())

            # Unmatched queries must not navigate or execute anything.
            window.search_entry.set_text("missing-page-xyz")
            self.assertEqual(window.page, "search")
            window.search_entry.emit("activate")
            self.assertEqual(window.page, "search")

            escape = SimpleNamespace(keyval=Gdk.KEY_Escape, state=0)
            self.assertTrue(window._luna_key_press(window.window, escape))
            self.assertEqual(window.page, "home")
            self.assertEqual(window.search_entry.get_text(), "")
            self.assertFalse(window._luna_key_press(window.window, escape))
        finally:
            GLib.timeout_add(30, lambda: (window.window.destroy(), False)[1])
            Gtk.main()
        self.assertTrue(window.closed)

    def test_taskbar_clock_format_only_saves_after_explicit_apply(self):
        try:
            Gtk, Gdk, GLib = settings._gtk_modules()
        except (ImportError, ValueError):
            self.skipTest("GTK introspection typelib unavailable")
        if not Gtk.init_check([])[0]:
            self.skipTest("GTK display unavailable")

        with mock.patch("macrice.de.luna_panel_settings.load",
                        return_value={"clock_format": "24h"}), \
             mock.patch("macrice.de.luna_panel_settings.save",
                        return_value={"clock_format": "12h"}) as saved:
            window = settings.RiceSpiceWindow(Gtk, Gdk, GLib, page="taskbar", luna=True)
            window._background = lambda work, done: done(work())
            choices = [child for child in window.content.get_children()
                       if isinstance(child, Gtk.ComboBoxText)]
            self.assertEqual(len(choices), 1)
            combo = choices[0]

            def buttons(widget):
                found = []
                if isinstance(widget, Gtk.Button):
                    found.append(widget)
                if isinstance(widget, Gtk.Container):
                    for child in widget.get_children():
                        found.extend(buttons(child))
                return found

            apply = next(button for button in buttons(window.content)
                         if button.get_label() == "Save clock format for next Luna login")
            self.assertEqual(combo.get_active_id(), "24h")
            self.assertFalse(apply.get_sensitive())
            saved.assert_not_called()
            combo.set_active_id("12h")
            self.assertTrue(apply.get_sensitive())
            combo.set_active_id("24h")
            self.assertFalse(apply.get_sensitive())
            combo.set_active_id("12h")
            apply.clicked()
            saved.assert_called_once_with({"clock_format": "12h"},
                                          expected={"clock_format": "24h"})
            self.assertEqual(window.page, "taskbar")
            GLib.timeout_add(30, lambda: (window.window.destroy(), False)[1])
            Gtk.main()
            self.assertTrue(window.closed)

    def test_invalid_pages_rejected_before_opening_gtk(self):
        with self.assertRaises(settings.backend.SettingsError):
            settings.launch(page="invalid", luna=True)


if __name__ == "__main__":
    unittest.main()
