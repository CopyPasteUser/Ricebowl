"""SG2 gaps 4/5: BlueZ and logind authorization refusal, rfkill block.

BlueZ is replaced at the Gio system-bus boundary (a fake bus raising real
GLib.Error values with GDBus.Error text); logind through a fake loginctl
subprocess. Asserts typed SettingsDenied, no raw text leak, no second
mutation/replay and that a blocked radio is never reported as success.
"""
from __future__ import annotations

import unittest
from unittest import mock

from macrice import authorization, bluetooth_dbus
from macrice.de import settings_backend as backend

ADAPTER = "/org/bluez/hci0"
ADDR = "AA:BB:CC:DD:EE:FF"
SECRET = "SECRET-BLUEZ-TOKEN"


def _glib_error(name, text):
    from gi.repository import Gio, GLib
    return GLib.Error.new_literal(
        Gio.dbus_error_quark(), f"GDBus.Error:{name}: {text} {SECRET}", 0)


class FakeBlueZ:
    """Fake system bus: tracks Powered/Connected; Set/Connect may raise."""

    def __init__(self, fail=None, apply_on_fail=False):
        self.powered = False
        self.connected = False
        self.fail = fail
        self.apply_on_fail = apply_on_fail
        self.mutations = []

    def objects(self):
        return {ADAPTER: {"org.bluez.Adapter1": {"Powered": self.powered}},
                ADAPTER + "/dev_AA": {"org.bluez.Device1": {
                    "Address": ADDR, "Name": "Headset", "Paired": True,
                    "Connected": self.connected}}}

    def call_sync(self, dest, path, iface, method, params, *_rest):
        self.mutations.append((path, iface, method))
        if self.fail is not None:
            raise self.fail
        if method == "Set":
            self.powered = params.unpack()[2]
        elif method in ("Connect", "Disconnect"):
            self.connected = method == "Connect"

    def patches(self):
        from gi.repository import Gio
        return (mock.patch.object(bluetooth_dbus, "_objects", self.objects),
                mock.patch.object(bluetooth_dbus, "_connection",
                                  return_value=(Gio, self)))


class BluetoothDenialTests(unittest.TestCase):
    def run_power(self, bus, enabled, expected):
        first, second = bus.patches()
        with first, second:
            return backend.set_bluetooth_power(enabled, expected=expected,
                                               expected_adapter=ADAPTER)

    def run_connect(self, bus, connected, expected):
        first, second = bus.patches()
        with first, second:
            return backend.set_bluetooth_connection(
                ADDR, connected, expected=expected, expected_adapter=ADAPTER)

    def test_bt_denied_power_on_and_off_is_typed_and_not_replayed(self):
        for name in ("org.bluez.Error.NotAuthorized",
                     "org.freedesktop.DBus.Error.AccessDenied"):
            for enabled in (True, False):
                with self.subTest(error=name, enabled=enabled):
                    bus = FakeBlueZ(_glib_error(name, "refused"))
                    bus.powered = not enabled
                    with self.assertRaises(backend.SettingsDenied) as caught:
                        self.run_power(bus, enabled, not enabled)
                    self.assertEqual(str(caught.exception), authorization.DENIED_MESSAGE)
                    self.assertNotIn(SECRET, str(caught.exception))
                    self.assertEqual(len(bus.mutations), 1, "no second mutation")
                    self.assertEqual(bus.powered, not enabled)

    def test_bt_denied_connect_and_disconnect_is_typed_and_not_replayed(self):
        for name in ("org.bluez.Error.NotAuthorized",
                     "org.freedesktop.DBus.Error.AccessDenied"):
            for connected in (True, False):
                with self.subTest(error=name, connected=connected):
                    bus = FakeBlueZ(_glib_error(name, "refused"))
                    bus.powered = True
                    bus.connected = not connected
                    with self.assertRaises(backend.SettingsDenied) as caught:
                        self.run_connect(bus, connected, not connected)
                    self.assertNotIn(SECRET, str(caught.exception))
                    self.assertEqual([m[2] for m in bus.mutations],
                                     ["Connect" if connected else "Disconnect"])
                    self.assertEqual(bus.connected, not connected)

    def test_bt_rfkill_blocked_power_on_is_honest_failure_not_success(self):
        bus = FakeBlueZ(_glib_error("org.bluez.Error.Failed", "Blocked through rfkill"))
        with self.assertRaises(backend.SettingsError) as caught:
            self.run_power(bus, True, False)
        self.assertNotIsInstance(caught.exception, backend.SettingsDenied)
        text = str(caught.exception)
        self.assertIn("blocked by rfkill", text)
        self.assertIn("not turned on", text)
        self.assertNotIn("outcome unknown", text)
        self.assertNotIn(SECRET, text)
        self.assertEqual(len(bus.mutations), 1)
        self.assertFalse(bus.powered)

    def test_bt_powered_stays_false_after_accepted_set_is_never_success(self):
        class Stuck(FakeBlueZ):
            def call_sync(self, *args):
                self.mutations.append(args[1:4])   # accepted, but rfkill keeps it off
        bus = Stuck()
        with self.assertRaisesRegex(backend.SettingsError, "could not be verified"):
            self.run_power(bus, True, False)
        self.assertEqual(len(bus.mutations), 1)

    def test_bt_other_failures_stay_unknown_outcome_not_denial(self):
        for exc in (_glib_error("org.bluez.Error.Failed", "Operation failed"),
                    _glib_error("org.bluez.Error.InProgress", "busy"),
                    RuntimeError("bus vanished")):
            with self.subTest(exc=str(exc)[:40]):
                bus = FakeBlueZ(exc)
                with self.assertRaises(backend.SettingsError) as caught:
                    self.run_power(bus, True, False)
                self.assertNotIsInstance(caught.exception, backend.SettingsDenied)
                self.assertIn("outcome unknown", str(caught.exception))
                self.assertNotIn(SECRET, str(caught.exception))

    def test_bt_success_controls_claim_only_after_readback(self):
        bus = FakeBlueZ()
        self.assertTrue(self.run_power(bus, True, False)["powered"])
        bus = FakeBlueZ()
        bus.powered = True
        result = self.run_connect(bus, True, False)
        self.assertTrue(result["devices"][0]["connected"])


