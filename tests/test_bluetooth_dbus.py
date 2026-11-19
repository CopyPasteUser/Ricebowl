"""Tests for BlueZ D-Bus parsing without a daemon or Bluetooth adapter."""

import unittest
from unittest.mock import Mock, patch

from macrice import bluetooth_dbus


class BluetoothDbusTests(unittest.TestCase):
    @patch("macrice.bluetooth_dbus._connection")
    def test_object_manager_uses_real_glib_variant_type(self, connection):
        from gi.repository import Gio

        bus = connection.return_value[1]
        connection.return_value = (Gio, bus)
        bus.call_sync.return_value.unpack.return_value = ({},)
        self.assertEqual(bluetooth_dbus._objects(), {})
        self.assertEqual(bus.call_sync.call_args.args[3], "GetManagedObjects")

    @patch("macrice.bluetooth_dbus._objects")
    def test_dbus_objects_are_scoped_to_selected_adapter(self, objects):
        objects.return_value = {
            "/org/bluez/hci0": {"org.bluez.Adapter1": {"Powered": True}},
            "/org/bluez/hci1": {"org.bluez.Adapter1": {"Powered": False}},
            "/org/bluez/hci0/dev_AA": {"org.bluez.Device1": {
                "Address": "AA:BB:CC:DD:EE:FF", "Alias": "Keyboard", "Paired": True,
                "Connected": False}},
            "/org/bluez/hci1/dev_FF": {"org.bluez.Device1": {
                "Address": "FF:EE:DD:CC:BB:AA", "Alias": "Other", "Paired": True,
                "Connected": True}},
        }
        self.assertEqual(bluetooth_dbus.snapshot(), (
            True, "/org/bluez/hci0", (("AA:BB:CC:DD:EE:FF", "Keyboard", True, False),)))

    @patch("macrice.bluetooth_dbus._objects", return_value={})
    def test_no_adapter_is_not_powered_off(self, _objects):
        with self.assertRaisesRegex(RuntimeError, "No BlueZ adapter"):
            bluetooth_dbus.snapshot()

    @patch("macrice.bluetooth_dbus._connection")
    @patch("macrice.bluetooth_dbus._objects")
    def test_device_method_targets_only_live_paired_path(self, objects, connection):
        from gi.repository import Gio

        bus = connection.return_value[1]
        connection.return_value = (Gio, bus)
        objects.return_value = {
            "/org/bluez/hci0/dev_AA": {"org.bluez.Device1": {
                "Address": "AA:BB:CC:DD:EE:FF", "Paired": True, "Connected": False}},
        }
        bluetooth_dbus.set_connection("AA:BB:CC:DD:EE:FF", True)
        self.assertEqual(bus.call_sync.call_args.args[1:4],
                         ("/org/bluez/hci0/dev_AA", "org.bluez.Device1", "Connect"))
        objects.return_value["/org/bluez/hci0/dev_AA"]["org.bluez.Device1"]["Paired"] = False
        with self.assertRaisesRegex(ValueError, "Pair"):
            bluetooth_dbus.set_connection("AA:BB:CC:DD:EE:FF", True)

    @patch("macrice.bluetooth_dbus._connection")
    @patch("macrice.bluetooth_dbus._objects")
    def test_same_device_address_on_two_adapters_must_not_cross_bind(self, objects, connection):
        from gi.repository import Gio

        bus = connection.return_value[1]
        connection.return_value = (Gio, bus)
        addr = "AA:BB:CC:DD:EE:FF"
        objects.return_value = {
            "/org/bluez/hci0": {"org.bluez.Adapter1": {"Powered": True}},
            "/org/bluez/hci1": {"org.bluez.Adapter1": {"Powered": True}},
            "/org/bluez/hci0/dev_AA": {"org.bluez.Device1": {
                "Address": addr, "Paired": True, "Connected": False}},
            "/org/bluez/hci1/dev_AA": {"org.bluez.Device1": {
                "Address": addr, "Paired": True, "Connected": False}},
        }
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            bluetooth_dbus.set_connection(addr, True)
        bus.call_sync.assert_not_called()

        bluetooth_dbus.set_connection(addr, True, expected_adapter="/org/bluez/hci1")
        self.assertEqual(bus.call_sync.call_args.args[1:4],
                         ("/org/bluez/hci1/dev_AA", "org.bluez.Device1", "Connect"))
        bus.reset_mock()
        with self.assertRaisesRegex(ValueError, "adapter changed"):
            bluetooth_dbus.set_connection(addr, True, expected_adapter="/org/bluez/hci9")
        bus.call_sync.assert_not_called()

        # A path from a disappeared adapter cannot become a valid target.
        del objects.return_value["/org/bluez/hci1"]
        with self.assertRaisesRegex(ValueError, "adapter changed"):
            bluetooth_dbus.set_connection(addr, True, expected_adapter="/org/bluez/hci1")
        bus.call_sync.assert_not_called()
        objects.return_value["/org/bluez/hci1"] = {"org.bluez.Adapter1": {}}
        objects.return_value["/org/bluez/hci1/dev_BB"] = {"org.bluez.Device1": {
            "Address": addr, "Paired": True, "Connected": False}}
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            bluetooth_dbus.set_connection(addr, True, expected_adapter="/org/bluez/hci1")
        bus.call_sync.assert_not_called()

    @patch("macrice.bluetooth_dbus._connection")
    @patch("macrice.bluetooth_dbus._objects")
    def test_connection_rejects_malformed_identity_before_mutation(self, objects, connection):
        objects.return_value = {"/org/bluez/hci0": {"org.bluez.Adapter1": {}}}
        for address, connected, adapter in (
            ("not-a-bluetooth-address", True, None),
            ("AA:BB:CC:DD:EE:FF", 1, None),
            ("AA:BB:CC:DD:EE:FF", True, "/invalid/adapter"),
            ("AA:BB:CC:DD:EE:FF", True, True),
        ):
            with self.subTest(address=address, adapter=adapter), \
                 self.assertRaises(ValueError):
                bluetooth_dbus.set_connection(address, connected, expected_adapter=adapter)
        connection.assert_not_called()

    @patch("macrice.bluetooth_dbus._connection")
    @patch("macrice.bluetooth_dbus.snapshot", return_value=(True, "/org/bluez/hci0", ()))
    def test_scan_is_explicit_bounded_and_always_stopped(self, snapshot, connection):
        from gi.repository import Gio

        bus = Mock()
        connection.return_value = (Gio, bus)
        cancel = Mock()
        cancel.is_set.return_value = False
        self.assertEqual(bluetooth_dbus.discover(duration=3, cancel=cancel),
                         (True, "/org/bluez/hci0", ()))
        cancel.wait.assert_called_once_with(3)
        self.assertEqual([call.args[3] for call in bus.call_sync.call_args_list],
                         ["StartDiscovery", "StopDiscovery"])
        self.assertEqual(snapshot.call_count, 2)

        cancel.wait.side_effect = RuntimeError("interrupted")
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            bluetooth_dbus.discover(duration=3, cancel=cancel)
        self.assertEqual(bus.call_sync.call_args_list[-1].args[3], "StopDiscovery")

    @patch("macrice.bluetooth_dbus._connection")
    @patch("macrice.bluetooth_dbus.snapshot", return_value=(False, "/org/bluez/hci0", ()))
    def test_scan_never_starts_without_power(self, _snapshot, connection):
        with self.assertRaisesRegex(RuntimeError, "Turn Bluetooth on"):
            bluetooth_dbus.discover(duration=3)
        connection.assert_not_called()

    def test_only_one_discovery_session_per_process(self):
        with bluetooth_dbus._DISCOVERY_LOCK:
            with self.assertRaisesRegex(RuntimeError, "already running"):
                bluetooth_dbus.discover(duration=3)

    @patch("macrice.bluetooth_dbus._connection")
    @patch("macrice.bluetooth_dbus._objects")
    def test_pair_uses_known_bluez_object_and_default_agent(self, objects, connection):
        from gi.repository import Gio

        connection.return_value = (Gio, Mock())
        objects.return_value = {
            "/org/bluez/hci0/dev_AA": {"org.bluez.Device1": {
                "Address": "AA:BB:CC:DD:EE:FF", "Paired": False}},
        }
        bluetooth_dbus.pair_device("AA:BB:CC:DD:EE:FF")
        args = connection.return_value[1].call_sync.call_args.args
        self.assertEqual(args[1:4], ("/org/bluez/hci0/dev_AA", "org.bluez.Device1", "Pair"))
        with self.assertRaises(ValueError):
            bluetooth_dbus.pair_device("not-a-device")


    @patch("macrice.bluetooth_dbus._connection")
    @patch("macrice.bluetooth_dbus._objects")
    def test_pair_rejects_same_address_on_multiple_adapters(self, objects, connection):
        from gi.repository import Gio

        address = "AA:BB:CC:DD:EE:FF"
        connection.return_value = (Gio, Mock())
        objects.return_value = {
            "/org/bluez/hci0": {"org.bluez.Adapter1": {"Powered": True}},
            "/org/bluez/hci1": {"org.bluez.Adapter1": {"Powered": True}},
            "/org/bluez/hci0/dev_AA": {"org.bluez.Device1": {
                "Address": address, "Paired": True}},
            "/org/bluez/hci1/dev_AA": {"org.bluez.Device1": {
                "Address": address, "Paired": False}},
        }
        # Even a paired first result cannot mask another unpaired device.
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            bluetooth_dbus.pair_device(address.lower())
        connection.assert_not_called()
        bluetooth_dbus.pair_device(address, expected_adapter="/org/bluez/hci1")
        self.assertEqual(connection.return_value[1].call_sync.call_args.args[1:4],
                         ("/org/bluez/hci1/dev_AA", "org.bluez.Device1", "Pair"))
        connection.reset_mock()
        bluetooth_dbus.pair_device(address, expected_adapter="/org/bluez/hci0")
        connection.assert_not_called()  # Only the selected already-paired device.

    @patch("macrice.bluetooth_dbus._connection")
    @patch("macrice.bluetooth_dbus._objects")
    def test_pair_rejects_missing_adapter_and_duplicate_same_adapter(self, objects, connection):
        address = "AA:BB:CC:DD:EE:FF"
        objects.return_value = {
            "/org/bluez/hci0": {"org.bluez.Adapter1": {"Powered": True}},
            "/org/bluez/hci0/dev_AA": {"org.bluez.Device1": {
                "Address": address, "Paired": False}},
        }
        for adapter in ("/org/bluez/hci9", True, "/tmp/arbitrary"):
            with self.subTest(adapter=adapter), self.assertRaisesRegex(
                    ValueError, "adapter changed"):
                bluetooth_dbus.pair_device(address, expected_adapter=adapter)
        del objects.return_value["/org/bluez/hci0"]
        with self.assertRaisesRegex(ValueError, "adapter changed"):
            bluetooth_dbus.pair_device(address, expected_adapter="/org/bluez/hci0")
        objects.return_value["/org/bluez/hci0"] = {"org.bluez.Adapter1": {}}
        objects.return_value["/org/bluez/hci0/dev_BB"] = {"org.bluez.Device1": {
            "Address": address.lower(), "Paired": False}}
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            bluetooth_dbus.pair_device(address, expected_adapter="/org/bluez/hci0")
        connection.assert_not_called()

    @patch("macrice.bluetooth_dbus._connection")
    @patch("macrice.bluetooth_dbus._objects")
    def test_pair_rejects_unknown_paired_state_without_dbus_mutation(self, objects, connection):
        address = "AA:BB:CC:DD:EE:FF"
        props = {"Address": address, "Paired": None}
        objects.return_value = {
            "/org/bluez/hci0/dev_AA": {"org.bluez.Device1": props},
        }
        for bad in (None, "false", 0, 1):
            with self.subTest(bad=bad):
                props["Paired"] = bad
                with self.assertRaisesRegex(ValueError, "state is unavailable"):
                    bluetooth_dbus.pair_device(address)
        connection.assert_not_called()

    @patch("macrice.bluetooth_dbus._connection")
    @patch("macrice.bluetooth_dbus._objects")
    def test_pair_legacy_unique_device_and_idempotent_paired_state(self, objects, connection):
        from gi.repository import Gio

        address = "AA:BB:CC:DD:EE:FF"
        connection.return_value = (Gio, Mock())
        props = {"Address": address, "Paired": False}
        objects.return_value = {
            "/org/bluez/hci0/dev_AA": {"org.bluez.Device1": props},
        }
        bluetooth_dbus.pair_device(address.lower())
        connection.return_value[1].call_sync.assert_called_once()
        props["Paired"] = True
        connection.reset_mock()
        bluetooth_dbus.pair_device(address)
        connection.assert_not_called()



if __name__ == "__main__":
    unittest.main()
