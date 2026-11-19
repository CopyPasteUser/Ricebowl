"""SG2: Wi-Fi SSID deduplication must not hide conflicting AP security.

These tests never contact NetworkManager or mutate the host radio; all
connection attempts and raw scan responses are mocked.
"""
from __future__ import annotations

import unittest
from contextlib import contextmanager
from unittest import mock

from macrice import hardware_status
from macrice.de import settings_backend as backend


@contextmanager
def scanned(ssid: str = "Campus", security: str = "WPA2", raw: str = "Campus:WPA2"):
    """One deduplicated UI row, independently controlled raw NetworkManager BSS rows."""
    networks = (hardware_status.WifiNetwork(ssid, 75, security, False),)
    with (
        mock.patch.object(backend, "wifi_state", return_value=True),
        mock.patch.object(hardware_status, "read_wifi_networks", return_value=networks) as inventory,
        mock.patch.object(backend, "_nmcli_profile", return_value=raw) as scan,
        mock.patch.object(hardware_status, "connect_wifi", return_value=True) as saved,
        mock.patch.object(hardware_status, "connect_wifi_secured", return_value=True) as secured,
    ):
        yield inventory, scan, saved, secured


class WiFiIdentityGuardTests(unittest.TestCase):
    def test_security_conflict_blocks_secret_and_saved_profile_paths(self):
        # The usual single UI row hides a simultaneous open AP with the same
        # SSID. Neither join path may choose NetworkManager's ambiguous BSS.
        with scanned(raw="Campus:WPA2\nCampus:--") as (inventory, scan, saved, secured):
            with self.assertRaisesRegex(backend.SettingsError, "conflicting access points"):
                backend.connect_secure_visible_wifi("Campus", "correct-password")
            with self.assertRaisesRegex(backend.SettingsError, "conflicting access points"):
                backend.connect_visible_wifi("Campus")
            saved.assert_not_called()
            secured.assert_not_called()
            self.assertEqual(inventory.call_count, 2)
            self.assertEqual(scan.call_count, 2)

    def test_same_security_multiple_access_points_preserve_roaming(self):
        with scanned(raw="Campus:WPA2\nCampus:WPA2") as (_, scan, saved, secured):
            self.assertTrue(backend.connect_visible_wifi("Campus"))
            self.assertTrue(backend.connect_secure_visible_wifi("Campus", "correct-password"))
            saved.assert_called_once_with("Campus")
            secured.assert_called_once_with("Campus", "correct-password")
            self.assertEqual(scan.call_count, 2)
            self.assertEqual(scan.call_args.args, (
                "-t", "-e", "yes", "-f", "SSID,SECURITY",
                "device", "wifi", "list", "--rescan", "no",
            ))

    def test_nmcli_escaped_colon_and_unicode_ssid_round_trip(self):
        with scanned(ssid="Café:Lobby", raw=r"Café\:Lobby:WPA2") as (_, _, saved, _):
            self.assertTrue(backend.connect_visible_wifi("Café:Lobby"))
            saved.assert_called_once_with("Café:Lobby")

    def test_changed_or_disappeared_security_never_starts_join(self):
        for raw in ("Campus:WPA3", "Other:WPA2", "", "Campus:WPA2\nCampus:WPA3"):
            with self.subTest(raw=raw), scanned(raw=raw) as (_, _, saved, secured):
                with self.assertRaisesRegex(backend.SettingsError, "security changed"):
                    backend.connect_secure_visible_wifi("Campus", "correct-password")
                saved.assert_not_called()
                secured.assert_not_called()

    def test_malformed_scan_fails_closed_before_any_network_mutation(self):
        with scanned(raw="Campus:WPA2:extra") as (_, _, saved, secured):
            with self.assertRaisesRegex(backend.SettingsError, "Malformed NetworkManager"):
                backend.connect_visible_wifi("Campus")
            saved.assert_not_called()
            secured.assert_not_called()
        with scanned(raw="\n".join("Campus:WPA2" for _ in range(257))) as (_, _, saved, secured):
            with self.assertRaisesRegex(backend.SettingsError, "too many access points"):
                backend.connect_secure_visible_wifi("Campus", "correct-password")
            saved.assert_not_called()
            secured.assert_not_called()

    def test_live_scan_provider_loss_remains_an_error_not_empty_or_safe(self):
        with scanned() as (_, scan, saved, secured):
            scan.side_effect = backend.SettingsError("NetworkManager went away")
            with self.assertRaisesRegex(backend.SettingsError, "went away"):
                backend.connect_secure_visible_wifi("Campus", "correct-password")
            saved.assert_not_called()
            secured.assert_not_called()

    def test_ordinary_list_never_triggers_second_scan_or_mutation(self):
        with scanned() as (inventory, scan, saved, secured):
            result = backend.wifi_snapshot()
            self.assertEqual(result["networks"][0]["ssid"], "Campus")
            inventory.assert_called_once_with(rescan=False, fail_on_error=True)
            scan.assert_not_called()
            saved.assert_not_called()
            secured.assert_not_called()

    def test_security_verification_requires_explicit_valid_selection(self):
        with scanned() as (inventory, scan, saved, secured):
            for invalid in (1, True, "", [], {}):
                with self.subTest(invalid=invalid), self.assertRaises(backend.SettingsError):
                    backend.wifi_snapshot(verify_security=invalid)
            inventory.assert_not_called()
            scan.assert_not_called()
            saved.assert_not_called()
            secured.assert_not_called()


if __name__ == "__main__":
    unittest.main()
