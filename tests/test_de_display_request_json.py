"""Monitor rollback workers must reject ambiguous JSON before any output mutation.

All requests are local test files. No compositor, xrandr or monitor hardware is
used. Existing valid transaction structures remain accepted.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macrice import display_guard
from macrice.de import display_restore, wayland_displays


class DisplayTransactionJSONTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.change = display_guard.DisplayChange("a" * 32, self.root)

    def request(self, content: str):
        path = display_guard._request_path(self.change)
        path.write_text(content, encoding="utf-8")
        path.chmod(0o600)

    def test_x11_worker_rejects_duplicate_request_before_monitor_inventory(self):
        self.request('{"name":"eDP-1","name":"HDMI-1","mode":"1600x900",'
                     '"x":10,"y":0,"old_mode":"1920x1080","old_x":0,"old_y":0}')
        with (
            mock.patch.object(display_guard.display_layout, "read_monitor_layout") as inventory,
            mock.patch.object(display_guard, "_run_xrandr") as setter,
        ):
            with self.assertRaisesRegex(ValueError, "Duplicate display transaction field"):
                display_guard.run_worker(self.change)
            inventory.assert_not_called()
            setter.assert_not_called()

    def test_wayland_worker_rejects_duplicate_scale_before_monitor_write(self):
        self.request('{"name":"eDP-1","mode":"1280x720@60Hz","scale":1,'
                     '"old_mode":"1920x1080@60Hz","old_scale":1,'
                     '"scale":2}')
        with (
            mock.patch.object(wayland_displays, "inventory") as inventory,
            mock.patch.object(wayland_displays, "_set") as setter,
        ):
            with self.assertRaisesRegex(ValueError, "Duplicate display transaction field"):
                wayland_displays.run_worker(self.change)
            inventory.assert_not_called()
            setter.assert_not_called()

    def test_full_layout_restore_rejects_nested_duplicate_output_identity(self):
        self.request('{"version":1,"baseline":[{"name":"eDP-1",'
                     '"name":"HDMI-A-1","mode":"1920x1080@60Hz",'
                     '"scale":1,"x":0,"y":0}],'
                     '"target":[]}')
        with mock.patch.object(wayland_displays, "_set") as setter:
            with self.assertRaisesRegex(ValueError, "Invalid monitor restore request"):
                display_restore.run_worker(self.change)
            setter.assert_not_called()

    def test_full_layout_request_keeps_existing_valid_contract(self):
        baseline = [{
            "name": "eDP-1", "mode": "1920x1080@60Hz",
            "scale": 1, "x": 0, "y": 0,
        }]
        target = [{
            "name": "eDP-1", "mode": "1280x720@60Hz",
            "scale": 1.25, "x": 0, "y": 0,
        }]
        self.request(json.dumps({"version": 1, "baseline": baseline, "target": target}))
        read_baseline, read_target = display_restore._request(self.change)
        self.assertEqual(read_baseline[0]["name"], "eDP-1")
        self.assertEqual(read_target[0]["scale"], 1.25)

    def test_duplicate_top_level_restore_request_never_reaches_output_changes(self):
        self.request('{"version":1,"version":1,"baseline":[],"target":[]}')
        with mock.patch.object(wayland_displays, "_set") as setter:
            with self.assertRaisesRegex(ValueError, "Invalid monitor restore request"):
                display_restore.run_worker(self.change)
            setter.assert_not_called()


    def test_confirmation_marker_must_be_exact_owner_private_true(self):
        marker = display_guard._keep_path(self.change)
        display_guard._write_new(marker, {"keep": True})
        self.assertTrue(display_guard._keep_requested(self.change))
        marker.unlink()

        for data in (
            b"", b"{}", b'{"keep":1}', b'{"keep":false}',
            b'{"keep":true,"keep":false}', b'{"keep":true,"extra":false}',
            b'{"keep":null}', b'{"keep":"true"}',
        ):
            with self.subTest(data=data):
                marker.write_bytes(data)
                marker.chmod(0o600)
                self.assertFalse(display_guard._keep_requested(self.change))
                marker.unlink()

        marker.write_text('{"keep":true}', encoding="utf-8")
        marker.chmod(0o644)
        self.assertFalse(display_guard._keep_requested(self.change))
        marker.unlink()
        outside = self.root / "outside"
        outside.write_text('{"keep":true}', encoding="utf-8")
        marker.symlink_to(outside)
        self.assertFalse(display_guard._keep_requested(self.change))
        self.assertEqual(outside.read_text(), '{"keep":true}')

    def test_ambiguous_guard_status_cannot_enable_confirmation(self):
        status = display_guard._state_path(self.change)
        status.write_text('{"state":"pending","state":"kept","detail":"forged"}')
        with self.assertRaisesRegex(RuntimeError, "Cannot read display guard status"):
            display_guard.keep_change(self.change)
        self.assertFalse(display_guard._keep_path(self.change).exists())

    def test_ignored_invalid_confirmation_rolls_back_to_previous_x11_mode(self):
        self.request('{"name":"eDP-1","mode":"1600x900","x":10,"y":0,'
                     '"old_mode":"1920x1080","old_x":0,"old_y":0}')
        display_guard._keep_path(self.change).write_text('{"keep":false}')
        from macrice import display_layout
        output = display_layout.DisplayOutput(
            "eDP-1", "1920x1080", (0, 0), True,
            ("1920x1080", "1600x900"))
        with (
            mock.patch.object(display_guard.display_layout, "read_monitor_layout",
                              return_value=(output,)),
            mock.patch.object(display_guard, "_run_xrandr") as set_mode,
            mock.patch.object(display_guard, "_check_current", return_value=True),
            mock.patch.object(display_guard.time, "monotonic", side_effect=(0, 19)),
        ):
            self.assertEqual(display_guard.run_worker(self.change), 1)
        self.assertEqual(set_mode.call_args_list, [
            mock.call("eDP-1", "1600x900", 10, 0),
            mock.call("eDP-1", "1920x1080", 0, 0),
        ])
        self.assertEqual(display_guard.read_status(self.change)[0], "reverted")


if __name__ == "__main__":
    unittest.main()
