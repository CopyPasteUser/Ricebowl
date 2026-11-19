"""SG2/SG3: saved settings must reject ambiguous JSON at every depth.

A duplicated field must not quietly change login-time monitor trials or
next-login notification and input settings. Invalid files stay untouched.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macrice.de import display_presets, notification_prefs, preferences


class PrivateSettingsJSONTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        environment = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": temporary.name})
        environment.start()
        self.addCleanup(environment.stop)
        self.directory = Path(temporary.name) / "ricebowl"
        self.directory.mkdir(mode=0o700)
        self.monitor = {
            "name": "eDP-1", "mode": "1920x1080@60Hz",
            "scale": 1.0, "x": 0, "y": 0,
        }

    def write(self, name: str, payload: str) -> Path:
        target = self.directory / name
        target.write_text(payload, encoding="utf-8")
        target.chmod(0o600)
        return target

    def test_ricespice_duplicate_field_rejected_without_overwriting(self):
        payload = json.dumps({"version": 2, **preferences.DEFAULTS}, sort_keys=True)
        self.assertEqual(preferences._decode(payload.encode()), preferences.DEFAULTS)
        duplicate = payload[:-1] + ', "high_contrast": true}'
        target = self.write("ricespice.json", duplicate)
        with self.assertRaisesRegex(preferences.PreferenceError, "Invalid RiceSpice"):
            preferences.load()
        with self.assertRaises(preferences.PreferenceError):
            preferences.save(preferences.DEFAULTS, expected=preferences.DEFAULTS)
        self.assertEqual(target.read_text(), duplicate)

    def test_ricepop_duplicate_version_and_choice_fail_closed(self):
        payload = json.dumps({"version": 1, **notification_prefs.DEFAULTS})
        target = self.write("ricepop-appearance.json", payload)
        self.assertEqual(notification_prefs.load(), notification_prefs.DEFAULTS)
        for duplicate in (
            payload[:-1] + ', "version": 1}',
            payload[:-1] + ', "max_visible": 8}',
        ):
            with self.subTest(duplicate=duplicate[-32:]):
                self.write("ricepop-appearance.json", duplicate)
                with self.assertRaisesRegex(ValueError, "invalid JSON"):
                    notification_prefs.load_optional()
                with self.assertRaises(ValueError):
                    notification_prefs.save(notification_prefs.DEFAULTS,
                                            expected=notification_prefs.DEFAULTS)
                self.assertEqual(target.read_text(), duplicate)

    def test_monitor_duplicate_autotrial_and_nested_identity_fail_closed(self):
        record = {"version": 2, "outputs": [self.monitor], "auto_trial": False}
        payload = json.dumps(record)
        target = self.write("ricespice-displays.json", payload)
        self.assertEqual(display_presets.load(), [self.monitor])
        self.assertFalse(display_presets.auto_trial_enabled())

        duplicated_login = payload[:-1] + ', "auto_trial": true}'
        duplicated_identity = payload.replace(
            '"name": "eDP-1"', '"name": "eDP-1", "name": "HDMI-1"')
        for duplicate in (duplicated_login, duplicated_identity):
            with self.subTest(duplicate=duplicate[-45:]):
                self.write("ricespice-displays.json", duplicate)
                with self.assertRaisesRegex(ValueError, "Invalid saved monitor JSON"):
                    display_presets.auto_trial_enabled()
                with self.assertRaises(ValueError):
                    display_presets.load()
                with self.assertRaises(ValueError):
                    display_presets.save([self.monitor], expected=[self.monitor])
                self.assertEqual(target.read_text(), duplicate)

    def test_unambiguous_legacy_monitor_presets_remain_compatible(self):
        self.write("ricespice-displays.json", json.dumps(
            {"version": 1, "outputs": [self.monitor]}))
        self.assertEqual(display_presets.load(), [self.monitor])
        self.assertFalse(display_presets.auto_trial_enabled())


if __name__ == "__main__":
    unittest.main()
