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

    def test_invalid_pages_rejected_before_opening_gtk(self):
        with self.assertRaises(settings.backend.SettingsError):
            settings.launch(page="invalid", luna=True)


if __name__ == "__main__":
    unittest.main()
