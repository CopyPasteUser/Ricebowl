"""SG2 timedated service writes are not safe to replay after uncertain results.

No system clock, NTP or timezone is changed: all timedated service calls are
strictly mocked. Tests distinguish stale preflight from unknown write outcome.
"""
from datetime import datetime
import unittest
from unittest import mock

from macrice.de import settings_backend as backend


class TimedatedUnknownOutcomeTests(unittest.TestCase):
    NTP_OFF = {"available": True, "enabled": False}
    NTP_ON = {"available": True, "enabled": True}

    def test_ntp_timeout_after_preflight_is_indeterminate_and_not_retried(self):
        with (
            mock.patch.object(backend, "ntp_snapshot", return_value=self.NTP_OFF),
            mock.patch.object(backend, "_timedatectl",
                              side_effect=backend.SettingsError("timedated timed out")) as run,
        ):
            with self.assertRaisesRegex(backend.SettingsError, "outcome unknown"):
                backend.set_ntp(True, expected=False)
            run.assert_called_once_with("set-ntp", "true")

    def test_ntp_post_write_provider_loss_and_capability_change_fail_closed(self):
        with (
            mock.patch.object(backend, "ntp_snapshot",
                              side_effect=[self.NTP_OFF, backend.SettingsError("unavailable")]),
            mock.patch.object(backend, "_timedatectl", return_value="") as run,
        ):
            with self.assertRaisesRegex(backend.SettingsError, "verification unavailable"):
                backend.set_ntp(True, expected=False)
            run.assert_called_once_with("set-ntp", "true")
        with (
            mock.patch.object(backend, "ntp_snapshot",
                              side_effect=[self.NTP_OFF, {"available": False, "enabled": True}]),
            mock.patch.object(backend, "_timedatectl", return_value="") as run,
        ):
            with self.assertRaisesRegex(backend.SettingsError, "verification failed"):
                backend.set_ntp(True, expected=False)
            run.assert_called_once_with("set-ntp", "true")

    def test_timezone_timeout_and_readback_loss_do_not_repeat_mutation(self):
        inventory = {"current": "UTC", "zones": ("UTC", "Europe/Berlin")}
        for calls, message in (
            ([backend.SettingsError("timeout")], "outcome unknown"),
            (["", backend.SettingsError("readback unavailable")],
             "verification unavailable"),
            (["", "UTC"], "verification failed"),
        ):
            with self.subTest(message=message):
                with (
                    mock.patch.object(backend, "timezone_snapshot", return_value=inventory),
                    mock.patch.object(backend, "_timedatectl", side_effect=calls) as timedated,
                ):
                    with self.assertRaisesRegex(backend.SettingsError, message):
                        backend.set_timezone("Europe/Berlin", expected="UTC")
                    self.assertEqual(timedated.call_args_list.count(
                        mock.call("set-timezone", "Europe/Berlin")), 1)

    def test_manual_clock_timeout_remains_indeterminate_without_second_write(self):
        with (
            mock.patch.object(backend, "ntp_snapshot", return_value=self.NTP_OFF),
            mock.patch.object(backend, "_timedatectl",
                              side_effect=backend.SettingsError("timeout")) as timedated,
        ):
            with self.assertRaisesRegex(backend.SettingsError, "outcome unknown"):
                backend.set_system_clock("2026-11-19 10:00:00")
            timedated.assert_called_once_with("set-time", "2026-11-19 10:00:00")

    def test_ntp_noop_and_stale_state_remain_write_free(self):
        with (
            mock.patch.object(backend, "ntp_snapshot", return_value=self.NTP_ON),
            mock.patch.object(backend, "_timedatectl") as timedated,
        ):
            self.assertEqual(backend.set_ntp(True, expected=True), self.NTP_ON)
            with self.assertRaisesRegex(backend.SettingsError, "changed"):
                backend.set_ntp(False, expected=False)
            timedated.assert_not_called()


if __name__ == "__main__":
    unittest.main()
