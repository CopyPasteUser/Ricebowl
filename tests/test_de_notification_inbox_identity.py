"""SG3 read-only inbox must fail closed on ambiguous live Mako IDs.

Mako remains the only notification host. This does not start a daemon or
perform writes; both direct and owner-verified readers use the same guard.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from macrice.de import notifications


def record(identifier: int, summary: str) -> dict:
    return {"id": identifier, "summary": summary, "body": "",
            "app_name": "SG3 private fixture", "urgency": "normal",
            "actions": [{"key": "open", "label": "Open"}]}


class InboxIdentityTests(unittest.TestCase):
    def test_duplicate_active_id_refuses_disclosure_before_history_fetch(self):
        seen = []

        def read(action, *, include_actions=False):
            seen.append((action, include_actions))
            return [record(17, "A"), record(17, "B")], False

        with mock.patch.object(notifications, "_read_mako", side_effect=read):
            with self.assertRaises(notifications.NotificationBridgeError) as captured:
                notifications.inspect()

        self.assertEqual(captured.exception.code, "ambiguous_notification_id")
        self.assertEqual(seen, [("ListNotifications", True)])

    def test_identical_duplicate_rows_remain_ambiguous(self):
        old = record(19, "same text and action")
        with mock.patch.object(notifications, "_read_mako",
                               return_value=([old, dict(old)], False)):
            with self.assertRaises(notifications.NotificationBridgeError) as captured:
                notifications.inspect()
        self.assertEqual(captured.exception.code, "ambiguous_notification_id")

    def test_owned_inbox_never_returns_duplicate_id_private_rows(self):
        old = record(21, "owner verified")
        with mock.patch.object(notifications, "_mutation_host",
                               return_value=("makoctl", 1234)), \
             mock.patch.object(notifications, "_read_mako",
                               return_value=([old, dict(old)], False)):
            with self.assertRaises(notifications.NotificationBridgeError) as captured:
                notifications.inspect_owned()
        self.assertEqual(captured.exception.code, "ambiguous_notification_id")

    def test_recycled_id_in_history_is_not_an_active_id_collision(self):
        active = record(31, "current")
        history = [record(31, "past event"), record(31, "earlier event")]
        with mock.patch.object(notifications, "_read_mako",
                               side_effect=[([active], False), (history, False)]) as reader:
            snapshot = notifications.inspect()
        self.assertEqual(snapshot["active"], [active])
        self.assertEqual(snapshot["history"], history)
        self.assertEqual(reader.call_count, 2)

    def test_distinct_live_ids_and_truncation_contract_remain_intact(self):
        current = [record(1, "one"), record(2, "two")]
        with mock.patch.object(notifications, "_read_mako",
                               side_effect=[(current, True), ([], False)]):
            snapshot = notifications.inspect()
        self.assertEqual(snapshot["active"], current)
        self.assertTrue(snapshot["truncated"])
        self.assertFalse(snapshot["mutates_active_desktop"])

    def test_active_wire_ids_remain_unique_past_the_display_limit(self):
        rows = [{"id": {"type": "u", "data": identifier}}
                for identifier in range(1, 66)]

        def response():
            return json.dumps({"type": "aa{sv}", "data": [rows]}).encode()

        shown, truncated = notifications._busctl_records(response(), include_actions=True)
        self.assertEqual([row["id"] for row in shown], list(range(1, 65)))
        self.assertTrue(truncated)

        rows[-1]["id"]["data"] = 1
        with self.assertRaises(notifications.NotificationBridgeError) as captured:
            notifications._busctl_records(response(), include_actions=True)
        self.assertEqual(captured.exception.code, "ambiguous_notification_id")


if __name__ == "__main__":
    unittest.main()
