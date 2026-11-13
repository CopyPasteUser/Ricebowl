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

    def test_invalid_pages_rejected_before_opening_gtk(self):
        with self.assertRaises(settings.backend.SettingsError):
            settings.launch(page="invalid", luna=True)


if __name__ == "__main__":
    unittest.main()
