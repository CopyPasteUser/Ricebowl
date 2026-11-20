"""SG2: saved NetworkManager profile mutations require authoritative readback.

Only fake providers are used: these tests never contact or mutate the host.
"""
from __future__ import annotations

import unittest
from unittest import mock

from macrice.de import settings_backend as backend


UUID = "d2e49f0c-1a2b-43cd-8e7f-88e1f39c2052"
BEFORE = {
    "uuid": UUID, "name": "Work VPN", "kind": "vpn",
    "device": "", "active": False,
}


class NetworkProfileReadbackTests(unittest.TestCase):
    def test_success_needs_independent_provider_confirmation(self):
        after = {**BEFORE, "active": True}
        with (mock.patch.object(backend, "connection_profiles",
                                side_effect=[[BEFORE], [after]]) as read,
              mock.patch.object(backend, "_nmcli_profile",
                                return_value="") as write):
            self.assertEqual(
                backend.set_connection_profile(UUID, True, expected=False), after)
        self.assertEqual(read.call_count, 2)
        write.assert_called_once_with("con", "up", "uuid", UUID, mutate=True)

    def test_lost_readback_is_uncertain_and_never_replayed(self):
        failure = backend.SettingsError("NetworkManager owner disappeared")
        with (mock.patch.object(backend, "connection_profiles",
                                side_effect=[[BEFORE], failure]) as read,
              mock.patch.object(backend, "_nmcli_profile",
                                return_value="") as write):
            with self.assertRaisesRegex(
                    backend.SettingsError, "readback unavailable.*refresh") as caught:
                backend.set_connection_profile(UUID, True, expected=False)
        self.assertIs(caught.exception.__cause__, failure)
        self.assertEqual(read.call_count, 2)
        write.assert_called_once_with("con", "up", "uuid", UUID, mutate=True)

    def test_unchanged_or_replaced_profile_cannot_be_reported_applied(self):
        for inventory in ([BEFORE], [], [{**BEFORE, "kind": "wifi", "active": True}]):
            with (self.subTest(inventory=inventory),
                  mock.patch.object(backend, "connection_profiles",
                                    side_effect=[[BEFORE], inventory]),
                  mock.patch.object(backend, "_nmcli_profile",
                                    return_value="") as write):
                with self.assertRaisesRegex(backend.SettingsError, "refresh"):
                    backend.set_connection_profile(UUID, True, expected=False)
                write.assert_called_once()

    def test_failed_write_and_stale_precondition_never_retry(self):
        with (mock.patch.object(backend, "connection_profiles",
                                return_value=[{**BEFORE, "active": True}]),
              mock.patch.object(backend, "_nmcli_profile") as write):
            with self.assertRaisesRegex(backend.SettingsError, "refresh"):
                backend.set_connection_profile(UUID, True, expected=False)
            write.assert_not_called()

        failure = backend.SettingsError("NetworkManager reply timed out")
        with (mock.patch.object(backend, "connection_profiles",
                                return_value=[BEFORE]) as read,
              mock.patch.object(backend, "_nmcli_profile",
                                side_effect=failure) as write):
            with self.assertRaisesRegex(backend.SettingsError, "may have changed"):
                backend.set_connection_profile(UUID, True, expected=False)
            read.assert_called_once()
            write.assert_called_once()


if __name__ == "__main__":
    unittest.main()
