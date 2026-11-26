"""SG2 polkit/NetworkManager authorization denial through private subprocesses.

Fake ``timedatectl`` and ``nmcli`` executables live in a TemporaryDirectory and
are the ONLY binaries the real adapters can invoke. Nothing contacts a system
bus. Each case asserts: denial is typed (SettingsDenied) with one fixed
message, no raw stderr leaks, no readback/replay follows a refusal, and every
other failure or unknown output stays a generic fail-closed SettingsError.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from macrice import authorization, hardware_status
from macrice.de import network_enrollment, settings, settings_backend as backend

DENY_STDERR = "Error: Not authorized to control networking. SECRET-STDERR-TOKEN"
UUID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
NEW_UUID = "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"
ZONES = ["Europe/Paris", "Europe/Rome", "UTC"]

PRIVATE_TIMEDATECTL = r'''
import json, os, sys
from pathlib import Path
root = Path(os.environ["RICEBOWL_SG2_TEST_ROOT"])
path = root / "state.json"
state = json.loads(path.read_text(encoding="utf-8"))
args = sys.argv[1:]
with (root / "calls.txt").open("a", encoding="utf-8") as log:
    log.write(" ".join(args) + "\n")
def refuse(text="Failed: Interactive authentication required. SECRET-STDERR-TOKEN"):
    sys.stderr.write(text + "\n"); sys.exit(1)
if args[:1] == ["show"]:
    if state.get("deny_show") and state["mutated"]:
        refuse("Failed to query: Access denied SECRET-STDERR-TOKEN")
    if args == ["show", "-p", "Timezone", "--value"]:
        print(state["tz"])
    elif args == ["show", "-p", "CanNTP", "-p", "NTP"]:
        print("CanNTP=yes"); print("NTP=" + ("yes" if state["ntp"] else "no"))
    else:
        sys.exit(8)
elif args == ["list-timezones", "--no-pager"]:
    print("\n".join(state["zones"]))
elif args[:1] in (["set-ntp"], ["set-timezone"], ["set-time"]):
    mode = state["mode"]
    if mode == "deny":
        refuse()
    if mode == "fail":
        sys.stderr.write("Failed to connect to bus: no such file SECRET-STDERR-TOKEN\n")
        sys.exit(1)
    if mode == "silent_fail":
        sys.exit(1)
    if mode == "lie":   # exit 0 and a refusal-looking stderr but no change
        sys.stderr.write("Access denied\n")
    else:               # ok
        if args[0] == "set-ntp":
            state["ntp"] = args[1] == "true"
        elif args[0] == "set-timezone":
            state["tz"] = args[1]
        state["mutated"] = True
        path.write_text(json.dumps(state), encoding="utf-8")
else:
    sys.exit(8)
'''

PRIVATE_NMCLI = r'''
import json, os, sys
from pathlib import Path
root = Path(os.environ["RICEBOWL_SG2_TEST_ROOT"])
path = root / "state.json"
state = json.loads(path.read_text(encoding="utf-8"))
args = sys.argv[1:]
asked = "--ask" in args
while args and args[0] in ("--ask", "--wait"):
    args = args[2:] if args[0] == "--wait" else args[1:]
with (root / "calls.txt").open("a", encoding="utf-8") as log:
    log.write(" ".join(args) + "\n")
def save():
    path.write_text(json.dumps(state), encoding="utf-8")
def mutate(apply):
    mode = state["mode"]
    if mode == "deny":
        sys.stderr.write(state["deny_text"] + "\n"); sys.exit(1)
    if mode == "fail":
        sys.stderr.write("Error: NetworkManager is not running. SECRET-STDERR-TOKEN\n")
        sys.exit(8)
    if mode == "silent_fail":
        sys.exit(4)
    apply()      # ok
    save()
profiles = state["profiles"]
if args == ["radio", "wifi"]:
    print(state["radio"])
elif args == ["radio", "wifi", "on"] or args == ["radio", "wifi", "off"]:
    def apply(): state["radio"] = "enabled" if args[2] == "on" else "disabled"
    mutate(apply)
elif args == ["-t", "-e", "yes", "-f", "UUID,TYPE,NAME,DEVICE", "con", "show"]:
    for p in profiles:
        print(f"{p['uuid']}:{p['type']}:{p['name']}:--")
elif args == ["-t", "-e", "yes", "-f", "UUID", "con", "show", "--active"]:
    for p in profiles:
        if p["active"]:
            print(p["uuid"])
elif args[:2] == ["-g", "connection.autoconnect"]:
    print("no")
elif args[:2] == ["con", "up"] and args[2] == "uuid":
    def apply():
        for p in profiles:
            p["active"] = p["uuid"] == args[3]
    mutate(apply)
elif args[:3] == ["con", "import", "type"]:
    def apply():
        profiles.append({"uuid": state["import_uuid"], "type": "vpn",
                         "name": "Office VPN", "active": False})
    mutate(apply)
elif args[:2] == ["con", "modify"]:
    pass
elif args == ["-t", "-e", "yes", "-f", "SSID,SECURITY", "device", "wifi", "list",
              "--rescan", "no"]:
    print("Cafe:WPA2")
elif args == ["-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list",
              "--rescan", "no"]:
    print(("*" if state["joined"] else " ") + ":Cafe:70:WPA2")
elif args == ["device", "wifi", "connect", "Cafe"]:
    if asked:
        sys.stdin.read()
    def apply(): state["joined"] = True
    mutate(apply)
else:
    sys.exit(9)
'''


class _Fixture:
    def __init__(self, test, name, script, state):
        self.test = test
        self.tmp = tempfile.TemporaryDirectory(prefix="ricebowl-sg2-deny-")
        test.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.name = name
        binary = self.root / self.name
        binary.write_text("#!" + sys.executable + "\n" + script, encoding="utf-8")
        binary.chmod(0o700)
        (self.root / "state.json").write_text(json.dumps(state), encoding="utf-8")
        patch_env = mock.patch.dict(os.environ, {
            "RICEBOWL_SG2_TEST_ROOT": str(self.root),
            "PATH": str(self.root) + os.pathsep + os.environ.get("PATH", "")})
        patch_which = mock.patch.object(shutil, "which", return_value=str(binary))
        patch_env.start(); patch_which.start()
        test.addCleanup(patch_env.stop); test.addCleanup(patch_which.stop)

    def state(self):
        return json.loads((self.root / "state.json").read_text(encoding="utf-8"))

    def calls(self):
        path = self.root / "calls.txt"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _time_fixture(test, mode, *, ntp=False, deny_show=False):
    return _Fixture(test, "timedatectl", PRIVATE_TIMEDATECTL, {
        "tz": "Europe/Paris", "zones": ZONES, "ntp": ntp, "mode": mode,
        "mutated": False, "deny_show": deny_show})


def _nm_fixture(test, mode, *, radio="enabled", deny_text=DENY_STDERR, profiles=None):
    return _Fixture(test, "nmcli", PRIVATE_NMCLI, {
        "mode": mode, "radio": radio, "deny_text": deny_text, "joined": False,
        "import_uuid": NEW_UUID,
        "profiles": profiles if profiles is not None else [
            {"uuid": UUID, "type": "wifi", "name": "Home", "active": False}]})


class DenialClassifierTests(unittest.TestCase):
    def test_only_recognized_refusal_text_is_a_denial(self):
        for text in ("Failed to set time zone: Access denied",
                     "Failed: Interactive authentication required.",
                     "Error: Not authorized to control networking.",
                     "org.freedesktop.DBus.Error.AccessDenied: rejected",
                     "ACCESS DENIED", b"Failed: Access denied\n"):
            with self.subTest(text=text):
                self.assertTrue(authorization.is_authorization_denial(text))
        for text in ("", b"", None, 7, "Failed to connect to bus", "Timeout expired",
                     "Error: NetworkManager is not running.", b"\xff\xfe",
                     "No such file or directory", "Permission denied: /etc/localtime"):
            with self.subTest(text=text):
                self.assertFalse(authorization.is_authorization_denial(text))

    def test_marker_beyond_bounded_prefix_is_ignored(self):
        self.assertFalse(authorization.is_authorization_denial("x" * 5000 + "access denied"))


class TimedatedDenialTests(unittest.TestCase):
    def _assert_denied(self, fixture, action):
        with self.assertRaises(backend.SettingsDenied) as caught:
            action()
        self.assertEqual(str(caught.exception), authorization.DENIED_MESSAGE)
        self.assertNotIn("SECRET-STDERR-TOKEN", repr(caught.exception))
        state = fixture.state()
        self.assertFalse(state["mutated"])
        # The refusal is the last call: no readback, no second mutation.
        calls = fixture.calls()
        self.assertEqual(sum(c.startswith("set-") for c in calls), 1)
        self.assertTrue(calls[-1].startswith("set-"), calls)
        return state

    def test_td_deny_ntp_timezone_and_clock_are_typed_and_not_replayed(self):
        cases = (
            lambda: backend.set_ntp(True, expected=False),
            lambda: backend.set_timezone("Europe/Rome", expected="Europe/Paris"),
            lambda: backend.set_system_clock(
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), expected_ntp=False),
        )
        for index, action in enumerate(cases):
            with self.subTest(action=index):
                fixture = _time_fixture(self, "deny")
                state = self._assert_denied(fixture, action)
                self.assertEqual((state["tz"], state["ntp"]), ("Europe/Paris", False))

    def test_td_generic_failures_stay_unknown_outcome_not_denial(self):
        for mode in ("fail", "silent_fail"):
            for index, action in enumerate((
                    lambda: backend.set_ntp(True, expected=False),
                    lambda: backend.set_timezone("Europe/Rome", expected="Europe/Paris"))):
                with self.subTest(mode=mode, action=index):
                    fixture = _time_fixture(self, mode)
                    with self.assertRaises(backend.SettingsError) as caught:
                        action()
                    self.assertNotIsInstance(caught.exception, backend.SettingsDenied)
                    self.assertIn("outcome unknown", str(caught.exception))
                    self.assertNotIn("SECRET-STDERR-TOKEN", repr(caught.exception))
                    self.assertEqual(sum(c.startswith("set-") for c in fixture.calls()), 1)

    def test_td_success_still_verified_by_independent_readback(self):
        fixture = _time_fixture(self, "ok")
        self.assertEqual(backend.set_timezone("Europe/Rome", expected="Europe/Paris"),
                         "Europe/Rome")
        self.assertEqual(backend.set_ntp(True, expected=False)["enabled"], True)
        self.assertEqual(fixture.state()["tz"], "Europe/Rome")

    def test_td_exit_zero_with_refusal_text_is_never_success_or_denial(self):
        fixture = _time_fixture(self, "lie")
        with self.assertRaises(backend.SettingsError) as caught:
            backend.set_ntp(True, expected=False)
        self.assertNotIsInstance(caught.exception, backend.SettingsDenied)
        self.assertIn("verification failed", str(caught.exception))
        self.assertFalse(fixture.state()["ntp"])

    def test_td_denial_during_post_write_readback_is_indeterminate_not_denied(self):
        fixture = _time_fixture(self, "ok", deny_show=True)
        with self.assertRaises(backend.SettingsError) as caught:
            backend.set_timezone("Europe/Rome", expected="Europe/Paris")
        self.assertNotIsInstance(caught.exception, backend.SettingsDenied)
        self.assertIn("may have changed", str(caught.exception))
        self.assertTrue(fixture.state()["mutated"])
        self.assertEqual(sum(c.startswith("set-") for c in fixture.calls()), 1)

    def test_td_unknown_or_empty_stderr_never_classifies_as_denial(self):
        for text in ("", "Failed: something else", "denied"):
            with self.subTest(text=text):
                completed = mock.Mock(returncode=1, stdout=b"", stderr=text.encode())
                with (mock.patch.object(shutil, "which", return_value="/x/timedatectl"),
                      mock.patch.object(backend.subprocess, "run",
                                        return_value=completed)):
                    with self.assertRaises(backend.SettingsError) as caught:
                        backend._timedatectl("set-ntp", "true")
                self.assertNotIsInstance(caught.exception, backend.SettingsDenied)


class NetworkManagerDenialTests(unittest.TestCase):
    def _assert_denied(self, fixture, action, mutation_prefix):
        with self.assertRaises(backend.SettingsDenied) as caught:
            action()
        self.assertEqual(str(caught.exception), authorization.DENIED_MESSAGE)
        self.assertNotIn("SECRET-STDERR-TOKEN", repr(caught.exception))
        self.assertNotIn("Not authorized", str(caught.exception))
        calls = fixture.calls()
        mutations = [c for c in calls if c.startswith(mutation_prefix)]
        self.assertEqual(len(mutations), 1, calls)          # single shot, never replayed
        self.assertTrue(calls[-1].startswith(mutation_prefix), calls)  # no readback claimed

    def test_nm_deny_wifi_radio_toggle(self):
        fixture = _nm_fixture(self, "deny", radio="enabled")
        self._assert_denied(fixture, lambda: backend.set_wifi(False, expected=True),
                            "radio wifi o")
        self.assertEqual(fixture.state()["radio"], "enabled")

    def test_nm_deny_saved_profile_activation(self):
        fixture = _nm_fixture(self, "deny")
        self._assert_denied(
            fixture, lambda: backend.set_connection_profile(UUID, True, expected=False),
            "con up")
        self.assertFalse(fixture.state()["profiles"][0]["active"])

    def test_nm_deny_wifi_join_open_and_secured(self):
        for action in (lambda: backend.connect_visible_wifi("Cafe"),
                       lambda: backend.connect_secure_visible_wifi("Cafe", "hunter2hunter2")):
            with self.subTest(action=action):
                fixture = _nm_fixture(self, "deny")
                self._assert_denied(fixture, action, "device wifi connect")
                self.assertFalse(fixture.state()["joined"])
                self.assertNotIn("hunter2", json.dumps(fixture.state()))

    def test_nm_deny_vpn_import(self):
        with tempfile.TemporaryDirectory(prefix="ricebowl-sg2-vpn-") as tmp:
            config = Path(tmp) / "office.ovpn"
            config.write_text("client\n", encoding="utf-8")
            fixture = _nm_fixture(self, "deny")
            self._assert_denied(fixture, lambda: network_enrollment.import_vpn_profile(
                str(config)), "con import")
            self.assertEqual(len(fixture.state()["profiles"]), 1)
            self.assertFalse(any(c.startswith("con modify") for c in fixture.calls()))

    def test_nm_marker_variants_all_typed_denials(self):
        for text in ("Error: Failed to set Wi-Fi radio: Access denied",
                     "Error: Connection activation failed: Insufficient privileges.",
                     "Error: org.freedesktop.NetworkManager.PermissionDenied: x"):
            with self.subTest(text=text):
                fixture = _nm_fixture(self, "deny", deny_text=text)
                with self.assertRaises(backend.SettingsDenied):
                    backend.set_wifi(False, expected=True)
                self.assertEqual(fixture.state()["radio"], "enabled")

    def test_nm_generic_failures_stay_unknown_outcome_not_denial(self):
        for mode in ("fail", "silent_fail"):
            with self.subTest(mode=mode):
                fixture = _nm_fixture(self, mode)
                for action, expect in (
                        (lambda: backend.set_wifi(False, expected=True), "outcome unknown"),
                        (lambda: backend.set_connection_profile(UUID, True, expected=False),
                         "may have changed"),
                        (lambda: backend.connect_visible_wifi("Cafe"), "Wi-Fi connection failed")):
                    with self.assertRaises(backend.SettingsError) as caught:
                        action()
                    self.assertNotIsInstance(caught.exception, backend.SettingsDenied)
                    self.assertIn(expect, str(caught.exception))
                    self.assertNotIn("SECRET-STDERR-TOKEN", repr(caught.exception))
                self.assertEqual(fixture.state()["radio"], "enabled")

    def test_nm_vpn_import_generic_failure_and_success_controls(self):
        with tempfile.TemporaryDirectory(prefix="ricebowl-sg2-vpn-") as tmp:
            config = Path(tmp) / "office.ovpn"
            config.write_text("client\n", encoding="utf-8")
            _nm_fixture(self, "fail")
            with self.assertRaises(backend.SettingsError) as caught:
                network_enrollment.import_vpn_profile(str(config))
            self.assertNotIsInstance(caught.exception, backend.SettingsDenied)
            self.assertIn("outcome is unknown", str(caught.exception))
            _nm_fixture(self, "ok")
            self.assertEqual(network_enrollment.import_vpn_profile(str(config)), NEW_UUID)

    def test_nm_success_controls_claim_only_after_readback(self):
        fixture = _nm_fixture(self, "ok")
        self.assertFalse(backend.set_wifi(False, expected=True))
        self.assertEqual(fixture.state()["radio"], "disabled")
        self.assertTrue(backend.set_connection_profile(UUID, True, expected=False)["active"])

    def test_nm_join_success_control_requires_connected_readback(self):
        fixture = _nm_fixture(self, "ok")
        self.assertIs(backend.connect_visible_wifi("Cafe"), True)
        self.assertTrue(fixture.state()["joined"])

    def test_nm_denial_text_on_readback_after_write_is_indeterminate(self):
        # A refusal reported by a follow-up read cannot prove the earlier write failed.
        fixture = _nm_fixture(self, "ok")
        with mock.patch.object(backend, "connection_profiles",
                               side_effect=[[{"uuid": UUID, "kind": "wifi", "name": "Home",
                                              "active": False, "device": ""}],
                                            backend.SettingsDenied()]):
            with self.assertRaises(backend.SettingsError) as caught:
                backend.set_connection_profile(UUID, True, expected=False)
        self.assertNotIsInstance(caught.exception, backend.SettingsDenied)
        self.assertIn("may have changed", str(caught.exception))
        self.assertTrue(fixture.state()["profiles"][0]["active"])


class DenialWordingTests(unittest.TestCase):
    def test_timedated_and_networkmanager_share_one_user_visible_denial(self):
        _time_fixture(self, "deny")
        with self.assertRaises(backend.SettingsDenied) as time_denial:
            backend.set_ntp(True, expected=False)
        _nm_fixture(self, "deny")
        with self.assertRaises(backend.SettingsDenied) as nm_denial:
            backend.set_wifi(False, expected=True)
        self.assertEqual(settings.denial_or_error_text(time_denial.exception),
                         settings.denial_or_error_text(nm_denial.exception))
        self.assertEqual(settings.denial_or_error_text(nm_denial.exception),
                         authorization.DENIED_MESSAGE)

    def test_other_errors_keep_existing_prefix(self):
        self.assertEqual(settings.denial_or_error_text(backend.SettingsError("boom")),
                         "Unavailable or denied: boom")
        self.assertEqual(settings.denial_or_error_text(RuntimeError("x")),
                         "Unavailable or denied: x")


if __name__ == "__main__":
    unittest.main()
