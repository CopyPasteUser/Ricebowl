"""Private SG2 subprocess integration through the real NetworkManager adapters.

The fixture executable is created inside TemporaryDirectory, and is the ONLY
nmcli binary either adapter can invoke. Nothing contacts the host system bus.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macrice.de import network_enrollment, settings_backend


UUID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
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

# This script runs as a separate process, like genuine nmcli. It never invokes
# nmcli, DBus, NetworkManager, or a real network device.
PRIVATE_NMCLI = r'''
import json
import os
import sys
from pathlib import Path

root = Path(os.environ["RICEBOWL_SG2_TEST_ROOT"])
state_path = root / "state.json"
state = json.loads(state_path.read_text(encoding="utf-8"))
args = sys.argv[1:]
if len(args) >= 2 and args[0] == "--wait":
    args = args[2:]
uuid = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
if args == ["-t", "-e", "yes", "-f", "UUID,TYPE,NAME,DEVICE", "con", "show"]:
    print(f"{uuid}:wifi:Campus profile:--")
elif args == ["-t", "-e", "yes", "-f", "UUID", "con", "show", "--active"]:
    if state["active"]:
        print(uuid)
elif len(args) == 6 and args[:1] == ["-g"] and args[2:] == [
        "con", "show", "uuid", uuid]:
    print(state["fields"][args[1]])
elif args == ["con", "up", "uuid", uuid, "passwd-file", "/dev/stdin"]:
    # Read the credential through the real child process's stdin, never argv,
    # stderr, or persistent fixture state. Only a nonsecret mutation receipt
    # is stored for the parent process to assert.
    secret = sys.stdin.read()
    if secret != "802-1x.password:private-secret\n":
        sys.exit(9)
    with (root / "mutations.txt").open("a", encoding="utf-8") as receipt:
        receipt.write("enterprise-up\n")
    if state["deny"]:
        sys.exit(4)
    state["active"] = True
    state_path.write_text(json.dumps(state), encoding="utf-8")
else:
    sys.exit(8)
'''


class EnterpriseSubprocessBoundaryTests(unittest.TestCase):
    def test_real_adapter_to_private_nmcli_success_and_denial(self):
        for deny in (False, True):
            with self.subTest(deny=deny), tempfile.TemporaryDirectory(
                    prefix="ricebowl-sg2-nmcli-") as tmp:
                root = Path(tmp)
                binary = root / "nmcli"
                binary.write_text("#!" + sys.executable + "\n" + PRIVATE_NMCLI,
                                  encoding="utf-8")
                binary.chmod(0o700)
                (root / "state.json").write_text(json.dumps({
                    "active": False, "deny": deny, "fields": FIELDS,
                }), encoding="utf-8")
                # Both modules import the same shutil singleton. Patch only
                # which(), not subprocess.run() or any production adapter.
                with (mock.patch.dict(os.environ, {
                          "RICEBOWL_SG2_TEST_ROOT": str(root),
                      }), mock.patch.object(shutil, "which",
                                            return_value=str(binary)) as which):
                    if deny:
                        with self.assertRaisesRegex(
                                settings_backend.SettingsError,
                                "outcome unknown"):
                            network_enrollment.connect_enterprise_wifi(
                                UUID, "private-secret")
                    else:
                        self.assertTrue(network_enrollment.connect_enterprise_wifi(
                            UUID, "private-secret"))
                    self.assertGreaterEqual(which.call_count, 1)
                state = json.loads((root / "state.json").read_text(encoding="utf-8"))
                self.assertEqual(state["active"], not deny)
                self.assertEqual(
                    (root / "mutations.txt").read_text(encoding="utf-8"),
                    "enterprise-up\n",
                )
                self.assertNotIn("private-secret", json.dumps(state))
                self.assertNotIn("private-secret", (root / "mutations.txt").read_text())


if __name__ == "__main__":
    unittest.main()