class LogindDenialTests(unittest.TestCase):
    def run_action(self, action, loginctl_stderr, loginctl_code=1):
        calls = []

        def fake_run(argv, **_kw):
            calls.append(argv[0].rsplit("/", 1)[-1] + " " + " ".join(argv[1:]))
            if argv[0].endswith("swaylock"):
                return mock.Mock(returncode=0, stderr=b"")
            return mock.Mock(returncode=loginctl_code, stderr=loginctl_stderr, stdout=b"")

        with mock.patch.object(backend.shutil, "which",
                               side_effect=lambda name: "/usr/bin/" + name), \
             mock.patch.object(backend.subprocess, "run", side_effect=fake_run), \
             mock.patch.dict(backend.os.environ, {"RICEBOWL_DE_NESTED": "0"}):
            try:
                backend.power_action(action)
            finally:
                self.calls = calls

    def test_pw_logind_refusal_is_typed_denial_and_suspend_not_retried(self):
        for stderr in (b"Failed to suspend system via logind: Interactive authentication required. " + SECRET.encode(),
                       b"Call failed: Access denied " + SECRET.encode(),
                       b"org.freedesktop.DBus.Error.AccessDenied: " + SECRET.encode()):
            with self.subTest(stderr=stderr[:30]):
                with self.assertRaises(backend.SettingsDenied) as caught:
                    self.run_action("suspend", stderr)
                self.assertEqual(str(caught.exception), authorization.DENIED_MESSAGE)
                self.assertNotIn(SECRET, str(caught.exception))
                self.assertEqual(self.calls, ["swaylock -f", "loginctl suspend"])

    def test_pw_logind_generic_failure_claims_no_suspend_and_is_not_denial(self):
        with self.assertRaises(backend.SettingsError) as caught:
            self.run_action("suspend", b"Failed to connect to bus " + SECRET.encode())
        self.assertNotIsInstance(caught.exception, backend.SettingsDenied)
        self.assertIn("nothing was suspended", str(caught.exception))
        self.assertNotIn(SECRET, str(caught.exception))

    def test_pw_lock_never_invokes_loginctl(self):
        self.run_action("lock", b"", 0)
        self.assertEqual(self.calls, ["swaylock -f"])

    def test_pw_failed_lock_never_reaches_logind(self):
        with mock.patch.object(backend.shutil, "which",
                               side_effect=lambda name: "/usr/bin/" + name), \
             mock.patch.object(backend.subprocess, "run",
                               return_value=mock.Mock(returncode=1, stderr=b"")) as run, \
             mock.patch.dict(backend.os.environ, {"RICEBOWL_DE_NESTED": "0"}):
            with self.assertRaisesRegex(backend.SettingsError, "lock failed"):
                backend.power_action("suspend")
        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
