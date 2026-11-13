"""Native Wayland XP Luna taskbar settings remain owner-private."""
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from macrice.de import luna_taskbar_settings as options


class NativeLunaTaskbarOptionsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        patch = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root)})
        patch.start()
        self.addCleanup(patch.stop)
        self.path = self.root / "ricebowl" / "luna-taskbar.json"

    def test_defaults_are_read_only(self):
        self.assertEqual(options.load(), {"auto_hide": False, "quick_launch": True})
        self.assertFalse(self.path.parent.exists())

    def test_private_atomic_save_and_cas(self):
        before = options.load()
        chosen = {"auto_hide": True, "quick_launch": False}
        self.assertEqual(options.save(chosen, expected=before), chosen)
        self.assertEqual(options.load(), chosen)
        self.assertEqual(json.loads(self.path.read_text()), {"version": 1, **chosen})
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertFalse(list(self.path.parent.glob(".luna-taskbar-*")))
        with self.assertRaisesRegex(options.TaskbarSettingsError, "changed elsewhere"):
            options.save(before, expected=before)
        self.assertEqual(options.load(), chosen)
        self.assertEqual(options.save(before, expected=chosen), before)

    def test_invalid_types_and_schema_fail_closed(self):
        self.path.parent.mkdir()
        for data in [
            {"version": 2, **options.DEFAULTS},
            {"version": True, **options.DEFAULTS},
            {"version": 1, "auto_hide": 1, "quick_launch": False},
            {"version": 1, "auto_hide": False},
            {"version": 1, **options.DEFAULTS, "command": "rm"},
        ]:
            self.path.write_text(json.dumps(data))
            self.path.chmod(0o600)
            with self.subTest(data=data), self.assertRaises(options.TaskbarSettingsError):
                options.load()
        with self.assertRaises(options.TaskbarSettingsError):
            options.save({"auto_hide": True, "quick_launch": 1}, expected=options.DEFAULTS)

    def test_symlink_and_world_readable_file_rejected(self):
        self.path.parent.mkdir()
        target = self.root / "target.json"
        target.write_text("{}")
        self.path.symlink_to(target)
        with self.assertRaises(options.TaskbarSettingsError):
            options.load()
        self.path.unlink()
        self.path.write_text("{}")
        self.path.chmod(0o644)
        with self.assertRaises(options.TaskbarSettingsError):
            options.load()
        self.path.chmod(0o600)
        self.path.write_bytes(b"x" * 300)
        with self.assertRaises(options.TaskbarSettingsError):
            options.load()

    def test_untrusted_directory_and_relative_root(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "relative"}):
            with self.assertRaises(options.TaskbarSettingsError):
                options.load()
        target = self.root / "real"
        target.mkdir()
        (self.root / "ricebowl").symlink_to(target, target_is_directory=True)
        with self.assertRaises(options.TaskbarSettingsError):
            options.load()


if __name__ == "__main__":
    unittest.main()
