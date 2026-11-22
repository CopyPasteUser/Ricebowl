"""SG3 Mako DND changes must distinguish indeterminate writes from safe no-ops.

All Mako ownership, bus and CLI commands are synthetic: no running
notification host, existing XFCE desktop or user notifications are touched.
"""
from __future__ import annotations

import subprocess
import unittest
from unittest import mock

from macrice.de import notifications


class RicePopDndUnknownOutcomeTests(unittest.TestCase):
    def test_timed_out_write_never_retries_or_claims_no_change(self):
        with (
            mock.patch.object(notifications, "_owned_mako",
                              return_value=("makoctl", 991)) as owner,
            mock.patch.object(notifications, "_modes", return_value=[]) as modes,
            mock.patch.object(notifications.subprocess, "run",
                              side_effect=subprocess.TimeoutExpired(
                                  ["makoctl", "mode", "-a"], 3)) as run,
        ):
            with self.assertRaises(notifications.NotificationBridgeError) as captured:
                notifications.set_dnd(True, expected=False)
            self.assertEqual(captured.exception.code, "dnd_outcome_unknown")
            self.assertIn("refresh", str(captured.exception).lower())
            run.assert_called_once_with(
                ["makoctl", "mode", "-a", notifications._DND_MODE],
                capture_output=True, timeout=3, check=False)
            self.assertEqual(owner.call_count, 2)
            modes.assert_called_once_with("makoctl")

    def test_postwrite_owner_loss_and_readback_loss_are_indeterminate(self):
        for reason, owner_values, mode_values in (
            ("owner loss", [("makoctl", 991), ("makoctl", 991),
                            notifications.NotificationBridgeError("gone")],
             [[]]),
            ("mode read loss", [("makoctl", 991)] * 3,
             [[], notifications.NotificationBridgeError("unavailable")]),
        ):
            with self.subTest(reason=reason):
                with (
                    mock.patch.object(notifications, "_owned_mako",
                                      side_effect=owner_values) as owner,
                    mock.patch.object(notifications, "_modes",
                                      side_effect=mode_values),
                    mock.patch.object(notifications.subprocess, "run",
                                      return_value=subprocess.CompletedProcess([], 0)) as run,
                ):
                    with self.assertRaises(notifications.NotificationBridgeError) as captured:
                        notifications.set_dnd(True, expected=False)
                    self.assertEqual(captured.exception.code, "dnd_outcome_unknown")
                    run.assert_called_once()
                    self.assertEqual(owner.call_count, 3)

    def test_negative_acknowledgement_cannot_prove_no_mode_change(self):
        with (
            mock.patch.object(notifications, "_owned_mako", return_value=("makoctl", 991)),
            mock.patch.object(notifications, "_modes", return_value=[]),
            mock.patch.object(notifications.subprocess, "run",
                              return_value=subprocess.CompletedProcess([], 1)) as run,
        ):
            with self.assertRaises(notifications.NotificationBridgeError) as captured:
                notifications.set_dnd(True, expected=False)
            self.assertEqual(captured.exception.code, "dnd_outcome_unknown")
            self.assertTrue(notifications.invalid(
                captured.exception, attempted_dnd=True)["outcome_unknown"])
            self.assertIn("refresh", str(captured.exception).lower())
            run.assert_called_once()

    def test_noop_and_stale_review_do_not_mutate_notifications(self):
        with (
            mock.patch.object(notifications, "_owned_mako",
                              return_value=("makoctl", 991)),
            mock.patch.object(notifications, "_modes",
                              return_value=[notifications._DND_MODE]),
            mock.patch.object(notifications.subprocess, "run") as run,
        ):
            result = notifications.set_dnd(True, expected=True)
            self.assertFalse(result["changed"])
            self.assertTrue(result["do_not_disturb"])
            with self.assertRaises(notifications.NotificationBridgeError) as captured:
                notifications.set_dnd(False, expected=False)
            self.assertEqual(captured.exception.code, "stale_dnd_state")
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
