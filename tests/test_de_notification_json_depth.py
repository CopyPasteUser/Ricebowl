"""Fail-closed RicePop parsing of deeply nested, bounded provider JSON."""
from __future__ import annotations

import subprocess
import unittest
from unittest import mock

from macrice.de import notifications


class RicePopJsonDepthTests(unittest.TestCase):
    @staticmethod
    def deeply_nested_reply() -> bytes:
        # Below the 128-KiB provider-response limit, but deeper than the
        # CPython JSON parser's recursion limit on supported Python versions.
        return b"[" * 12_000 + b"0" + b"]" * 12_000

    def test_bounded_recursive_provider_replies_get_typed_errors(self):
        reply = self.deeply_nested_reply()
        self.assertLess(len(reply), 128 * 1024)
        for parser in (notifications._records, notifications._busctl_records):
            with self.subTest(parser=parser.__name__):
                with self.assertRaises(notifications.NotificationBridgeError) as ctx:
                    parser(reply)
                self.assertEqual(ctx.exception.code, "invalid_notification_response")
                self.assertEqual(str(ctx.exception), "Notification host returned invalid JSON")

    def test_real_busctl_read_path_does_not_leak_unhandled_recursion(self):
        bad = subprocess.CompletedProcess(["busctl"], 0, self.deeply_nested_reply(), b"")
        with mock.patch.object(notifications.shutil, "which", return_value="/usr/bin/busctl"), \
             mock.patch.object(notifications.subprocess, "run", return_value=bad):
            with self.assertRaises(notifications.NotificationBridgeError) as ctx:
                notifications._read_mako("ListNotifications")
        self.assertEqual(ctx.exception.code, "invalid_notification_response")

    def test_native_private_snapshot_decoder_handles_json_recursion(self):
        # The native bridge uses an even smaller 8-KiB input limit; simulate
        # a decoder recursion failure independent of interpreter depth.
        with mock.patch.object(notifications.json, "loads",
                               side_effect=RecursionError("too many levels")):
            with self.assertRaises(notifications.NotificationBridgeError) as ctx:
                notifications.decode_gui_snapshot(b'{"id":1}')
        self.assertEqual(ctx.exception.code, "invalid_notification_snapshot")
        self.assertNotIn("too many levels", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
