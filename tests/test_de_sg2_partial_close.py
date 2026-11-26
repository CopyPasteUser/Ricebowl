"""SG2 WP2.3: adapter-level evidence for the inventory cells that were `~`.

Private fake ``nmcli`` executables (radio and enterprise connect), a fake
BlueZ Gio bus and the real preference store in a temporary XDG directory. No
real system service is contacted.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from macrice import authorization, bluetooth_dbus
from macrice.de import network_enrollment as enrollment
from macrice.de import preferences
from macrice.de import settings_backend as backend

SECRET = "SECRET-STDERR-TOKEN"
PASSWORD = "private-secret"
UUID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

RADIO_NMCLI = r'''#!%(py)s
import os, sys
from pathlib import Path
root = Path(os.environ["RICEBOWL_SG2_PARTIAL_ROOT"])
args = sys.argv[1:]
while args and args[0] == "--wait":
    args = args[2:]
with (root / "calls.txt").open("a", encoding="utf-8") as log:
    log.write(" ".join(args) + "\n")
mode = (root / "mode").read_text().strip()
state = root / "radio"
if args == ["radio", "wifi"]:
    if mode == "nm-down":
        sys.stderr.write("Error: NetworkManager is not running. %(secret)s\n")
        sys.exit(8)
    print(state.read_text().strip())
elif args[:2] == ["radio", "wifi"] and len(args) == 3:
    if mode == "write-fails":
        sys.stderr.write("Error: Timeout expired %(secret)s\n")
        sys.exit(3)
    state.write_text("enabled" if args[2] == "on" else "disabled")
else:
    sys.exit(9)
'''

FIELDS = {
    "802-11-wireless-security.key-mgmt": "wpa-eap",
    "802-1x.eap": "peap",
    "802-1x.phase2-auth": "mschapv2",
    "802-1x.domain-suffix-match": "radius.school.example",
    "802-1x.system-ca-certs": "yes",
    "802-1x.ca-cert": "",
    "802-1x.password-flags": "2",
    "802-11-wireless.ssid": "Campus",
    "802-1x.identity": "student",
}

ENTERPRISE_NMCLI = r'''#!%(py)s
import json, os, sys
from pathlib import Path
root = Path(os.environ["RICEBOWL_SG2_PARTIAL_ROOT"])
state = json.loads((root / "state.json").read_text())
args = sys.argv[1:]
while args and args[0] == "--wait":
    args = args[2:]
uuid = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
if args == ["-t", "-e", "yes", "-f", "UUID,TYPE,NAME,DEVICE", "con", "show"]:
    print(uuid + ":wifi:Campus profile:--")
elif args == ["-t", "-e", "yes", "-f", "UUID", "con", "show", "--active"]:
    if state["active"]:
        print(uuid)
elif len(args) == 6 and args[0] == "-g" and args[2:] == ["con", "show", "uuid", uuid]:
    print(state["fields"][args[1]])
elif args == ["con", "up", "uuid", uuid, "passwd-file", "/dev/stdin"]:
    sys.stdin.read()
    with (root / "mutations.txt").open("a") as receipt:
        receipt.write("enterprise-up\n")
    sys.stderr.write("Error: Connection activation failed: Not authorized to "
                     "control networking. %(secret)s\n")
    sys.exit(1)
else:
    sys.exit(8)
'''


class RadioProviderMissingTests(unittest.TestCase):
    """N1 PROV: a missing/unreachable NetworkManager never mutates or fakes state."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / "bin").mkdir()
        binary = self.root / "bin" / "nmcli"
        binary.write_text(RADIO_NMCLI % {"py": sys.executable, "secret": SECRET})
        binary.chmod(0o700)
        (self.root / "radio").write_text("enabled")
        (self.root / "mode").write_text("ok")
        patcher = mock.patch.dict(os.environ, {
            "PATH": str(self.root / "bin"),
            "RICEBOWL_SG2_PARTIAL_ROOT": str(self.root)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def calls(self):
        path = self.root / "calls.txt"
        return path.read_text().splitlines() if path.exists() else []

    def test_n1_nmcli_not_installed_is_an_error_and_never_a_state(self):
        with mock.patch.dict(os.environ, {"PATH": str(self.root)}):
            with self.assertRaisesRegex(backend.SettingsError, "nmcli is not installed"):
                backend.set_wifi(False, expected=True)
        self.assertEqual(self.calls(), [])

    def test_n1_networkmanager_not_running_fails_before_any_write(self):
        (self.root / "mode").write_text("nm-down")
        with self.assertRaises(backend.SettingsError) as caught:
            backend.set_wifi(False, expected=True)
        self.assertNotIsInstance(caught.exception, backend.SettingsDenied)
        self.assertNotIn(SECRET, str(caught.exception))
        self.assertEqual(self.calls(), ["radio wifi"], "only the read was attempted")

    def test_n1_provider_lost_during_write_is_unknown_outcome_single_shot(self):
        (self.root / "mode").write_text("write-fails")
        with self.assertRaisesRegex(backend.SettingsError, "outcome unknown"):
            backend.set_wifi(False, expected=True)
        self.assertEqual(self.calls(), ["radio wifi", "radio wifi off"])
        self.assertEqual((self.root / "radio").read_text(), "enabled")

    def test_n1_success_is_verified_by_readback(self):
        self.assertFalse(backend.set_wifi(False, expected=True))
        self.assertEqual((self.root / "radio").read_text(), "disabled")


class EnterpriseCreateConcurrencyTests(unittest.TestCase):
    """N5 BUSY: a profile another client added meanwhile is never adopted."""

    FIELD_VALUES = {
        "connection.autoconnect": "no",
        "802-11-wireless-security.key-mgmt": "wpa-eap",
        "802-1x.eap": "peap", "802-1x.phase2-auth": "mschapv2",
        "802-1x.domain-suffix-match": "radius.example.com",
        "802-1x.system-ca-certs": "yes", "802-1x.ca-cert": "",
        "802-1x.password-flags": "2", "802-11-wireless.ssid": "Corp",
        "802-1x.identity": "alice",
    }

    def run_create(self, include_ours):
        foreign = {"uuid": "ffffffff-0000-4000-8000-000000000001",
                   "kind": "wifi", "name": "Corp (other client)", "active": False}
        ran = []
        ours = {}

        def provider(*args, **_kwargs):
            ran.append(args)
            if args[:2] == ("con", "add"):
                ours["uuid"] = args[args.index("connection.uuid") + 1]
                return ""
            if args[0] == "-g":
                return self.FIELD_VALUES[args[1]]
            raise AssertionError(args)

        def inventory():
            if "uuid" not in ours:
                return []
            mine = {"uuid": ours["uuid"], "kind": "wifi", "name": "RiceSpice · Corp",
                    "active": False}
            return [foreign, mine] if include_ours else [foreign]

        with mock.patch.object(backend, "connection_profiles", side_effect=inventory), \
                mock.patch.object(enrollment, "_run", side_effect=provider):
            try:
                result = enrollment.create_enterprise_wifi(
                    ssid="Corp", identity="alice", domain="radius.example.com",
                    eap="peap", inner="mschapv2")
            except backend.SettingsError as exc:
                result = exc
        return result, ran, ours.get("uuid"), foreign["uuid"]

    def test_n5_concurrent_foreign_profile_is_not_mistaken_for_ours(self):
        result, ran, ours, foreign = self.run_create(include_ours=True)
        self.assertEqual(result, ours)
        self.assertNotEqual(result, foreign)
        self.assertEqual([a[:2] for a in ran].count(("con", "add")), 1)

    def test_n5_only_foreign_profile_present_fails_closed_without_replay(self):
        result, ran, _ours, _foreign = self.run_create(include_ours=False)
        self.assertIsInstance(result, backend.SettingsError)
        self.assertIn("could not be verified", str(result))
        self.assertEqual(len(ran), 1, "no second con add, no modify, no delete")

    def test_n5_overlapping_creates_each_issue_one_distinct_add(self):
        adds, lock = [], threading.Lock()

        def provider(*args, **_kwargs):
            if args[:2] == ("con", "add"):
                with lock:
                    adds.append(args[args.index("connection.uuid") + 1])
                return ""
            if args[0] == "-g":
                return self.FIELD_VALUES[args[1]]
            raise AssertionError(args)

        def inventory():
            with lock:
                return [{"uuid": u, "kind": "wifi", "name": "RiceSpice · Corp",
                         "active": False} for u in adds]

        results = []

        def worker():
            try:
                results.append(enrollment.create_enterprise_wifi(
                    ssid="Corp", identity="alice", domain="radius.example.com",
                    eap="peap", inner="mschapv2"))
            except backend.SettingsError as exc:
                results.append(exc)

        with mock.patch.object(backend, "connection_profiles", side_effect=inventory), \
                mock.patch.object(enrollment, "_run", side_effect=provider):
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(5)
        self.assertEqual(len(adds), 2)
        self.assertEqual(len(set(adds)), 2, "each attempt has its own UUID")
        self.assertEqual(sorted(r for r in results if isinstance(r, str)), sorted(adds))


class EnterpriseConnectPolkitDenialTests(unittest.TestCase):
    """N6 AUTH: a real polkit denial text on `con up` is typed, not "unknown"."""

    def test_n6_polkit_denial_text_on_activation_is_typed_and_single_shot(self):
        with tempfile.TemporaryDirectory(prefix="ricebowl-sg2-partial-") as tmp:
            root = Path(tmp)
            binary = root / "nmcli"
            binary.write_text(ENTERPRISE_NMCLI % {"py": sys.executable, "secret": SECRET})
            binary.chmod(0o700)
            (root / "state.json").write_text(json.dumps(
                {"active": False, "fields": FIELDS}))
            with mock.patch.dict(os.environ, {"RICEBOWL_SG2_PARTIAL_ROOT": str(root)}), \
                    mock.patch.object(shutil, "which", return_value=str(binary)):
                with self.assertRaises(backend.SettingsDenied) as caught:
                    enrollment.connect_enterprise_wifi(UUID, PASSWORD)
            self.assertEqual(str(caught.exception), authorization.DENIED_MESSAGE)
            self.assertNotIn(SECRET, repr(caught.exception))
            self.assertNotIn(PASSWORD, repr(caught.exception))
            self.assertEqual((root / "mutations.txt").read_text(), "enterprise-up\n")
            self.assertFalse(json.loads((root / "state.json").read_text())["active"])


class VpnImportNeverRollsBackTests(unittest.TestCase):
    """N7 RBK: explicit no-rollback-by-design. After the import write, no
    failure path deletes, downs or re-imports anything."""

    def test_n7_no_destructive_or_repeat_command_in_any_failure_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "office.ovpn")
            source.write_text("client\nremote vpn.example.net 1194\n")
            imported = {"uuid": UUID, "kind": "vpn", "active": False, "name": "office"}
            cases = {
                "modify-fails": ([[], [imported]],
                                 ["", backend.SettingsError("lost")], "unverified"),
                "autoconnect-still-on": ([[], [imported]], ["", "", "yes"],
                                         "could not be disabled"),
                "became-active": ([[], [imported], [{**imported, "active": True}]],
                                  ["", "", "no"], "became active"),
                "inventory-lost": ([[], backend.SettingsError("gone")], [""],
                                   "inventory is unavailable"),
            }
            for name, (inventory, replies, message) in cases.items():
                with self.subTest(case=name):
                    argv = []

                    def run(*args, **_kw):
                        argv.append(args)
                        reply = replies[len(argv) - 1]
                        if isinstance(reply, Exception):
                            raise reply
                        return reply

                    with mock.patch.object(backend, "connection_profiles",
                                           side_effect=inventory), \
                            mock.patch.object(enrollment, "_run", side_effect=run):
                        with self.assertRaisesRegex(backend.SettingsError, message):
                            enrollment.import_vpn_profile(str(source))
                    verbs = [a[:2] for a in argv]
                    self.assertEqual(verbs.count(("con", "import")), 1)
                    for forbidden in (("con", "delete"), ("con", "down")):
                        self.assertNotIn(forbidden, verbs)


class _PairBus:
    """Fake BlueZ bus whose Pair either takes effect or is accepted but ignored."""

    def __init__(self, effective):
        self.effective = effective
        self.calls = []
        self.paired = False

    def objects(self):
        return {"/org/bluez/hci0": {"org.bluez.Adapter1": {"Powered": True}},
                "/org/bluez/hci0/dev_AA": {"org.bluez.Device1": {
                    "Address": "AA:BB:CC:DD:EE:FF", "Paired": self.paired}}}

    def call_sync(self, dest, path, iface, method, *_rest):
        self.calls.append(method)
        if method == "Pair" and self.effective:
            self.paired = True

    def patches(self):
        from gi.repository import Gio
        return (mock.patch.object(bluetooth_dbus, "_objects", self.objects),
                mock.patch.object(bluetooth_dbus, "_connection",
                                  return_value=(Gio, self)))


class BluetoothPairReadbackTests(unittest.TestCase):
    """B4 RB: pairing is claimed only after the device reads back as Paired."""

    def setUp(self):
        try:
            from gi.repository import Gio  # noqa: F401
        except ImportError:
            self.skipTest("PyGObject is not installed")

    def pair(self, bus):
        first, second = bus.patches()
        with first, second:
            return bluetooth_dbus.pair_device("AA:BB:CC:DD:EE:FF",
                                              expected_adapter="/org/bluez/hci0")

    def test_b4_verified_pair_succeeds_once(self):
        bus = _PairBus(effective=True)
        self.pair(bus)
        self.assertEqual(bus.calls, ["Pair"])
        self.assertTrue(bus.paired)

    def test_b4_accepted_but_still_unpaired_is_never_success_or_retried(self):
        bus = _PairBus(effective=False)
        with self.assertRaisesRegex(ValueError, "could not be verified"):
            self.pair(bus)
        self.assertEqual(bus.calls, ["Pair"], "readback failure must not re-pair")


class OrcaPreferenceReadbackTests(unittest.TestCase):
    """I3 RB: the Orca-on-login preference is read back from the private store."""

    def test_i3_saved_orca_flag_reads_back_from_disk_with_private_modes(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}):
            original = preferences.load()
            self.assertFalse(original["screen_reader_enabled"])
            saved = preferences.save(
                {**original, "accessibility_enabled": True,
                 "screen_reader_enabled": True}, expected=original)
            self.assertTrue(saved["screen_reader_enabled"])
            fresh = preferences.load()           # independent re-read from disk
            self.assertTrue(fresh["screen_reader_enabled"])
            self.assertTrue(fresh["accessibility_enabled"])
            stored = json.loads((Path(tmp) / "ricebowl" / "ricespice.json").read_text())
            self.assertIs(stored["screen_reader_enabled"], True)
            self.assertEqual(os.stat(Path(tmp) / "ricebowl" / "ricespice.json").st_mode & 0o777,
                             0o600)
            # A second save from the stale snapshot is refused, not merged.
            with self.assertRaisesRegex(preferences.PreferenceError, "changed elsewhere"):
                preferences.save({**original, "screen_reader_enabled": False},
                                 expected=original)
            self.assertTrue(preferences.load()["screen_reader_enabled"])


if __name__ == "__main__":
    unittest.main()
