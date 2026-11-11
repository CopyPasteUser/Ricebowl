"""RiceSpice settings action boundaries and truthful native menu integration."""

import json
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime
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
            "network", "audio", "notifications", "bluetooth", "displays", "input",
            "accessibility", "timezone", "power", "appearance",
        })
        self.assertEqual(set(backend.EXTERNAL_PAGES), {
            "connections", "displays", "input", "accessibility", "timezone",
        })

    def test_saved_network_profiles_activate_by_uuid_without_secrets(self):
        wired = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        vpn = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        rows = (f"{wired}:802-3-ethernet:Office\\:LAN:enp1s0\n"
                f"{vpn}:vpn:Mullvad\\\\test:--\n")
        active = {wired}
        commands = []

        def nmcli(*args, mutate=False):
            commands.append((args, mutate))
            if args[-2:] == ("show", "--active"):
                return "\n".join(sorted(active))
            if args[-2:] == ("con", "show"):
                return rows
            if args == ("con", "up", "uuid", vpn):
                active.add(vpn)
                return ""
            if args == ("con", "down", "uuid", wired):
                active.remove(wired)
                return ""
            self.fail(f"Unexpected NetworkManager operation: {args}")

        with mock.patch.object(backend, "_nmcli_profile", side_effect=nmcli):
            before = backend.connection_profiles()
            self.assertEqual(before[0]["name"], "Office:LAN")
            self.assertEqual(before[1]["name"], "Mullvad\\test")
            self.assertEqual(backend.set_connection_profile(vpn, True, expected=False)["active"], True)
            self.assertFalse(backend.set_connection_profile(wired, False, expected=True)["active"])
            with self.assertRaisesRegex(backend.SettingsError, "changed"):
                backend.set_connection_profile(vpn, True, expected=False)
            with self.assertRaises(backend.SettingsError):
                backend.set_connection_profile("--help", True, expected=False)
        self.assertIn((("con", "up", "uuid", vpn), True), commands)
        self.assertIn((("con", "down", "uuid", wired), True), commands)
        self.assertFalse(any("password" in str(item).lower() for item in commands))

    def test_network_profile_parser_rejects_ambiguous_malformed_inventory(self):
        wired = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        with mock.patch.object(backend, "_nmcli_profile", side_effect=lambda *args, **kwargs:
                               f"{wired}:vpn:Work:--\n{wired}:vpn:Work 2:--" if args[-2:] ==
                               ("con", "show") else ""):
            with self.assertRaisesRegex(backend.SettingsError, "duplicate"):
                backend.connection_profiles()
        for bad in ("broken\\escape", "trailing\\", "a:b:c"):
            with self.subTest(bad=bad), self.assertRaises(backend.SettingsError):
                if bad == "a:b:c":
                    with mock.patch.object(backend, "_nmcli_profile", side_effect=lambda *a, **kw:
                                           bad if a[-2:] == ("con", "show") else ""):
                        backend.connection_profiles()
                else:
                    backend._terse_fields(bad)

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

    def test_wpa_password_stays_with_stdin_adapter_and_rejects_unsupported_networks(self):
        personal = {"enabled": True, "networks": [
            {"ssid": "Home", "signal": 78, "security": "WPA2", "connected": False}]}
        with mock.patch.object(backend, "wifi_snapshot", return_value=personal), \
                mock.patch("macrice.hardware_status.connect_wifi_secured",
                           return_value=True) as join:
            self.assertTrue(backend.connect_secure_visible_wifi("Home", "correct-passphrase"))
            join.assert_called_once_with("Home", "correct-passphrase")
            for invalid in ("short", "line\nbreaks", "x" * 64, None):
                with self.assertRaises(backend.SettingsError):
                    backend.connect_secure_visible_wifi("Home", invalid)
            with self.assertRaisesRegex(backend.SettingsError, "scan again"):
                backend.connect_secure_visible_wifi("Unknown", "correct-passphrase")
            join.assert_called_once()
        unsupported = {"enabled": True, "networks": [
            {"ssid": "Office", "signal": 70, "security": "WPA2 802.1X", "connected": False}]}
        with mock.patch.object(backend, "wifi_snapshot", return_value=unsupported), \
                mock.patch("macrice.hardware_status.connect_wifi_secured") as join:
            with self.assertRaisesRegex(backend.SettingsError, "external authentication"):
                backend.connect_secure_visible_wifi("Office", "correct-passphrase")
            join.assert_not_called()

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

    def test_suspend_locks_before_requesting_logind_and_lock_reports_success(self):
        result = mock.Mock(returncode=0)
        with mock.patch.object(backend.shutil, "which",
                               side_effect=lambda name: "/usr/bin/" + name), \
             mock.patch.object(backend.subprocess, "run", return_value=result) as run, \
             mock.patch.dict(backend.os.environ, {"RICEBOWL_DE_NESTED": "0"}):
            backend.power_action("lock")
            self.assertEqual(run.call_args.args[0], ["/usr/bin/swaylock", "-f"])
            run.reset_mock()
            backend.power_action("suspend")
            self.assertEqual([call.args[0] for call in run.call_args_list],
                             [["/usr/bin/swaylock", "-f"],
                              ["/usr/bin/loginctl", "suspend"]])

    def test_suspend_refuses_failed_or_unavailable_screen_lock(self):
        with mock.patch.object(backend.shutil, "which",
                               side_effect=lambda name: None if name == "swaylock"
                               else "/usr/bin/" + name), \
             mock.patch.object(backend.subprocess, "run") as run:
            with self.assertRaisesRegex(backend.SettingsError, "swaylock"):
                backend.power_action("suspend")
            run.assert_not_called()
        with mock.patch.object(backend.shutil, "which",
                               side_effect=lambda name: "/usr/bin/" + name), \
             mock.patch.object(backend.subprocess, "run",
                               return_value=mock.Mock(returncode=1)) as run:
            with self.assertRaisesRegex(backend.SettingsError, "lock failed"):
                backend.power_action("suspend")
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0], ["/usr/bin/swaylock", "-f"])

    def test_suspend_refuses_lock_timeout_without_contacting_logind(self):
        import subprocess
        with mock.patch.object(backend.shutil, "which",
                               side_effect=lambda name: "/usr/bin/" + name), \
             mock.patch.object(backend.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired("swaylock", 8)) as run:
            with self.assertRaisesRegex(backend.SettingsError, "could not complete"):
                backend.power_action("suspend")
            self.assertEqual(run.call_count, 1)

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

    def test_timezone_inventory_and_guarded_polkit_change(self):
        rows = "Europe/Berlin\nUTC\nAmerica/New_York"
        with mock.patch.object(backend, "_timedatectl", side_effect=["UTC", rows]) as call:
            self.assertEqual(backend.timezone_snapshot(), {
                "current": "UTC", "zones": ("America/New_York", "Europe/Berlin", "UTC")})
            self.assertEqual(call.call_args_list, [
                mock.call("show", "-p", "Timezone", "--value"),
                mock.call("list-timezones", "--no-pager")])
        with mock.patch.object(backend, "_timedatectl", side_effect=["UTC", rows,
                                                                      "", "Europe/Berlin"]) as call:
            self.assertEqual(backend.set_timezone("Europe/Berlin", expected="UTC"),
                             "Europe/Berlin")
            self.assertEqual(call.call_args_list[2], mock.call("set-timezone", "Europe/Berlin"))

        with mock.patch.object(backend, "_timedatectl") as run:
            for name in ("../../etc/passwd", "UTC; whoami", "No Such Zone", "x\x00", None):
                if name == "No Such Zone":
                    continue  # Valid syntax but not in the system inventory.
                with self.assertRaises(backend.SettingsError):
                    backend.set_timezone(name, expected="UTC")
            run.assert_not_called()
        with mock.patch.object(backend, "timezone_snapshot", return_value={
                    "current": "Europe/Berlin", "zones": ("Europe/Berlin", "UTC")}), \
                mock.patch.object(backend, "_timedatectl") as run:
            with self.assertRaisesRegex(backend.SettingsError, "changed"):
                backend.set_timezone("UTC", expected="America/New_York")
            with self.assertRaisesRegex(backend.SettingsError, "system list"):
                backend.set_timezone("America/New_York", expected="Europe/Berlin")
            run.assert_not_called()
        with mock.patch.object(backend, "_timedatectl", side_effect=["UTC", "UTC\nEurope/Berlin",
                                                                      "", "UTC"]):
            with self.assertRaisesRegex(backend.SettingsError, "verification"):
                backend.set_timezone("Europe/Berlin", expected="UTC")
        with mock.patch.object(backend, "_timedatectl", side_effect=["UTC", "UTC\n.."]):
            with self.assertRaisesRegex(backend.SettingsError, "invalid"):
                backend.timezone_snapshot()

    def test_ntp_is_explicit_system_wide_and_verified(self):
        with mock.patch.object(backend, "_timedatectl",
                               return_value="CanNTP=yes\nNTP=no") as query:
            self.assertEqual(backend.ntp_snapshot(), {"available": True, "enabled": False})
            query.assert_called_once_with("show", "-p", "CanNTP", "-p", "NTP")
        with mock.patch.object(backend, "_timedatectl", side_effect=[
                "CanNTP=yes\nNTP=no", "", "CanNTP=yes\nNTP=yes"]) as timedated:
            self.assertEqual(backend.set_ntp(True, expected=False)["enabled"], True)
            self.assertEqual(timedated.call_args_list[1], mock.call("set-ntp", "true"))
        with mock.patch.object(backend, "ntp_snapshot", return_value={
                "available": True, "enabled": True}), \
                mock.patch.object(backend, "_timedatectl") as changed:
            with self.assertRaisesRegex(backend.SettingsError, "changed"):
                backend.set_ntp(True, expected=False)
            changed.assert_not_called()
        with mock.patch.object(backend, "ntp_snapshot", return_value={
                "available": False, "enabled": False}), \
                mock.patch.object(backend, "_timedatectl") as changed:
            with self.assertRaisesRegex(backend.SettingsError, "does not offer"):
                backend.set_ntp(True, expected=False)
            changed.assert_not_called()
        with mock.patch.object(backend, "_timedatectl", return_value="NTP=maybe\nCanNTP=yes"):
            with self.assertRaisesRegex(backend.SettingsError, "invalid"):
                backend.ntp_snapshot()
        with self.assertRaises(backend.SettingsError):
            backend.set_ntp("true", expected=False)

    def test_manual_system_clock_is_guarded_and_readback_verified(self):
        target = datetime(2026, 11, 8, 10, 30, 0)

        class Clock:
            @staticmethod
            def strptime(value, pattern):
                return datetime.strptime(value, pattern)

            @staticmethod
            def now():
                return target

        with mock.patch.object(backend, "datetime", Clock), \
                mock.patch.object(backend, "_timedatectl", side_effect=[
                    "CanNTP=yes\nNTP=no", ""]) as timedated:
            self.assertEqual(backend.set_system_clock("2026-11-08 10:30:00"),
                             "2026-11-08 10:30:00")
            self.assertEqual(timedated.call_args_list[1],
                             mock.call("set-time", "2026-11-08 10:30:00"))
        with mock.patch.object(backend, "_timedatectl") as timedated:
            for invalid in ("not-a-date", "2026-99-08 10:30:00", "2000-02-31 10:30:00",
                            "; rm -rf /", "2026-11-08 10:30", None):
                with self.subTest(invalid=invalid), self.assertRaises(backend.SettingsError):
                    backend.set_system_clock(invalid)
            timedated.assert_not_called()
        with mock.patch.object(backend, "ntp_snapshot", return_value={
                "available": True, "enabled": True}), \
                mock.patch.object(backend, "_timedatectl") as timedated:
            with self.assertRaisesRegex(backend.SettingsError, "Automatic time"):
                backend.set_system_clock("2026-11-08 10:30:00")
            timedated.assert_not_called()

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
