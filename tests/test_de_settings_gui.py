"""Actual GTK constructor/navigation smoke for the on-demand RiceSpice GUI."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macrice.de import settings
from macrice.riceware.media import MediaPlayer


class SettingsGuiTests(unittest.TestCase):
    def test_ricepop_font_duration_and_banner_limit_are_next_login_only(self):
        try:
            Gtk, Gdk, GLib = settings._gtk_modules()
        except (ImportError, ValueError):
            self.skipTest("GTK introspection typelib is not installed")
        if not Gtk.init_check([])[0]:
            self.skipTest("GTK display is unavailable")
        from macrice.de import fonts, notification_prefs
        original = dict(notification_prefs.DEFAULTS)
        face = fonts.FontFace("DejaVu Sans", "Regular", Path("/usr/share/fonts/sample.ttf"))
        with mock.patch("macrice.de.notifications.dnd_status",
                        return_value={"do_not_disturb": False}), \
             mock.patch("macrice.de.notification_prefs.load", return_value=original), \
             mock.patch("macrice.de.fonts.installed_fonts", return_value=[face]), \
             mock.patch("macrice.de.notification_prefs.save", return_value=original) as saved:
            window = settings.RiceSpiceWindow(Gtk, Gdk, GLib)
            window._background = lambda work, done: done(work())
            window.show_page("notifications")
            combos = [child for child in window.content.get_children()
                      if isinstance(child, Gtk.ComboBoxText)]
            self.assertEqual(len(combos), 4)
            scan = next(child for child in window.content.get_children()
                        if isinstance(child, Gtk.Button)
                        and child.get_label() == "Find installed TrueType fonts")
            scan.clicked()
            combos[0].set_active_id("DejaVu Sans")
            combos[1].set_active_id("14")
            combos[2].set_active_id("7000")
            combos[3].set_active_id("3")
            apply = next(child for child in window.content.get_children()
                         if isinstance(child, Gtk.Button)
                         and child.get_label() == "Save RicePop appearance for next login")
            apply.clicked()
            saved.assert_called_once_with({"font_family": "DejaVu Sans",
                                           "font_size": 14, "default_timeout": 7000,
                                           "max_visible": 3}, expected=original)
            GLib.timeout_add(30, lambda: (window.window.destroy(), False)[1])
            Gtk.main()

    def test_login_monitor_confirmation_is_visible_and_explicit(self):
        try:
            Gtk, _Gdk, GLib = settings._gtk_modules()
        except (ImportError, ValueError):
            self.skipTest("GTK introspection typelib is not installed")
        if not Gtk.init_check([])[0]:
            self.skipTest("GTK display is unavailable")

        def approve_when_visible():
            window = next(widget for widget in Gtk.Window.list_toplevels()
                          if widget.get_title() == "RiceBowl · Confirm monitor layout")
            self.assertTrue(window.get_visible())
            content = window.get_child()
            button = next(child for child in content.get_children()
                          if isinstance(child, Gtk.Button))
            self.assertTrue(button.get_sensitive())
            self.assertIn("Keep this monitor layout", button.get_label())
            button.clicked()
            button.clicked()  # Duplicate clicks must not commit a second time.
            self.assertFalse(button.get_sensitive())
            return False

        # A real GTK event loop is exercised, while the monitor guard itself
        # stays mocked so this test never touches physical display hardware.
        with mock.patch.object(settings.wayland_displays, "_in_session", return_value=True), \
                mock.patch.dict("os.environ", {"RICEBOWL_DE_NESTED": "0"}), \
                mock.patch.object(settings.wayland_displays, "runtime_root",
                                  return_value=Path("/private")), \
                mock.patch.object(settings.display_guard, "_state_path"), \
                mock.patch.object(settings.display_guard, "read_status",
                                  side_effect=[("pending", ""), ("kept", "Confirmed")]), \
                mock.patch.object(settings.display_guard, "keep_change") as keep:
            GLib.idle_add(approve_when_visible)
            failsafe = GLib.timeout_add(2000, lambda: (Gtk.main_quit(), False)[1])
            try:
                settings.launch_display_confirmation("a" * 32)
            finally:
                GLib.source_remove(failsafe)
            keep.assert_called_once()

    def test_all_sections_render_without_hardware_services_or_side_effects(self):
        try:
            Gtk, Gdk, GLib = settings._gtk_modules()
        except (ImportError, ValueError):
            self.skipTest("GTK introspection typelib is not installed")
        if not Gtk.init_check([])[0]:
            self.skipTest("GTK display is unavailable")
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": directory}), \
                mock.patch("macrice.de.settings_backend.wifi_state", return_value=True), \
                mock.patch("macrice.de.settings_backend.wifi_snapshot", return_value={
                    "enabled": True, "networks": [],
                }), \
                mock.patch("macrice.de.settings_backend.bluetooth_snapshot", return_value={
                    "powered": True, "adapter": "/org/bluez/hci0", "devices": [],
                }), \
                mock.patch("macrice.de.audio_devices.inspect", return_value={
                    "outputs": [{"name": "output.1", "description": "USB speakers", "default": True}],
                    "inputs": [{"name": "input.1", "description": "USB mic", "default": True}],
                }), \
                mock.patch("macrice.de.notifications.dnd_status", return_value={
                    "do_not_disturb": False,
                }), \
                mock.patch("macrice.de.settings_backend.power_snapshot", return_value={
                    "current": "balanced", "supported": ("balanced", "power-saver"),
                    "battery": {"percent": 85, "charging": False, "label": "Discharging"},
                }), \
                mock.patch("macrice.de.settings_backend.timezone_snapshot", return_value={
                    "current": "UTC", "zones": ("UTC",),
                }), \
                mock.patch("macrice.de.settings_backend.external_tool", return_value=None):
            Path(directory).chmod(0o700)
            window = settings.RiceSpiceWindow(Gtk, Gdk, GLib)
            self.assertTrue(window.window.get_visible())
            self.assertEqual(len(window.nav_buttons), 10)
            for name, _title, _description in settings.SECTIONS:
                before = window.generation
                window.show_page(name)
                self.assertEqual(window.generation, before + 1,
                                 "Changing one page must never recursively activate a nav button")
                self.assertEqual(window.page, name)
                self.assertTrue(window.nav_buttons[name].get_active())
            before = window.generation
            window.nav_buttons["audio"].clicked()
            self.assertEqual(window.page, "audio")
            self.assertEqual(window.generation, before + 1)
            GLib.timeout_add(160, lambda: (window.window.destroy(), False)[1])
            Gtk.main()
            self.assertTrue(window.closed)

    def test_power_page_offers_only_actual_profiles_and_applies_explicit_selection(self):
        try:
            Gtk, Gdk, GLib = settings._gtk_modules()
        except (ImportError, ValueError):
            self.skipTest("GTK introspection typelib is not installed")
        if not Gtk.init_check([])[0]:
            self.skipTest("GTK display is unavailable")
        with mock.patch("macrice.de.settings_backend.wifi_snapshot", return_value={
                    "enabled": True, "networks": [],
                }), \
                mock.patch("macrice.de.settings_backend.power_snapshot", return_value={
                    "current": "balanced", "supported": ("balanced", "power-saver"),
                    "battery": {"percent": 54, "charging": False, "label": "Discharging"},
                }), \
                mock.patch("macrice.de.settings_backend.set_power_profile",
                           return_value="power-saver") as change:
            window = settings.RiceSpiceWindow(Gtk, Gdk, GLib)
            # Complete the mocked worker on this GTK thread to test actual UI bindings.
            window._background = lambda work, done: done(work())
            window.show_page("power")
            combo = next(child for child in window.content.get_children()
                         if isinstance(child, Gtk.ComboBoxText))
            self.assertEqual(combo.get_active_id(), "balanced")
            combo.set_active_id("power-saver")
            apply = next(child for child in window.content.get_children()
                         if isinstance(child, Gtk.Button)
                         and child.get_label() == "Apply energy profile")
            apply.clicked()
            change.assert_called_once_with("power-saver", expected="balanced")
            GLib.timeout_add(30, lambda: (window.window.destroy(), False)[1])
            Gtk.main()

    def test_audio_page_controls_real_mpris_players_and_degrades_independently(self):
        try:
            Gtk, Gdk, GLib = settings._gtk_modules()
        except (ImportError, ValueError):
            self.skipTest("GTK introspection typelib is not installed")
        if not Gtk.init_check([])[0]:
            self.skipTest("GTK display is unavailable")
        player = MediaPlayer("org.mpris.MediaPlayer2.browser", "browser", "Track", "Artist",
                             "Playing", True, True, False)
        inventory = {"outputs": [{"name": "out", "description": "Speakers", "default": True}],
                     "inputs": []}
        with mock.patch("macrice.de.settings_backend.wifi_snapshot", return_value={
                    "enabled": True, "networks": [],
                }), \
                mock.patch("macrice.de.audio_devices.inspect", return_value=inventory) as devices, \
                mock.patch("macrice.riceware.media.read_media_players",
                           return_value=(player,)) as players, \
                mock.patch("macrice.riceware.media.media_action",
                           return_value=(player,)) as action:
            window = settings.RiceSpiceWindow(Gtk, Gdk, GLib)
            window._background = lambda work, done: done(work())
            window.show_page("audio")
            buttons = [child for row in window.content.get_children()
                       if isinstance(row, Gtk.Box)
                       for child in row.get_children()
                       if isinstance(child, Gtk.Button)]
            self.assertEqual([button.get_label() for button in buttons], [
                "Previous · browser", "Pause · browser", "Next · browser"])
            self.assertFalse(buttons[0].get_sensitive())
            self.assertTrue(buttons[1].get_sensitive())
            buttons[1].clicked()
            action.assert_called_once_with("org.mpris.MediaPlayer2.browser", "PlayPause")
            self.assertGreaterEqual(players.call_count, 2)
            devices.assert_called()

            # Missing audio service must not remove independently working media controls.
            with mock.patch("macrice.de.audio_devices.inspect",
                            side_effect=RuntimeError("pactl unavailable")):
                window.show_page("audio")
            labels = [child.get_text() for child in window.content.get_children()
                      if isinstance(child, Gtk.Label)]
            self.assertTrue(any("Audio devices unavailable" in label for label in labels))
            self.assertTrue(any("Track" in label for label in labels))

            # Missing MPRIS must still allow normal default-device selection.
            with mock.patch("macrice.riceware.media.read_media_players",
                            side_effect=RuntimeError("bus unavailable")):
                window.show_page("audio")
            self.assertTrue(any(isinstance(child, Gtk.ComboBoxText)
                                for child in window.content.get_children()))
            labels = [child.get_text() for child in window.content.get_children()
                      if isinstance(child, Gtk.Label)]
            self.assertTrue(any("Media session unavailable" in label for label in labels))
            GLib.timeout_add(30, lambda: (window.window.destroy(), False)[1])
            Gtk.main()

    def test_network_page_connects_selected_visible_wifi_without_password_leaks(self):
        try:
            Gtk, Gdk, GLib = settings._gtk_modules()
        except (ImportError, ValueError):
            self.skipTest("GTK introspection typelib is not installed")
        if not Gtk.init_check([])[0]:
            self.skipTest("GTK display is unavailable")
        snapshot = {"enabled": True, "networks": [
            {"ssid": "Guest", "signal": 70, "security": "", "connected": False}]}
        with mock.patch("macrice.de.settings_backend.wifi_snapshot", return_value=snapshot) as scan, \
                mock.patch("macrice.de.settings_backend.connect_visible_wifi",
                           return_value=True) as join:
            window = settings.RiceSpiceWindow(Gtk, Gdk, GLib)
            window._background = lambda work, done: done(work())
            window.show_page("network")
            connect = next(child for child in window.content.get_children()
                           if isinstance(child, Gtk.Button)
                           and child.get_label() == "Connect to Guest")
            connect.clicked()
            join.assert_called_once_with("Guest")
            refresh = next(child for child in window.content.get_children()
                           if isinstance(child, Gtk.Button)
                           and child.get_label() == "Refresh visible networks")
            refresh.clicked()
            self.assertTrue(any(call.kwargs.get("rescan") is True
                                for call in scan.call_args_list))
            snapshot["networks"] = [{"ssid": "Home", "signal": 85,
                                     "security": "WPA2", "connected": False}]
            window.show_page("network")
            self.assertTrue(any(isinstance(child, Gtk.Button)
                                and child.get_label() == "Enter password for Home"
                                for child in window.content.get_children()))
            password_button = next(child for child in window.content.get_children()
                                   if isinstance(child, Gtk.Button)
                                   and child.get_label() == "Enter password for Home")

            visibility = []

            def enter_password():
                dialog = next(widget for widget in Gtk.Window.list_toplevels()
                              if isinstance(widget, Gtk.Dialog)
                              and widget.get_title() == "Wi-Fi password")
                entry = next(child for child in dialog.get_content_area().get_children()
                             if isinstance(child, Gtk.Entry))
                visibility.append(entry.get_visibility())
                entry.set_text("correct-passphrase")
                dialog.response(Gtk.ResponseType.OK)
                return False

            def cancel_stuck_dialog():
                for widget in Gtk.Window.list_toplevels():
                    if isinstance(widget, Gtk.Dialog) and widget.get_title() == "Wi-Fi password":
                        widget.response(Gtk.ResponseType.CANCEL)
                return False

            with mock.patch("macrice.de.settings_backend.connect_secure_visible_wifi",
                            return_value=True) as secure_join:
                GLib.idle_add(enter_password)
                GLib.timeout_add(1000, cancel_stuck_dialog)
                password_button.clicked()
                secure_join.assert_called_once_with("Home", "correct-passphrase")
                self.assertEqual(visibility, [False])
            snapshot["networks"] = [{"ssid": "Office", "signal": 85,
                                     "security": "WPA2 802.1X", "connected": False}]
            window.show_page("network")
            self.assertFalse(any(isinstance(child, Gtk.Button)
                                 and child.get_label() == "Enter password for Office"
                                 for child in window.content.get_children()))
            GLib.timeout_add(30, lambda: (window.window.destroy(), False)[1])
            Gtk.main()

    def test_timezone_search_uses_supported_system_list_and_explicit_apply(self):
        try:
            Gtk, Gdk, GLib = settings._gtk_modules()
        except (ImportError, ValueError):
            self.skipTest("GTK introspection typelib is not installed")
        if not Gtk.init_check([])[0]:
            self.skipTest("GTK display is unavailable")
        snapshot = {"current": "UTC", "zones": ("America/New_York", "Europe/Berlin", "UTC")}
        with mock.patch("macrice.de.settings_backend.wifi_snapshot", return_value={
                    "enabled": True, "networks": []}), \
                mock.patch("macrice.de.settings_backend.timezone_snapshot",
                           return_value=snapshot), \
                mock.patch("macrice.de.settings_backend.external_tool", return_value=None), \
                mock.patch("macrice.de.settings_backend.set_timezone",
                           return_value="Europe/Berlin") as update:
            window = settings.RiceSpiceWindow(Gtk, Gdk, GLib)
            window._background = lambda work, done: done(work())
            window.show_page("timezone")
            search = next(child for child in window.content.get_children()
                          if isinstance(child, Gtk.SearchEntry))
            apply = next(child for child in window.content.get_children()
                         if isinstance(child, Gtk.Button)
                         and child.get_label() == "Apply system timezone")
            self.assertFalse(apply.get_sensitive())
            search.set_text("Ber")
            choices = next(child for child in window.content.get_children()
                           if isinstance(child, Gtk.Box))
            berlin = next(child for child in choices.get_children()
                          if isinstance(child, Gtk.Button) and child.get_label() == "Europe/Berlin")
            berlin.clicked()
            self.assertTrue(apply.get_sensitive())
            apply.clicked()
            update.assert_called_once_with("Europe/Berlin", expected="UTC")
            search = next(child for child in window.content.get_children()
                          if isinstance(child, Gtk.SearchEntry))
            search.set_text("Not a timezone")
            self.assertFalse(any(isinstance(child, Gtk.Button)
                                 for child in next(child for child in window.content.get_children()
                                                   if isinstance(child, Gtk.Box)).get_children()))
            GLib.timeout_add(30, lambda: (window.window.destroy(), False)[1])
            Gtk.main()


if __name__ == "__main__":
    unittest.main()
