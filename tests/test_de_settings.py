"""RiceSpice settings action boundaries and truthful native menu integration."""

import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from macrice.cli import main
from macrice.de import recipes, settings, settings_backend as backend


EXAMPLE = Path(__file__).parents[1] / "examples/wayland/quick-controls.json"


class RiceSpiceSettingsTests(unittest.TestCase):
    def test_sections_cover_real_and_delegated_settings_without_background_services(self):
        keys = [section[0] for section in settings.SECTIONS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(set(keys), {
            "network", "audio", "bluetooth", "displays", "input",
            "accessibility", "timezone", "power", "appearance",
        })
        self.assertEqual(set(backend.EXTERNAL_PAGES), {
            "displays", "input", "accessibility", "timezone",
        })

    def test_external_tools_are_allowlisted_and_not_shell_interpreted(self):
        with mock.patch.object(backend.shutil, "which", side_effect=lambda name:
                               "/usr/bin/" + name if name == "wdisplays" else None), \
                mock.patch.object(backend.subprocess, "Popen") as opened:
            self.assertEqual(backend.external_tool("displays"), ("wdisplays",))
            backend.open_external("displays")
            self.assertEqual(opened.call_args.args[0], ["wdisplays"])
            self.assertNotIn("shell", opened.call_args.kwargs)
            with self.assertRaises(backend.SettingsError):
                backend.open_external("input")
        with self.assertRaises(backend.SettingsError):
            backend.open_external("../../tmp/evil")

    def test_wifi_change_guards_stale_state_and_verifies_postcondition(self):
        with mock.patch.object(backend, "wifi_state", side_effect=[True, False]), \
                mock.patch.object(backend, "_nmcli", return_value="") as run:
            self.assertFalse(backend.set_wifi(False, expected=True))
            run.assert_called_once_with("radio", "wifi", "off")
        with mock.patch.object(backend, "wifi_state", return_value=False), \
                mock.patch.object(backend, "_nmcli") as run:
            with self.assertRaisesRegex(backend.SettingsError, "changed"):
                backend.set_wifi(False, expected=True)
            run.assert_not_called()
        with self.assertRaises(backend.SettingsError):
            backend.set_wifi(1, expected=True)

    def test_network_inventory_is_bounded_by_existing_networkmanager_reader(self):
        from macrice.hardware_status import WifiNetwork

        rows = (WifiNetwork("Home", 90, "WPA2", True),
                WifiNetwork("Guest", 62, "", False))
        with mock.patch.object(backend, "wifi_state", return_value=True), \
                mock.patch("macrice.hardware_status.read_wifi_networks", return_value=rows) as scan:
            self.assertEqual(backend.wifi_snapshot(rescan=True)["networks"], [
                {"ssid": "Home", "signal": 90, "security": "WPA2", "connected": True},
                {"ssid": "Guest", "signal": 62, "security": "", "connected": False},
            ])
            scan.assert_called_once_with(rescan=True)
        with mock.patch.object(backend, "wifi_state", return_value=False), \
                mock.patch("macrice.hardware_status.read_wifi_networks") as scan:
            self.assertEqual(backend.wifi_snapshot(), {"enabled": False, "networks": []})
            scan.assert_not_called()
        with self.assertRaises(backend.SettingsError):
            backend.wifi_snapshot(rescan="yes")

    def test_connect_wifi_requires_fresh_visible_selection_and_readback(self):
        network = {"enabled": True, "networks": [
            {"ssid": "Guest", "signal": 62, "security": "", "connected": False}]}
        with mock.patch.object(backend, "wifi_snapshot", return_value=network), \
                mock.patch("macrice.hardware_status.connect_wifi", return_value=True) as join:
            self.assertTrue(backend.connect_visible_wifi("Guest"))
            join.assert_called_once_with("Guest")
            with self.assertRaisesRegex(backend.SettingsError, "scan again"):
                backend.connect_visible_wifi("Absent")
            with self.assertRaises(backend.SettingsError):
                backend.connect_visible_wifi("bad\x00ssid")
            join.assert_called_once()
        with mock.patch.object(backend, "wifi_snapshot", return_value=network), \
                mock.patch("macrice.hardware_status.connect_wifi", return_value=False):
            with self.assertRaisesRegex(backend.SettingsError, "verified"):
                backend.connect_visible_wifi("Guest")

    def test_bluetooth_unpaired_or_stale_devices_are_not_mutated(self):
        fixture = {"powered": True, "adapter": "/org/bluez/hci0", "devices": [
            {"address": "AA:BB:CC:DD:EE:FF", "paired": False,
             "connected": False, "label": "Phone"}]}
        with mock.patch.object(backend, "bluetooth_snapshot", return_value=fixture), \
                mock.patch("macrice.bluetooth_dbus.set_connection") as connect:
            with self.assertRaisesRegex(backend.SettingsError, "Pair"):
                backend.set_bluetooth_connection("AA:BB:CC:DD:EE:FF", True, expected=False)
            with self.assertRaisesRegex(backend.SettingsError, "changed"):
                backend.set_bluetooth_connection("AA:BB:CC:DD:EE:FF", False, expected=True)
            connect.assert_not_called()

    def test_bluetooth_power_has_concurrency_guard_and_postcondition(self):
        before = {"powered": False, "adapter": "/org/bluez/hci0", "devices": []}
        after = {**before, "powered": True}
        with mock.patch.object(backend, "bluetooth_snapshot", side_effect=[before, after]), \
                mock.patch("macrice.bluetooth_dbus.set_power") as change:
            self.assertEqual(backend.set_bluetooth_power(True, expected=False), after)
            change.assert_called_once_with("/org/bluez/hci0", True)
        with mock.patch.object(backend, "bluetooth_snapshot", return_value=after), \
                mock.patch("macrice.bluetooth_dbus.set_power") as change:
            with self.assertRaisesRegex(backend.SettingsError, "changed"):
                backend.set_bluetooth_power(False, expected=False)
            change.assert_not_called()

    def test_suspend_refused_in_nested_preview_without_command(self):
        with mock.patch.object(backend.subprocess, "run") as run:
            with self.assertRaisesRegex(backend.SettingsError, "nested"):
                backend.power_action("suspend", nested=True)
            with self.assertRaises(backend.SettingsError):
                backend.power_action("reboot")
            run.assert_not_called()

    def test_power_snapshot_shows_real_battery_and_missing_profile_service(self):
        from macrice.hardware_status import BatteryState

        with mock.patch("macrice.hardware_status.read_power_profiles",
                        return_value=(None, ())), \
                mock.patch("macrice.hardware_status.read_battery",
                           return_value=BatteryState(71, True, "Charging")):
            self.assertEqual(backend.power_snapshot(), {
                "current": None, "supported": (),
                "battery": {"percent": 71, "charging": True, "label": "Charging"},
            })
        with mock.patch("macrice.hardware_status.read_power_profiles",
                        return_value=("balanced", ("balanced",))), \
                mock.patch("macrice.hardware_status.read_battery", return_value=None):
            self.assertIsNone(backend.power_snapshot()["battery"])

    def test_power_profile_change_requires_fresh_supported_state_and_readback(self):
        with mock.patch("macrice.hardware_status.read_power_profiles",
                        side_effect=[("balanced", ("balanced", "power-saver")),
                                     ("power-saver", ("balanced", "power-saver"))]), \
                mock.patch("macrice.hardware_status.set_power_profile") as change:
            self.assertEqual(backend.set_power_profile("power-saver", expected="balanced"),
                             "power-saver")
            change.assert_called_once_with("power-saver")
        with mock.patch("macrice.hardware_status.read_power_profiles",
                        return_value=("balanced", ("balanced", "power-saver"))), \
                mock.patch("macrice.hardware_status.set_power_profile") as change:
            with self.assertRaisesRegex(backend.SettingsError, "changed"):
                backend.set_power_profile("power-saver", expected="performance")
            with self.assertRaisesRegex(backend.SettingsError, "not supported"):
                backend.set_power_profile("performance", expected="balanced")
            with self.assertRaises(backend.SettingsError):
                backend.set_power_profile(1, expected="balanced")
            change.assert_not_called()
        with mock.patch("macrice.hardware_status.read_power_profiles",
                        side_effect=[("balanced", ("balanced", "power-saver")),
                                     ("balanced", ("balanced", "power-saver"))]), \
                mock.patch("macrice.hardware_status.set_power_profile"):
            with self.assertRaisesRegex(backend.SettingsError, "verified"):
                backend.set_power_profile("power-saver", expected="balanced")

    def test_native_and_fallback_settings_actions_use_fixed_command(self):
        original = json.loads(EXAMPLE.read_text())
        parsed = recipes.parse(json.dumps(original).encode())
        self.assertIn("settings", parsed.menu[1][0].actions)
        actions = ET.fromstring(recipes.labwc_menu(parsed)).find("menu").find("menu")
        self.assertEqual(actions.findall("item")[-1].find("action").attrib,
                         {"name": "Execute", "command": "ricebowl de settings"})
        original["menu"]["groups"][0]["actions"][-1] = "settings; curl malicious"
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(original).encode())
        with mock.patch("macrice.de.settings.launch") as launch:
            self.assertEqual(main(["de", "settings"]), 0)
            launch.assert_called_once_with()
        with mock.patch("sys.stderr"):
            self.assertEqual(main(["de", "settings", "--nested"]), 1)
        with mock.patch("macrice.de.settings._gtk_modules", side_effect=ValueError("missing Gtk")), \
                mock.patch("sys.stderr"):
            self.assertEqual(main(["de", "settings"]), 1)


if __name__ == "__main__":
    unittest.main()
