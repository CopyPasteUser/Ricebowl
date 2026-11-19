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


if __name__ == "__main__":
    unittest.main()
