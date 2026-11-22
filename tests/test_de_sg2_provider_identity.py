"""SG2 provider-object continuity: never certify a different NM or pactl object.

All mutations are mocked. No network, audio, time or host services are contacted.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from macrice.de import audio_devices as audio
from macrice.de import network_enrollment as enrollment
from macrice.de import settings_backend as backend


UUID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
OLD = "alsa_output.old"
NEW = "alsa_output.new"


class AudioDefaultIdentityTests(unittest.TestCase):
    def _attempt(self, *, kind="sink", after_index=2, write_error=None):
        state = {"changed": False, "writes": 0}
        collection = "sinks" if kind == "sink" else "sources"

        def provider(*args):
            if args == ("--format=json", "list", collection):
                return json.dumps([
                    {"index": 1, "name": OLD},
                    {"index": after_index if state["changed"] else 2, "name": NEW},
                ])
            if args == ("get-default-" + kind,):
                return NEW if state["changed"] else OLD
            if args == ("set-default-" + kind, NEW):
                state["changed"] = True
                state["writes"] += 1
                if write_error is not None:
                    raise write_error
                return ""
            raise AssertionError("Unexpected pactl call: " + repr(args))

        with mock.patch.object(audio, "_run", side_effect=provider):
            try:
                result = audio.set_default(kind, NEW, expected_current=OLD)
            except audio.AudioDeviceError as exc:
                return state, exc
            return state, result

    def test_same_device_index_readback_succeeds_for_both_kinds(self):
        for kind in ("sink", "source"):
            with self.subTest(kind=kind):
                state, result = self._attempt(kind=kind)
                self.assertEqual(state["writes"], 1)
                self.assertEqual(result["current"], NEW)
                self.assertTrue(result["changed"])

    def test_recycled_name_with_different_object_index_is_indeterminate(self):
        for kind in ("sink", "source"):
            with self.subTest(kind=kind):
                state, error = self._attempt(kind=kind, after_index=99)
                self.assertEqual(state["writes"], 1)
                self.assertEqual(error.code, "audio_verification_failed")
                self.assertTrue(error.may_have_changed)
                self.assertIn("identity changed", str(error.__cause__))

    def test_timeout_after_mutation_never_repeats_write(self):
        state, error = self._attempt(
            write_error=audio.AudioDeviceError("PipeWire reply lost"))
        self.assertEqual(state["writes"], 1)
        self.assertTrue(error.may_have_changed)


class NetworkProfileIdentityTests(unittest.TestCase):
    def test_same_uuid_same_type_but_new_label_never_certifies_activation(self):
        first = {"uuid": UUID, "kind": "wifi", "name": "Campus",
                 "device": "", "active": False}
        for changed in ("Campus-replaced", "Campus"):
            with self.subTest(name=changed):
                second = {**first, "active": True, "device": "wlan0",
                          "name": changed}
                with (
                    mock.patch.object(backend, "connection_profiles",
                                      side_effect=[[first], [second]]),
                    mock.patch.object(backend, "_nmcli_profile",
                                      return_value="") as write,
                ):
                    if changed != first["name"]:
                        with self.assertRaisesRegex(
                                backend.SettingsError, "identity changed"):
                            backend.set_connection_profile(UUID, True, expected=False)
                    else:
                        self.assertTrue(
                            backend.set_connection_profile(UUID, True, expected=False)["active"])
                    write.assert_called_once_with(
                        "con", "up", "uuid", UUID, mutate=True)

    def test_stale_profile_or_readback_loss_is_not_a_retry_authorization(self):
        first = {"uuid": UUID, "kind": "wifi", "name": "Campus", "active": False}
        with (
            mock.patch.object(backend, "connection_profiles",
                              return_value=[{**first, "active": True}]),
            mock.patch.object(backend, "_nmcli_profile") as write,
        ):
            with self.assertRaisesRegex(backend.SettingsError, "changed"):
                backend.set_connection_profile(UUID, True, expected=False)
            write.assert_not_called()
        with (
            mock.patch.object(backend, "connection_profiles", side_effect=[
                [first], backend.SettingsError("Provider disappeared")]),
            mock.patch.object(backend, "_nmcli_profile", return_value="") as write,
        ):
            with self.assertRaisesRegex(
                    backend.SettingsError, "readback unavailable"):
                backend.set_connection_profile(UUID, True, expected=False)
            write.assert_called_once()


class EnterpriseEnrollmentIdentityTests(unittest.TestCase):
    def _attempt(self, *, change=None, fail=None, active=True):
        profile = {"uuid": UUID, "kind": "wifi", "name": "Campus profile",
                   "active": False}
        fields = {
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
        calls = []

        def provider(*args, **kwargs):
            if args[0] == "-g":
                if fail == "readback" and profile["active"]:
                    raise backend.SettingsError("NetworkManager disconnected")
                return fields[args[1]]
            if args[:2] == ("con", "up"):
                calls.append((args, kwargs))
                profile["active"] = active
                if change is not None:
                    key, value = change
                    if key in profile:
                        profile[key] = value
                    else:
                        fields[key] = value
                if fail == "timeout":
                    raise backend.SettingsError("reply lost")
                return ""
            raise AssertionError("Unexpected nmcli call: " + repr(args))

        with (
            mock.patch.object(backend, "connection_profiles",
                              side_effect=lambda: [dict(profile)]),
            mock.patch.object(enrollment, "_run", side_effect=provider),
        ):
            try:
                value = enrollment.connect_enterprise_wifi(UUID, "private-secret")
            except backend.SettingsError as exc:
                return calls, exc
            return calls, value

    def test_positive_requires_verified_profile_and_policy(self):
        calls, result = self._attempt()
        self.assertTrue(result)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["secret"],
                         "802-1x.password:private-secret\n")
        self.assertNotIn("private-secret", str(calls[0][0]))

    def test_post_write_stale_object_and_security_changes_fail_closed(self):
        for change in (
            ("name", "reused-profile"),
            ("kind", "802-11-wireless"),
            ("802-11-wireless.ssid", "EvilTwin"),
            ("802-1x.identity", "another-student"),
            ("802-1x.domain-suffix-match", "radius.other.example"),
            ("802-1x.password-flags", "0"),
        ):
            with self.subTest(change=change):
                calls, error = self._attempt(change=change)
                self.assertEqual(len(calls), 1)
                self.assertIsInstance(error, backend.SettingsError)
                self.assertIn("refresh" if change[0] == "802-1x.password-flags"
                              else "changed", str(error))

    def test_timeout_after_write_is_unknown_and_single_shot(self):
        calls, error = self._attempt(fail="timeout")
        self.assertEqual(len(calls), 1)
        self.assertIn("outcome unknown", str(error))
        self.assertNotIn("private-secret", str(error))

    def test_readback_provider_disconnect_is_indeterminate(self):
        calls, error = self._attempt(fail="readback")
        self.assertEqual(len(calls), 1)
        self.assertIn("readback unavailable", str(error))

    def test_unconfirmed_activation_is_not_success(self):
        calls, error = self._attempt(active=False)
        self.assertEqual(len(calls), 1)
        self.assertIn("changed", str(error))

    def test_missing_profile_label_fails_before_secret_dispatch(self):
        malformed = {"uuid": UUID, "kind": "wifi", "active": False}
        with (
            mock.patch.object(backend, "connection_profiles", return_value=[malformed]),
            mock.patch.object(enrollment, "_run") as write,
        ):
            with self.assertRaisesRegex(backend.SettingsError, "profile changed"):
                enrollment.connect_enterprise_wifi(UUID, "private-secret")
            write.assert_not_called()

    def test_invalid_nmcli_utf8_is_bounded_and_not_exposed(self):
        error = UnicodeDecodeError("utf-8", b"\\xff", 0, 1, "invalid")
        with (
            mock.patch.object(enrollment.shutil, "which", return_value="/usr/bin/nmcli"),
            mock.patch.object(enrollment.subprocess, "run", side_effect=error) as run,
        ):
            with self.assertRaisesRegex(backend.SettingsError, "invalid text"):
                enrollment._run("con", "show", UUID)
            run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
