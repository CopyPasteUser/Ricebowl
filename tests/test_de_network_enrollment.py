"""Enterprise Wi-Fi and VPN enrollment must keep credentials out of argv."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macrice.de import network_enrollment as enrollment
from macrice.de import settings_backend as backend


UUID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


class NetworkEnrollmentTests(unittest.TestCase):
    def test_enterprise_eap_requires_server_identity_and_never_saves_password(self):
        added = {"uuid": UUID, "kind": "802-11-wireless", "active": False}
        with mock.patch.object(enrollment.uuidlib, "uuid4", return_value=UUID), \
                mock.patch.object(backend, "connection_profiles", side_effect=[[], [added]]), \
                mock.patch.object(enrollment, "_run", return_value="") as run:
            result = enrollment.create_enterprise_wifi(
                ssid="Campus", identity="user@school.edu", domain="radius.school.edu",
                eap="peap", inner="mschapv2")
        self.assertEqual(result, UUID)
        arguments = run.call_args.args
        self.assertIn("802-1x.domain-suffix-match", arguments)
        self.assertIn("radius.school.edu", arguments)
        self.assertEqual(arguments[arguments.index("802-1x.password-flags") + 1], "2")
        self.assertEqual(arguments[arguments.index("802-1x.system-ca-certs") + 1], "yes")
        self.assertNotIn("802-1x.password", arguments)
        self.assertNotIn("password123", str(arguments))
        self.assertIn("connection.autoconnect", arguments)
        self.assertEqual(arguments[arguments.index("connection.autoconnect") + 1], "no")

    def test_enterprise_eap_fails_closed_on_missing_domain_or_unsafe_mode(self):
        normal = dict(ssid="Campus", identity="someone", domain="radius.school.edu",
                      eap="peap", inner="mschapv2")
        bad = (
            {"domain": ""}, {"domain": "*.school.edu"},
            {"domain": "radius.school.edu;evil"}, {"domain": "school"},
            {"eap": "tls", "inner": "mschapv2"},
            {"eap": "peap", "inner": "pap"},
            {"ssid": "bad\nname"}, {"identity": "x\n"},
            {"ca_certificate": "/missing/cert.pem"},
        )
        with mock.patch.object(enrollment, "_run") as run:
            for changes in bad:
                with self.subTest(changes=changes), self.assertRaises(backend.SettingsError):
                    enrollment.create_enterprise_wifi(**{**normal, **changes})
        run.assert_not_called()

    def test_enterprise_connection_passes_password_only_by_stdin(self):
        before = {"uuid": UUID, "kind": "wifi", "active": False}
        after = {**before, "active": True}

        def runner(*args, **kwargs):
            if args[0] == "-g":
                return {
                    "802-11-wireless-security.key-mgmt": "wpa-eap",
                    "802-1x.eap": "peap",
                    "802-1x.domain-suffix-match": "radius.school.edu",
                    "802-1x.system-ca-certs": "yes",
                    "802-1x.ca-cert": "",
                }[args[1]]
            return ""

        with mock.patch.object(backend, "connection_profiles", side_effect=[[before], [after]]), \
                mock.patch.object(enrollment, "_run", side_effect=runner) as run:
            self.assertTrue(enrollment.connect_enterprise_wifi(UUID, "private-password"))
        self.assertEqual(run.call_args.kwargs["secret"],
                         "802-1x.password:private-password\n")
        self.assertIn("/dev/stdin", run.call_args.args)
        self.assertNotIn("private-password", str(run.call_args.args))

    def test_enterprise_connection_refuses_non_eap_and_untrusted_profiles(self):
        existing = {"uuid": UUID, "kind": "802-11-wireless", "active": False}
        with mock.patch.object(backend, "connection_profiles", return_value=[existing]), \
                mock.patch.object(enrollment, "_run", return_value="wpa-psk") as run:
            with self.assertRaisesRegex(backend.SettingsError, "not an enterprise"):
                enrollment.connect_enterprise_wifi(UUID, "secret")
            self.assertEqual(run.call_count, 1)
        for secret in ("", "line\nbreak", "x" * 513, None):
            with self.subTest(secret=secret), self.assertRaises(backend.SettingsError):
                enrollment.connect_enterprise_wifi(UUID, secret)

    def test_existing_eap_profile_without_cert_verification_cannot_receive_password(self):
        fields = {"802-11-wireless-security.key-mgmt": "wpa-eap",
                  "802-1x.eap": "peap",
                  "802-1x.domain-suffix-match": "radius.school.edu",
                  "802-1x.system-ca-certs": "no", "802-1x.ca-cert": ""}
        with mock.patch.object(enrollment, "_run", side_effect=lambda *args, **kwargs:
                               fields[args[1]]) as run:
            with self.assertRaisesRegex(backend.SettingsError, "verify a CA"):
                enrollment.enterprise_password_ready(UUID)
            self.assertFalse(any("passwd-file" in str(call.args) for call in run.call_args_list))

    def test_subprocess_secret_is_stdin_only_and_errors_hide_output(self):
        with mock.patch.object(enrollment.shutil, "which", return_value="/usr/bin/nmcli"), \
                mock.patch.object(enrollment.subprocess, "run", return_value=mock.Mock(
                    returncode=0, stdout="activated", stderr="")) as run:
            self.assertEqual(enrollment._run("con", "up", "uuid", UUID,
                                             secret="802-1x.password:secret\n"), "activated")
            self.assertNotIn("secret", str(run.call_args.args))
            self.assertEqual(run.call_args.kwargs["input"], "802-1x.password:secret\n")
        with mock.patch.object(enrollment.shutil, "which", return_value="/usr/bin/nmcli"), \
                mock.patch.object(enrollment.subprocess, "run", return_value=mock.Mock(
                    returncode=1, stdout="secret leaked", stderr="secret leaked")):
            with self.assertRaises(backend.SettingsError) as caught:
                enrollment._run("con", "up", "uuid", UUID, secret="sensitive")
            self.assertNotIn("secret leaked", str(caught.exception))

    def test_vpn_import_verifies_single_new_profile_and_disables_autoconnect(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "home.ovpn")
            source.write_text("client\nremote vpn.example.com 1194\n", encoding="utf-8")
            imported = {"uuid": UUID, "kind": "vpn", "active": False}
            with mock.patch.object(backend, "connection_profiles",
                                   side_effect=[[], [imported]]), \
                    mock.patch.object(enrollment, "_run", side_effect=["", "", "no"]) as run:
                self.assertEqual(enrollment.import_vpn_profile(str(source)), UUID)
            self.assertIn("openvpn", run.call_args_list[0].args)
            self.assertEqual(run.call_args_list[1].args,
                             ("con", "modify", "uuid", UUID, "connection.autoconnect", "no"))
            self.assertEqual(run.call_args_list[2].args,
                             ("-g", "connection.autoconnect", "con", "show", "uuid", UUID))

    def test_vpn_import_reports_if_networkmanager_keeps_autoconnect(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "home.conf")
            source.write_text("[Interface]\nPrivateKey=test\n", encoding="utf-8")
            imported = {"uuid": UUID, "kind": "wireguard", "active": False}
            with mock.patch.object(backend, "connection_profiles",
                                   side_effect=[[], [imported]]), \
                    mock.patch.object(enrollment, "_run", side_effect=["", "", "yes"]):
                with self.assertRaisesRegex(backend.SettingsError, "autoconnect could not"):
                    enrollment.import_vpn_profile(str(source))

    def test_vpn_import_rejects_invalid_files_and_ambiguous_additions(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp, "home.zip")
            bad.write_bytes(b"archive")
            with mock.patch.object(enrollment, "_run") as run:
                for path in (str(bad), "relative.ovpn", "/missing/vpn.ovpn", ""):
                    with self.subTest(path=path), self.assertRaises(backend.SettingsError):
                        enrollment.import_vpn_profile(path)
                run.assert_not_called()
            good = Path(tmp, "home.conf")
            good.write_text("[Interface]\n", encoding="utf-8")
            with mock.patch.object(backend, "connection_profiles", side_effect=[[], []]), \
                    mock.patch.object(enrollment, "_run", return_value=""):
                with self.assertRaisesRegex(backend.SettingsError, "could not be verified"):
                    enrollment.import_vpn_profile(str(good))


if __name__ == "__main__":
    unittest.main()
