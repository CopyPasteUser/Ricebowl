"""SG2 WP2.2 gap fill: adapter-level cells the inventory listed as `gap`.

Private fake ``nmcli`` / ``powerprofilesctl`` executables are the only binaries
on PATH; BlueZ is a fake Gio bus; MPRIS and the Orca session path use their
existing injection seams. Nothing touches a real system service.
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from macrice import authorization, bluetooth_dbus
from macrice.de import network_enrollment, session
from macrice.de import settings_backend as backend
from macrice.riceware import media

SECRET = "SECRET-STDERR-TOKEN"

PRIVATE_NMCLI = r'''#!%(py)s
import os, sys
from pathlib import Path
root = Path(os.environ["RICEBOWL_SG2_GAP_ROOT"])
args = [a for a in sys.argv[1:]]
while args and args[0] == "--wait":
    args = args[2:]
with (root / "calls.txt").open("a", encoding="utf-8") as log:
    log.write(" ".join(args[:3]) + "\n")
mode = (root / "mode").read_text().strip()
if args[:2] == ["con", "add"]:
    if mode == "deny":
        sys.stderr.write("Error: Not authorized to control networking. %(secret)s\n")
        sys.exit(1)
    if mode == "fail":
        sys.stderr.write("Error: NetworkManager is not running. %(secret)s\n")
        sys.exit(8)
    sys.exit(0)
sys.exit(9)
'''

PRIVATE_POWERPROFILESCTL = r'''#!%(py)s
import os, sys
from pathlib import Path
root = Path(os.environ["RICEBOWL_SG2_GAP_ROOT"])
args = sys.argv[1:]
mode = (root / "mode").read_text().strip()
state = root / "profile"
with (root / "calls.txt").open("a", encoding="utf-8") as log:
    log.write(" ".join(args) + "\n")
if args == ["get"]:
    print(state.read_text().strip())
elif args == ["list"]:
    print("  power-saver:\n    Driver: x\n* balanced:\n    Driver: x\n  performance:\n    Driver: x")
elif args[:1] == ["set"]:
    if mode == "deny":
        sys.stderr.write("Error: GDBus.Error:org.freedesktop.DBus.Error.AccessDenied: "
                         "Rejected send message %(secret)s\n")
        sys.exit(1)
    if mode == "fail":
        sys.stderr.write("Error: connection to power-profiles-daemon lost %(secret)s\n")
        sys.exit(1)
    state.write_text(args[1])
else:
    sys.exit(8)
'''


class _PrivateBinaries(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name, text in (("nmcli", PRIVATE_NMCLI),
                           ("powerprofilesctl", PRIVATE_POWERPROFILESCTL)):
            path = self.bin / name
            path.write_text(text % {"py": sys.executable, "secret": SECRET},
                            encoding="utf-8")
            path.chmod(0o700)
        (self.root / "profile").write_text("balanced")
        patcher = mock.patch.dict(os.environ, {
            "PATH": str(self.bin), "RICEBOWL_SG2_GAP_ROOT": str(self.root)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def mode(self, value):
        (self.root / "mode").write_text(value)

    def calls(self):
        path = self.root / "calls.txt"
        return path.read_text().splitlines() if path.exists() else []


class EnterpriseCreateDenialTests(_PrivateBinaries):
    """N5 AUTH: `nmcli con add` refusal is typed, single-shot and leak-free."""

    def create(self):
        with mock.patch.object(backend, "connection_profiles", return_value=[]):
            return network_enrollment.create_enterprise_wifi(
                ssid="Corp", identity="alice", domain="radius.example.com",
                eap="peap", inner="mschapv2")

    def test_n5_denied_con_add_is_typed_not_replayed_and_leaks_nothing(self):
        self.mode("deny")
        with self.assertRaises(backend.SettingsDenied) as caught:
            self.create()
        self.assertEqual(str(caught.exception), authorization.DENIED_MESSAGE)
        self.assertNotIn(SECRET, repr(caught.exception))
        self.assertEqual(len(self.calls()), 1, "denial must not be replayed")

    def test_n5_generic_failure_is_unknown_outcome_never_denial(self):
        self.mode("fail")
        with self.assertRaises(backend.SettingsError) as caught:
            self.create()
        self.assertNotIsInstance(caught.exception, backend.SettingsDenied)
        self.assertIn("outcome unknown", str(caught.exception))
        self.assertNotIn(SECRET, str(caught.exception))
        self.assertEqual(len(self.calls()), 1)


class PowerProfileDenialTests(_PrivateBinaries):
    """P1 AUTH: power-profiles-daemon polkit/AccessDenied refusal."""

    def change(self):
        return backend.set_power_profile("performance", expected="balanced")

    def test_p1_denied_profile_change_is_typed_and_not_replayed(self):
        self.mode("deny")
        with self.assertRaises(backend.SettingsDenied) as caught:
            self.change()
        self.assertEqual(str(caught.exception), authorization.DENIED_MESSAGE)
        self.assertNotIn(SECRET, repr(caught.exception))
        self.assertEqual([c for c in self.calls() if c.startswith("set")],
                         ["set performance"])
        self.assertEqual((self.root / "profile").read_text(), "balanced")

    def test_p1_generic_failure_stays_unknown_outcome_not_denial(self):
        self.mode("fail")
        with self.assertRaises(backend.SettingsError) as caught:
            self.change()
        self.assertNotIsInstance(caught.exception, backend.SettingsDenied)
        self.assertIn("outcome unknown", str(caught.exception))
        self.assertNotIn(SECRET, str(caught.exception))

    def test_p1_success_is_claimed_only_after_readback(self):
        self.mode("ok")
        self.assertEqual(self.change(), "performance")
        self.assertEqual((self.root / "profile").read_text(), "performance")


class _FakeSystemBus:
    def __init__(self, error=None, powered=True):
        self.error = error
        self.calls = []
        self.powered = powered

    def objects(self):
        return {"/org/bluez/hci0": {"org.bluez.Adapter1": {"Powered": self.powered}},
                "/org/bluez/hci0/dev_AA": {"org.bluez.Device1": {
                    "Address": "AA:BB:CC:DD:EE:FF", "Paired": False,
                    "Connected": False, "Name": "Pad"}}}

    def call_sync(self, dest, path, iface, method, *_rest):
        self.calls.append(method)
        if self.error is not None and method in self.error[0]:
            raise self.error[1]

    def patches(self):
        from gi.repository import Gio
        return (mock.patch.object(bluetooth_dbus, "_objects", self.objects),
                mock.patch.object(bluetooth_dbus, "_connection",
                                  return_value=(Gio, self)))


def _glib_error(name, text):
    from gi.repository import Gio, GLib
    return GLib.Error.new_literal(
        Gio.dbus_error_quark(), f"GDBus.Error:{name}: {text} {SECRET}", 0)


class BluetoothBackendOnlyDenialTests(unittest.TestCase):
    """B3/B4 AUTH: scan and pair have no RiceSpice caller (backend only).

    They must still never swallow a refusal into a fake success: the raw error
    propagates to the caller and discovery is released.
    """

    def setUp(self):
        try:
            from gi.repository import Gio  # noqa: F401
        except ImportError:
            self.skipTest("PyGObject is not installed")

    def test_b3_denied_start_discovery_propagates_and_releases_the_lock(self):
        bus = _FakeSystemBus((("StartDiscovery",), _glib_error(
            "org.bluez.Error.NotAuthorized", "refused")))
        first, second = bus.patches()
        with first, second, mock.patch.object(
                bluetooth_dbus, "snapshot",
                return_value=(True, "/org/bluez/hci0", [])):
            with self.assertRaises(Exception) as caught:
                bluetooth_dbus.discover(2, cancel=threading.Event())
        self.assertTrue(authorization.is_authorization_denial(str(caught.exception)))
        self.assertEqual(bus.calls, ["StartDiscovery"], "no StopDiscovery for an unowned session")
        self.assertTrue(bluetooth_dbus._DISCOVERY_LOCK.acquire(blocking=False))
        bluetooth_dbus._DISCOVERY_LOCK.release()

    def test_b4_denied_pair_propagates_once_and_is_not_reported_as_paired(self):
        bus = _FakeSystemBus((("Pair",), _glib_error(
            "org.bluez.Error.AuthenticationRejected", "refused")))
        first, second = bus.patches()
        with first, second:
            with self.assertRaises(Exception):
                bluetooth_dbus.pair_device("AA:BB:CC:DD:EE:FF",
                                           expected_adapter="/org/bluez/hci0")
        self.assertEqual(bus.calls, ["Pair"], "pair must not be retried")


class MprisVanishedPlayerTests(unittest.TestCase):
    """A5 RB: a command to a player that vanished is an error, not a success."""

    def test_a5_vanished_player_reports_error_and_never_dispatches(self):
        calls = []

        class Bus:
            def call_sync(self, dest, path, iface, method, *_rest):
                calls.append(method)
                raise RuntimeError("org.freedesktop.DBus.Error.ServiceUnknown")

        gio = SimpleNamespace(BusType=SimpleNamespace(SESSION=0),
                              DBusCallFlags=SimpleNamespace(NONE=0),
                              bus_get_sync=lambda *_a: Bus())
        glib = SimpleNamespace(Variant=lambda _s, v: v, VariantType=lambda s: s)
        with mock.patch.object(media, "_gio", return_value=(gio, glib)):
            with self.assertRaises(Exception):
                media.media_action("org.mpris.MediaPlayer2.gone", "PlayPause")
        self.assertNotIn("PlayPause", calls)


class OrcaProviderMissingTests(unittest.TestCase):
    """I3 PROV: Orca requested but absent starts nothing and says so."""

    def test_i3_requested_orca_not_installed_spawns_nothing_and_reports(self):
        spawned = []
        tools = {tool: "/usr/bin/" + tool for tool in (
            "waybar", "swaybg", "mako", "lxpolkit", "riceplate-native",
            "swayidle", "swaylock")}

        class Child:
            def poll(self): return None
            def terminate(self): pass
            def kill(self): pass
            def wait(self, timeout=None): return 0

        def spawn(command, **_kwargs):
            spawned.append(command[0])
            return Child()

        env = {"RICEBOWL_DE_SHELL_CHILD": "1", "WAYLAND_DISPLAY": "wayland-0",
               "RICEBOWL_DE_NESTED": "0", "RICEBOWL_DE_SCREEN_READER": "1"}
        err = io.StringIO()
        with mock.patch("macrice.de.session.signal.signal"), \
                mock.patch("sys.stderr", err), \
                mock.patch("macrice.de.notification_prefs.load_optional",
                           return_value=None):
            self.assertEqual(session.shell(environment=env, which=tools.get,
                                           spawn=spawn), 0)
        self.assertFalse([name for name in spawned if "orca" in name])
        self.assertIn("Orca screen reader requested but not installed", err.getvalue())


if __name__ == "__main__":
    unittest.main()
