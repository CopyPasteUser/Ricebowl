"""SG3: private native RicePop selections and uncertain Mako writes.

No notification daemon or D-Bus session is started. All provider calls are
synthetic and action attempts must occur at most once.
"""
from __future__ import annotations

import json
import subprocess
import unittest
from unittest import mock

from macrice.de import notifications


RECORD = {
    "id": 12, "summary": "Ready", "body": "Completed",
    "app_name": "Transfer", "urgency": "normal",
    "actions": [{"key": "open", "label": "Open"}],
}


class RicePopUncertainWriteTests(unittest.TestCase):
    def test_native_selection_rejects_duplicate_keys_even_when_nested(self):
        original = json.dumps(RECORD)
        replacements = (
            ('"id": 12', '"id": 12, "id": 99'),
            ('"summary": "Ready"', '"summary": "Ready", "summary": "Forged"'),
            ('"key": "open"', '"key": "open", "key": "delete"'),
            ('"label": "Open"', '"label": "Open", "label": "Delete"'),
        )
        for marker, replacement in replacements:
            with self.subTest(marker=marker):
                self.assertIn(marker, original)
                with self.assertRaises(notifications.NotificationBridgeError) as caught:
                    notifications.decode_gui_snapshot(
                        original.replace(marker, replacement).encode("utf-8"))
                self.assertEqual(caught.exception.code, "invalid_notification_snapshot")
        self.assertEqual(notifications.decode_gui_snapshot(
            original.encode("utf-8")), RECORD)

    def test_timed_out_or_rejected_dismissal_is_not_silently_repeated(self):
        for failure in (
            subprocess.TimeoutExpired(["makoctl", "dismiss"], 3),
            OSError("lost response"),
            subprocess.CompletedProcess(["makoctl", "dismiss"], 1, b"", b""),
        ):
            with self.subTest(failure=type(failure).__name__):
                if isinstance(failure, subprocess.CompletedProcess):
                    execute = {"return_value": failure}
                else:
                    execute = {"side_effect": failure}
                with (
                    mock.patch.object(notifications, "_mutation_host",
                                      return_value=("makoctl", 91)) as owner,
                    mock.patch.object(notifications, "_read_mako",
                                      return_value=([RECORD], False)) as read,
                    mock.patch.object(notifications.subprocess, "run",
                                      **execute) as run,
                ):
                    with self.assertRaises(notifications.NotificationBridgeError) as caught:
                        notifications.dismiss(12, expected=RECORD,
                                              expected_owner_pid=91)
                    self.assertEqual(caught.exception.code, "notification_outcome_unknown")
                    self.assertIn("refresh", str(caught.exception).lower())
                    self.assertTrue(notifications.invalid(
                        caught.exception, attempted_dismiss=True)["outcome_unknown"])
                    self.assertEqual(owner.call_count, 2)
                    read.assert_called_once_with("ListNotifications", include_actions=True)
                    run.assert_called_once_with(
                        ["makoctl", "dismiss", "-n", "12"],
                        capture_output=True, timeout=3, check=False)

    def test_timed_out_or_rejected_action_is_not_silently_replayed(self):
        for failure in (
            subprocess.TimeoutExpired(["makoctl", "invoke"], 3),
            OSError("lost response"),
            subprocess.CompletedProcess(["makoctl", "invoke"], 1, b"", b""),
        ):
            with self.subTest(failure=type(failure).__name__):
                if isinstance(failure, subprocess.CompletedProcess):
                    execute = {"return_value": failure}
                else:
                    execute = {"side_effect": failure}
                with (
                    mock.patch.object(notifications, "_mutation_host",
                                      return_value=("makoctl", 91)) as owner,
                    mock.patch.object(notifications, "_read_mako",
                                      return_value=([RECORD], False)) as read,
                    mock.patch.object(notifications.subprocess, "run",
                                      **execute) as run,
                ):
                    with self.assertRaises(notifications.NotificationBridgeError) as caught:
                        notifications.invoke(12, "open", expected=RECORD,
                                             expected_owner_pid=91)
                    self.assertEqual(caught.exception.code, "notification_outcome_unknown")
                    self.assertIn("refresh", str(caught.exception).lower())
                    self.assertTrue(notifications.invalid(
                        caught.exception, attempted_invoke=True)["outcome_unknown"])
                    self.assertEqual(owner.call_count, 2)
                    read.assert_called_once_with("ListNotifications", include_actions=True)
                    run.assert_called_once_with(
                        ["makoctl", "invoke", "-n", "12", "--", "open"],
                        capture_output=True, timeout=3, check=False)

    def test_invalid_or_stale_selection_does_not_contact_action_provider(self):
        with (
            mock.patch.object(notifications, "_mutation_host",
                              return_value=("makoctl", 91)),
            mock.patch.object(notifications, "_read_mako",
                              return_value=([RECORD], False)),
            mock.patch.object(notifications.subprocess, "run") as run,
        ):
            old = {**RECORD, "actions": [{"key": "open", "label": "Delete"}]}
            with self.assertRaises(notifications.NotificationBridgeError) as caught:
                notifications.invoke(12, "open", expected=old,
                                     expected_owner_pid=91)
            self.assertEqual(caught.exception.code, "stale_notification_snapshot")
            self.assertFalse(notifications.invalid(
                caught.exception, attempted_invoke=True)["outcome_unknown"])
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
