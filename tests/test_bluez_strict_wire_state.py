"""Strict BlueZ system-bus state and idempotent device actions for SG2.

These use fake ObjectManager replies and never access a real Bluetooth radio,
device, service or D-Bus connection.
"""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from macrice import bluetooth_dbus as bluez

ADDR = "AA:BB:CC:DD:EE:FF"
HCI = "/org/bluez/hci0"
DEVICE = HCI + "/dev_AA"


def objects(*, paired=True, connected=False):
    return {
        HCI: {"org.bluez.Adapter1": {"Powered": True}},
        DEVICE: {"org.bluez.Device1": {
            "Address": ADDR, "Paired": paired, "Connected": connected, "Alias": "Keyboard"}},
    }


def fake_connection():
    bus = Mock()
    return (SimpleNamespace(DBusCallFlags=SimpleNamespace(NONE=0)), bus)


class BluezStrictStateTests(unittest.TestCase):
    def test_snapshot_rejects_missing_and_non_boolean_device_state(self):
        for key in ("Paired", "Connected"):
            for invalid in (None, 0, 1, "false", "yes", [], {}):
                with self.subTest(key=key, invalid=invalid):
                    current = objects()
                    current[DEVICE]["org.bluez.Device1"][key] = invalid
                    with patch.object(bluez, "_objects", return_value=current), \
                            self.assertRaisesRegex(RuntimeError, "state is unavailable"):
                        bluez.snapshot()
            current = objects()
            del current[DEVICE]["org.bluez.Device1"][key]
            with self.subTest(key=key, missing=True), \
                    patch.object(bluez, "_objects", return_value=current), \
                    self.assertRaisesRegex(RuntimeError, "state is unavailable"):
                bluez.snapshot()

    def test_connection_never_writes_with_invalid_paired_or_connected_property(self):
        for key in ("Paired", "Connected"):
            for invalid in (None, 0, 1, "false", "true"):
                current = objects()
                current[DEVICE]["org.bluez.Device1"][key] = invalid
                with self.subTest(key=key, invalid=invalid), \
                        patch.object(bluez, "_objects", return_value=current), \
                        patch.object(bluez, "_connection") as bus, \
                        self.assertRaisesRegex(ValueError, "state is unavailable"):
                    bluez.set_connection(ADDR, True)
                bus.assert_not_called()

    def test_noop_connected_or_disconnected_device_is_never_resent(self):
        for desired in (False, True):
            with self.subTest(desired=desired), \
                    patch.object(bluez, "_objects",
                                 return_value=objects(connected=desired)), \
                    patch.object(bluez, "_connection") as bus:
                self.assertIsNone(bluez.set_connection(ADDR.lower(), desired))
                bus.assert_not_called()

    def test_change_uses_unique_live_path_and_case_insensitive_address(self):
        gio, bus = fake_connection()
        with patch.object(bluez, "_objects", return_value=objects()), \
                patch.object(bluez, "_connection", return_value=(gio, bus)):
            bluez.set_connection(ADDR.lower(), True)
        bus.call_sync.assert_called_once()
        self.assertEqual(bus.call_sync.call_args.args[1:4],
                         (DEVICE, "org.bluez.Device1", "Connect"))

    def test_connect_requires_exact_paired_boolean_not_truthiness(self):
        gio, bus = fake_connection()
        with patch.object(bluez, "_objects",
                          return_value=objects(paired=False)), \
                patch.object(bluez, "_connection", return_value=(gio, bus)), \
                self.assertRaisesRegex(ValueError, "Pair"):
            bluez.set_connection(ADDR, True)
        bus.call_sync.assert_not_called()

    def test_device_identity_cannot_cross_adapters_with_case_alias(self):
        current = objects()
        current["/org/bluez/hci1"] = {"org.bluez.Adapter1": {"Powered": True}}
        current["/org/bluez/hci1/dev_AA"] = {"org.bluez.Device1": {
            "Address": ADDR.lower(), "Paired": True, "Connected": False}}
        gio, bus = fake_connection()
        with patch.object(bluez, "_objects", return_value=current), \
                patch.object(bluez, "_connection", return_value=(gio, bus)):
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                bluez.set_connection(ADDR, True)
            bus.call_sync.assert_not_called()
            bluez.set_connection(ADDR, True,
                                 expected_adapter="/org/bluez/hci1")
            self.assertEqual(bus.call_sync.call_args.args[1],
                             "/org/bluez/hci1/dev_AA")


if __name__ == "__main__":
    unittest.main()
