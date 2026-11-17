"""Private native RicePop actions cannot escape the owner/snapshot contract."""

import io
import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

from macrice.cli import main
from macrice.de import notifications


ROW = {
    "id": 12, "summary": "Private mail", "body": "Never in argv or logs",
    "app_name": "Mail", "urgency": "normal",
    "actions": [{"key": "reply", "label": "Reply"}],
}


def stdin_for(row):
    return SimpleNamespace(buffer=io.BytesIO(json.dumps(row).encode()))


class NativeRicePopActionGuardTests(unittest.TestCase):
    def test_private_snapshot_decoder_requires_full_bounded_exact_row(self):
        self.assertEqual(notifications.decode_gui_snapshot(
            json.dumps(ROW).encode()), ROW)
        for invalid in (
            b"", b"{", b"[]" , b'"hi"', b" " * 8193,
            json.dumps({**ROW, "id": True}).encode(),
            json.dumps({**ROW, "extra": "not permitted"}).encode(),
            json.dumps({**ROW, "actions": [{"key": "reply", "label": "Reply"},
                                          {"key": "reply", "label": "Other"}]}).encode(),
            json.dumps({**ROW, "body": "x" * 2049}).encode(),
            json.dumps({**ROW, "actions": {"reply": "Reply"}}).encode(),
            json.dumps({**ROW, "app_name": None}).encode(),
        ):
            with self.subTest(raw=invalid[:40]):
                with self.assertRaises(notifications.NotificationBridgeError) as error:
                    notifications.decode_gui_snapshot(invalid)
                self.assertEqual(error.exception.code, "invalid_notification_snapshot")

    def test_only_owning_mako_may_supply_native_private_inbox(self):
        with mock.patch.object(notifications, "inspect_owned", return_value={
                "ok": True, "owner_pid": 41, "active": [ROW],
                "history": [], "truncated": False}) as owned,              mock.patch.object(notifications, "inspect") as unverified,              mock.patch("builtins.print") as printed:
            self.assertEqual(main(["de", "notifications-owned", "--json"]), 0)
        owned.assert_called_once()
        unverified.assert_not_called()
        self.assertEqual(json.loads(printed.call_args.args[0])["owner_pid"], 41)

    def _perform(self, operation, *, owner=41, fresh=None, row=ROW):
        argv = ["de", "notification-" + operation,
                "--notification-id", "12", "--expected-owner-pid", str(owner),
                "--snapshot-stdin", "--json"]
        if operation == "invoke":
            argv.extend(("--action-key", "reply"))
        with mock.patch("sys.stdin", new=stdin_for(row)),              mock.patch.object(notifications, "_mutation_host",
                               return_value=("makoctl", 42)),              mock.patch.object(notifications, "_read_mako",
                               return_value=([ROW if fresh is None else fresh], False)) as read,              mock.patch.object(notifications.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0, b"", b"")) as command,              mock.patch("builtins.print") as output:
            result = main(argv)
        return result, read, command, output

    def test_stale_owner_blocks_dismiss_and_invoke_before_private_inventory(self):
        for operation in ("dismiss", "invoke"):
            with self.subTest(operation=operation):
                result, read, command, output = self._perform(operation)
                self.assertEqual(result, 2)
                self.assertEqual(json.loads(output.call_args.args[0])["error"]["code"],
                                 "notification_host_changed")
                read.assert_not_called()
                command.assert_not_called()

    def test_same_owner_changed_text_or_action_label_is_rejected(self):
        for operation, changed in (
                ("dismiss", {**ROW, "body": "Other private notice"}),
                ("dismiss", {**ROW, "actions": [{"key": "reply", "label": "Delete"}]}),
                ("invoke", {**ROW, "actions": [{"key": "reply", "label": "Delete"}]})):
            with self.subTest(operation=operation):
                result, read, command, output = self._perform(
                    operation, owner=42, fresh=changed)
                self.assertEqual(result, 2)
                self.assertEqual(json.loads(output.call_args.args[0])["error"]["code"],
                                 "stale_notification_snapshot")
                read.assert_called_once()
                command.assert_not_called()
                self.assertNotIn(ROW["body"], str(output.call_args))

    def test_current_owner_and_unchanged_snapshot_can_mutate_exact_id(self):
        for operation in ("dismiss", "invoke"):
            with self.subTest(operation=operation):
                result, read, command, output = self._perform(operation, owner=42)
                self.assertEqual(result, 0)
                read.assert_called_once()
                command.assert_called_once()
                args = command.call_args.args[0]
                self.assertNotIn(ROW["summary"], " ".join(args))
                self.assertNotIn(ROW["body"], " ".join(args))
                self.assertEqual(json.loads(output.call_args.args[0])["notification_id"], 12)

    def test_native_owner_guard_flags_are_not_optional_or_other_command_escape(self):
        for argv in (
                ["de", "notification-dismiss", "--notification-id", "12",
                 "--expected-owner-pid", "7", "--json"],
                ["de", "notification-dismiss", "--notification-id", "12",
                 "--snapshot-stdin", "--json"],
                ["de", "notifications-owned", "--snapshot-stdin",
                 "--expected-owner-pid", "7", "--json"],
                ["de", "notification-dnd", "--expected-owner-pid", "7",
                 "--snapshot-stdin", "--json"],
        ):
            with self.subTest(argv=argv), mock.patch("builtins.print"):
                self.assertEqual(main(argv), 1)


if __name__ == "__main__":
    unittest.main()
