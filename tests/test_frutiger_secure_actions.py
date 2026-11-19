"""Credential and pairing actions must be verified and never expose secrets."""

import subprocess
import unittest
from unittest import mock

from macrice import hardware_status as hw
from macrice.riceware import spice


class SecureDeviceTests(unittest.TestCase):
    def test_wifi_secret_goes_only_to_stdin(self):
        password = "correct-horse-do-not-log"
        network = hw.WifiNetwork("MyNetwork", 88, "WPA2", True)
        with mock.patch.object(hw.shutil, "which", return_value="/usr/bin/nmcli"), \
                mock.patch.object(hw.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run, \
                mock.patch.object(hw, "read_wifi_networks", return_value=(network,)):
            self.assertTrue(hw.connect_wifi_secured("MyNetwork", password))
        command = run.call_args.args[0]
        self.assertEqual(command[:2], ["nmcli", "--ask"])
        self.assertNotIn(password, " ".join(command))
        self.assertEqual(run.call_args.kwargs["input"], password + "\n")
        self.assertTrue(run.call_args.kwargs["capture_output"])

    def test_wifi_error_does_not_return_secret_or_subprocess_output(self):
        password = "another-very-secret-value"
        failed = subprocess.CompletedProcess([], 10, stdout=password, stderr="bad " + password)
        with mock.patch.object(hw.shutil, "which", return_value="/usr/bin/nmcli"), \
                mock.patch.object(hw.subprocess, "run", return_value=failed):
            with self.assertRaisesRegex(RuntimeError, "authentication failed") as context:
                hw.connect_wifi_secured("Home", password)
        self.assertNotIn(password, str(context.exception))

    def test_wifi_credentials_are_validated_in_riceware_before_device_action(self):
        for invalid in (("MyNetwork", "short"), ("MyNetwork", "bad\npassw"),
                        ("network", "secretpassword", "extra"), ("network", None)):
            result = spice.change("wifi_connect_secure", invalid)
            self.assertEqual(result.status, "error")
            self.assertNotIn("secretpassword", result.reason or "")

    def test_bluetooth_pairing_requires_known_device_and_verifies_pair_state(self):
        address = "AA:BB:CC:DD:EE:FF"
        before = hw.BluetoothState(True, (), (hw.BluetoothDevice(address, "Headset", False, False),))
        after = hw.BluetoothState(True, (), (hw.BluetoothDevice(address, "Headset", True, False),))
        with mock.patch.object(hw, "read_bluetooth", side_effect=[before, after]), \
                mock.patch("macrice.bluetooth_dbus.pair_device") as pair:
            self.assertEqual(hw.pair_bluetooth_device(address), after)
        pair.assert_called_once_with(address)

    def test_discovery_requires_a_real_bluez_readback(self):
        with mock.patch("macrice.bluetooth_dbus.discover") as scan, \
                mock.patch.object(hw, "_bluetooth_via_dbus", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "device list is unavailable"):
                hw.scan_bluetooth_devices(duration=3)
        scan.assert_called_once_with(duration=3, cancel=None)

    def test_bluetooth_pairing_rejects_unknown_device_before_mutation(self):
        with mock.patch.object(hw, "read_bluetooth", return_value=hw.BluetoothState(True, (), ())):
            with self.assertRaisesRegex(ValueError, "Discover"):
                hw.pair_bluetooth_device("AA:BB:CC:DD:EE:FF")

    def test_bluetoothctl_still_works_when_gi_dbus_transport_is_missing(self):
        address = "AA:BB:CC:DD:EE:FF"
        before = hw.BluetoothState(True, (), (hw.BluetoothDevice(address, "Headset", False, False),))
        after = hw.BluetoothState(True, (), (hw.BluetoothDevice(address, "Headset", True, False),))
        with mock.patch.object(hw, "read_bluetooth", side_effect=[before, after]), \
                mock.patch("macrice.bluetooth_dbus.pair_device", side_effect=ImportError("GI unavailable")), \
                mock.patch.object(hw.shutil, "which", return_value="/usr/bin/bluetoothctl"), \
                mock.patch.object(hw.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(hw.pair_bluetooth_device(address), after)
        self.assertEqual(run.call_args.args[0], ["bluetoothctl", "pair", address])

    def test_bluetooth_pairing_transport_loss_never_replays_through_cli(self):
        address = "AA:BB:CC:DD:EE:FF"
        before = hw.BluetoothState(True, (), (
            hw.BluetoothDevice(address, "Headset", False, False),))
        with (
            mock.patch.object(hw, "read_bluetooth", return_value=before) as state,
            mock.patch("macrice.bluetooth_dbus.pair_device",
                       side_effect=OSError("BlueZ timed out")) as dbus,
            mock.patch.object(hw.shutil, "which") as which,
            mock.patch.object(hw.subprocess, "run") as cli,
        ):
            with self.assertRaisesRegex(RuntimeError, "outcome unknown"):
                hw.pair_bluetooth_device(address)
        dbus.assert_called_once_with(address)
        state.assert_called_once()
        which.assert_not_called()
        cli.assert_not_called()

    def test_bluetooth_pairing_caller_rejects_ambiguous_known_addresses(self):
        address = "AA:BB:CC:DD:EE:FF"
        before = hw.BluetoothState(True, (), (
            hw.BluetoothDevice(address, "First USB", False, False),
            hw.BluetoothDevice(address.lower(), "Second USB", False, False),
        ))
        with (
            mock.patch.object(hw, "read_bluetooth", return_value=before),
            mock.patch("macrice.bluetooth_dbus.pair_device") as pair,
            mock.patch.object(hw.subprocess, "run") as cli,
        ):
            with self.assertRaisesRegex(ValueError, "identity is ambiguous"):
                hw.pair_bluetooth_device(address)
            pair.assert_not_called()
            cli.assert_not_called()
