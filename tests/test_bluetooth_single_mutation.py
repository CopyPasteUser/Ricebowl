"""SG2: Bluetooth CLI/BlueZ transitions are single-action, verified transactions.

All radio, DBus and bluetoothctl operations are mocked. Never touch a host
radio or pair a real device when exercising these failure/recovery branches.
"""
import subprocess
import unittest
from unittest import mock

from macrice import hardware_status as hw

ADDRESS = "AA:BB:CC:DD:EE:FF"


def bluetooth(powered=True, connected=False, *, duplicates=False):
    devices = (hw.BluetoothDevice(ADDRESS, "Keyboard", True, connected),)
    if duplicates:
        devices += (hw.BluetoothDevice(ADDRESS.lower(), "Other adapter", True, False),)
    return hw.BluetoothState(powered, ("Keyboard",) if connected else (),
                             devices, "D-Bus", False, False)


class BluetoothSingleMutationTests(unittest.TestCase):
    def test_already_selected_power_does_not_touch_any_transport(self):
        state = bluetooth(powered=True)
        with (
            mock.patch.object(hw, "read_bluetooth", return_value=state),
            mock.patch.object(hw.shutil, "which") as which,
            mock.patch("macrice.bluetooth_dbus.set_power") as setter,
            mock.patch.object(hw.subprocess, "run") as run,
        ):
            self.assertIs(hw.set_bluetooth_power(True), state)
            which.assert_not_called()
            setter.assert_not_called()
            run.assert_not_called()

    def test_already_connected_device_does_not_mutate(self):
        state = bluetooth(connected=True)
        with (
            mock.patch.object(hw, "read_bluetooth", return_value=state),
            mock.patch.object(hw.shutil, "which") as which,
            mock.patch("macrice.bluetooth_dbus.set_connection") as setter,
            mock.patch.object(hw.subprocess, "run") as run,
        ):
            self.assertIs(hw.set_bluetooth_connection(ADDRESS.lower(), True), state)
            which.assert_not_called()
            setter.assert_not_called()
            run.assert_not_called()

    def test_successful_cli_power_with_stale_cli_readback_uses_dbus_read_only(self):
        old, new = bluetooth(powered=False), bluetooth(powered=True)
        with (
            mock.patch.object(hw, "read_bluetooth", side_effect=[old, old]),
            mock.patch.object(hw, "_bluetooth_via_dbus", return_value=new) as probe,
            mock.patch.object(hw.shutil, "which", return_value="/usr/bin/bluetoothctl"),
            mock.patch.object(hw.subprocess, "run",
                              return_value=subprocess.CompletedProcess([], 0)) as run,
            mock.patch("macrice.bluetooth_dbus.set_power") as mutate,
        ):
            self.assertIs(hw.set_bluetooth_power(True), new)
            run.assert_called_once()
            probe.assert_called_once_with()
            mutate.assert_not_called()

    def test_successful_cli_connection_with_stale_cli_readback_is_read_only(self):
        old, new = bluetooth(connected=False), bluetooth(connected=True)
        with (
            mock.patch.object(hw, "read_bluetooth", side_effect=[old, old]),
            mock.patch.object(hw, "_bluetooth_via_dbus", return_value=new),
            mock.patch.object(hw.shutil, "which", return_value="/usr/bin/bluetoothctl"),
            mock.patch.object(hw.subprocess, "run",
                              return_value=subprocess.CompletedProcess([], 0)) as run,
            mock.patch("macrice.bluetooth_dbus.set_connection") as mutate,
        ):
            self.assertIs(hw.set_bluetooth_connection(ADDRESS, True), new)
            run.assert_called_once()
            mutate.assert_not_called()

    def test_successful_cli_but_both_readbacks_disagree_never_replays(self):
        old = bluetooth(connected=False)
        with (
            mock.patch.object(hw, "read_bluetooth", return_value=old),
            mock.patch.object(hw, "_bluetooth_via_dbus", return_value=old),
            mock.patch.object(hw.shutil, "which", return_value="/usr/bin/bluetoothctl"),
            mock.patch.object(hw.subprocess, "run",
                              return_value=subprocess.CompletedProcess([], 0)) as run,
            mock.patch("macrice.bluetooth_dbus.set_connection") as setter,
        ):
            with self.assertRaisesRegex(RuntimeError, "verification failed"):
                hw.set_bluetooth_connection(ADDRESS, True)
            run.assert_called_once()
            setter.assert_not_called()

    def test_timeout_must_not_fall_back_to_second_mutation(self):
        for operation in ("power", "connect"):
            with self.subTest(operation=operation):
                before = bluetooth(powered=False) if operation == "power" else bluetooth()
                with (
                    mock.patch.object(hw, "read_bluetooth", return_value=before),
                    mock.patch.object(hw, "_bluetooth_via_dbus") as probe,
                    mock.patch.object(hw.shutil, "which",
                                      return_value="/usr/bin/bluetoothctl"),
                    mock.patch.object(hw.subprocess, "run",
                                      side_effect=subprocess.TimeoutExpired(
                                          ["bluetoothctl", operation], 5)) as run,
                    mock.patch("macrice.bluetooth_dbus.set_power") as power,
                    mock.patch("macrice.bluetooth_dbus.set_connection") as connection,
                ):
                    with self.assertRaisesRegex(RuntimeError, "outcome unknown"):
                        if operation == "power":
                            hw.set_bluetooth_power(True)
                        else:
                            hw.set_bluetooth_connection(ADDRESS, True)
                    run.assert_called_once()
                    probe.assert_not_called()
                    power.assert_not_called()
                    connection.assert_not_called()

    def test_rejected_cli_power_can_use_verified_dbus_fallback(self):
        old, new = bluetooth(powered=False), bluetooth(powered=True)
        with (
            mock.patch.object(hw, "read_bluetooth", return_value=old),
            mock.patch.object(hw, "_bluetooth_via_dbus",
                              side_effect=[old, new]) as probe,
            mock.patch.object(hw.shutil, "which",
                              return_value="/usr/bin/bluetoothctl"),
            mock.patch.object(hw.subprocess, "run",
                              return_value=subprocess.CompletedProcess([], 1)),
            mock.patch("macrice.bluetooth_dbus.snapshot",
                       return_value=(False, "/org/bluez/hci0", ())),
            mock.patch("macrice.bluetooth_dbus.set_power") as setter,
        ):
            self.assertIs(hw.set_bluetooth_power(True), new)
            setter.assert_called_once_with("/org/bluez/hci0", True)
            self.assertEqual(probe.call_count, 2)

    def test_rejected_cli_connection_can_use_verified_dbus_fallback(self):
        old, new = bluetooth(connected=False), bluetooth(connected=True)
        with (
            mock.patch.object(hw, "read_bluetooth", return_value=old),
            mock.patch.object(hw, "_bluetooth_via_dbus",
                              side_effect=[old, new]) as probe,
            mock.patch.object(hw.shutil, "which",
                              return_value="/usr/bin/bluetoothctl"),
            mock.patch.object(hw.subprocess, "run",
                              return_value=subprocess.CompletedProcess([], 1)),
            mock.patch("macrice.bluetooth_dbus.set_connection") as setter,
        ):
            self.assertIs(hw.set_bluetooth_connection(ADDRESS, True), new)
            setter.assert_called_once_with(ADDRESS, True)
            self.assertEqual(probe.call_count, 2)

    def test_duplicate_device_identity_and_malformed_address_refuse_mutation(self):
        state = bluetooth(duplicates=True)
        with (
            mock.patch.object(hw, "read_bluetooth", return_value=state) as read,
            mock.patch.object(hw.shutil, "which") as which,
            mock.patch.object(hw.subprocess, "run") as run,
            mock.patch("macrice.bluetooth_dbus.set_connection") as setter,
        ):
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                hw.set_bluetooth_connection(ADDRESS, True)
            with self.assertRaisesRegex(ValueError, "valid Bluetooth device"):
                hw.set_bluetooth_connection("AA:BB:CC", True)
            read.assert_called_once()
            which.assert_not_called()
            setter.assert_not_called()
            run.assert_not_called()


    def test_failed_cli_without_dbus_readback_refuses_fallback_mutation(self):
        old = bluetooth(connected=False)
        with (
            mock.patch.object(hw, "read_bluetooth", return_value=old),
            mock.patch.object(hw, "_bluetooth_via_dbus", return_value=None),
            mock.patch.object(hw.shutil, "which", return_value="/usr/bin/bluetoothctl"),
            mock.patch.object(hw.subprocess, "run",
                              return_value=subprocess.CompletedProcess([], 1)) as run,
            mock.patch("macrice.bluetooth_dbus.set_connection") as setter,
        ):
            with self.assertRaisesRegex(RuntimeError, "readback unavailable"):
                hw.set_bluetooth_connection(ADDRESS, True)
            run.assert_called_once()
            setter.assert_not_called()

    def test_failed_cli_power_without_dbus_readback_refuses_fallback_mutation(self):
        old = bluetooth(powered=False)
        with (
            mock.patch.object(hw, "read_bluetooth", return_value=old),
            mock.patch.object(hw, "_bluetooth_via_dbus", return_value=None),
            mock.patch.object(hw.shutil, "which", return_value="/usr/bin/bluetoothctl"),
            mock.patch.object(hw.subprocess, "run",
                              return_value=subprocess.CompletedProcess([], 1)) as run,
            mock.patch("macrice.bluetooth_dbus.set_power") as setter,
        ):
            with self.assertRaisesRegex(RuntimeError, "readback unavailable"):
                hw.set_bluetooth_power(True)
            run.assert_called_once()
            setter.assert_not_called()


if __name__ == "__main__":
    unittest.main()
