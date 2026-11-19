"""SG2: system service write failures must not advertise safe retries.

A transport exception cannot prove a power, radio or Bluetooth operation did
not apply before the reply was lost. This suite only calls mock adapters.
"""
import unittest
from unittest import mock

from macrice.de import settings_backend as backend


class DeviceMutationUncertaintyTests(unittest.TestCase):
    def test_wifi_radio_write_timeout_is_indeterminate_and_not_replayed(self):
        for failure in (backend.SettingsError("nmcli transport lost"),
                        backend.SettingsError("policy reply missing")):
            with self.subTest(failure=str(failure)):
                with (
                    mock.patch.object(backend, "wifi_state", return_value=False) as read,
                    mock.patch.object(backend, "_nmcli", side_effect=failure) as change,
                ):
                    with self.assertRaisesRegex(
                            backend.SettingsError, "outcome unknown; refresh") as raised:
                        backend.set_wifi(True, expected=False)
                    self.assertIs(raised.exception.__cause__, failure)
                    read.assert_called_once()
                    change.assert_called_once_with("radio", "wifi", "on")

    def test_bluetooth_adapter_write_reply_loss_is_indeterminate(self):
        snapshot = {"powered": False, "adapter": "/org/bluez/hci0", "devices": []}
        failure = TimeoutError("reply dropped after BlueZ action")
        with (
            mock.patch.object(backend, "bluetooth_snapshot", return_value=snapshot) as read,
            mock.patch("macrice.bluetooth_dbus.set_power", side_effect=failure) as write,
        ):
            with self.assertRaisesRegex(
                    backend.SettingsError, "power may have changed; outcome unknown") as raised:
                backend.set_bluetooth_power(True, expected=False,
                                            expected_adapter="/org/bluez/hci0")
            self.assertIs(raised.exception.__cause__, failure)
            read.assert_called_once()
            write.assert_called_once_with("/org/bluez/hci0", True)

    def test_bluetooth_device_write_reply_loss_is_indeterminate(self):
        addr = "AA:BB:CC:DD:EE:FF"
        snapshot = {"powered": True, "adapter": "/org/bluez/hci0",
                    "devices": [{"address": addr, "paired": True,
                                 "connected": False, "label": "Headset"}]}
        failure = OSError("system bus disconnected")
        with (
            mock.patch.object(backend, "bluetooth_snapshot", return_value=snapshot) as read,
            mock.patch("macrice.bluetooth_dbus.set_connection", side_effect=failure) as write,
        ):
            with self.assertRaisesRegex(
                    backend.SettingsError, "connection may have changed; outcome unknown") as raised:
                backend.set_bluetooth_connection(addr, True, expected=False,
                                                 expected_adapter="/org/bluez/hci0")
            self.assertIs(raised.exception.__cause__, failure)
            read.assert_called_once()
            write.assert_called_once_with(
                addr, True, expected_adapter="/org/bluez/hci0")

    def test_power_profile_write_reply_loss_is_indeterminate(self):
        from macrice import hardware_status

        failure = RuntimeError("power-profiles-daemon reply lost")
        with (
            mock.patch.object(hardware_status, "read_power_profiles",
                              return_value=("balanced", ("balanced", "power-saver"))) as read,
            mock.patch.object(hardware_status, "set_power_profile",
                              side_effect=failure) as write,
        ):
            with self.assertRaisesRegex(
                    backend.SettingsError, "Power profile may have changed; outcome unknown") as raised:
                backend.set_power_profile("power-saver", expected="balanced")
            self.assertIs(raised.exception.__cause__, failure)
            read.assert_called_once()
            write.assert_called_once_with("power-saver")

    def test_noop_device_changes_never_touch_mutation_backends(self):
        with (
            mock.patch.object(backend, "wifi_state", return_value=False),
            mock.patch.object(backend, "_nmcli") as radio,
        ):
            self.assertFalse(backend.set_wifi(False, expected=False))
            radio.assert_not_called()
        with (
            mock.patch.object(backend, "bluetooth_snapshot",
                              return_value={"powered": True,
                                            "adapter": "/org/bluez/hci0",
                                            "devices": []}),
            mock.patch("macrice.bluetooth_dbus.set_power") as bluetooth,
        ):
            self.assertTrue(backend.set_bluetooth_power(
                True, expected=True)["powered"])
            bluetooth.assert_not_called()


if __name__ == "__main__":
    unittest.main()
