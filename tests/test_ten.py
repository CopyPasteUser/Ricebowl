"""Safe Windows 10 rice roundtrip and artwork tests (no real desktop writes)."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macrice import ten
from macrice.aero import read_autostart as read_aero
from macrice.aero_pins import pin_file
from macrice.installer import project_root
from macrice.rice import RiceError, STYLES, apply, plan, restore
from macrice.ten_shell import CSS
from tests.test_rice import FakeBackend, setup_apps


class TenTests(unittest.TestCase):
    def test_complete_light_dark_assets(self):
        root = project_root()
        for key in ("ten-dark", "ten-light"):
            style = STYLES[key]
            self.assertIn(style.gtk, ten.THEMES)
            self.assertTrue((root / "assets/wallpapers" / style.wallpaper).is_file())
            self.assertEqual((root / "assets/wallpapers" / style.wallpaper).read_bytes()[:3], b"\xff\xd8\xff")
            chrome = root / "assets/themes" / style.xfwm / "xfwm4"
            for state in ("active", "inactive"):
                for part in ("top-left", "top-right", "title-1", "title-5", "bottom", "left", "right"):
                    self.assertTrue((chrome / f"{part}-{state}.png").is_file())
            for button in ("close", "maximize", "hide"):
                for state in ("active", "inactive", "prelight", "pressed"):
                    self.assertTrue((chrome / f"{button}-{state}.png").is_file())
        mark = (root / "assets/ten-start.svg").read_text(encoding="utf-8")
        self.assertIn("RiceBowl Ten Start", mark)
        self.assertNotIn("M2 4 12", mark)
        self.assertEqual(mark, (root / "assets/icons/RiceHub-Ten-Penguin/scalable/apps/start-here.svg")
                         .read_text(encoding="utf-8"))
        self.assertIn(b"ten-tile", CSS)

    def test_preflight_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = FakeBackend()
            setup_apps(root / "config")
            changes, _previous, source, target = plan("ten-light", backend=fake,
                                                      data_root=root / "data", config_root=root / "config")
            self.assertTrue(source.is_file())
            self.assertTrue(str(target).endswith(".jpg"))
            self.assertFalse((root / "data").exists())
            self.assertEqual(fake.calls, [])
            self.assertIn("RiceHub-Ten-Light", {c["after"] for c in changes})

    def test_apply_restore_and_switch_from_aero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = FakeBackend()
            setup_apps(root / "config")
            original = fake.values.copy()
            aero_backup = apply("aero-meadow", backend=fake, data_root=root / "data", config_root=root / "config")
            self.assertIsNotNone(read_aero(root / "config"))
            ten_backup = apply("ten-dark", backend=fake, data_root=root / "data", config_root=root / "config")
            self.assertIsNone(read_aero(root / "config"))
            self.assertIn("windows10-shell", ten.read_autostart(root / "config"))
            manifest = json.loads((ten_backup / "manifest.json").read_text())
            self.assertEqual(manifest["schema"], 5)
            self.assertTrue((root / "data/themes/RiceHub-Ten-Dark/gtk-3.0/gtk.css").is_file())
            self.assertTrue((root / "data/icons/RiceHub-Ten-Penguin/index.theme").is_file())
            self.assertEqual(fake.get("xfconf", "xsettings", "/Net/IconThemeName"), ten.ICON_THEME)
            self.assertTrue((root / "data/plank/themes/RiceHub-Ten-Flat/dock.theme").is_file())
            restore(backend=fake, data_root=root / "data", config_root=root / "config")
            self.assertIsNotNone(read_aero(root / "config"))
            self.assertIsNone(ten.read_autostart(root / "config"))
            restore(backend=fake, data_root=root / "data", config_root=root / "config")
            self.assertEqual(fake.values, original)
            self.assertIsNone(read_aero(root / "config"))
            self.assertIsNone(ten.read_autostart(root / "config"))
            self.assertTrue((aero_backup / "restored").is_file())

    def test_customized_theme_and_autostart_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = FakeBackend()
            setup_apps(root / "config")
            theme = root / "data/themes/RiceHub-Ten-Light/gtk-3.0/gtk.css"
            theme.parent.mkdir(parents=True)
            theme.write_text("my own theme", encoding="utf-8")
            with self.assertRaisesRegex(RiceError, "conflicts"):
                apply("ten-light", backend=fake, data_root=root / "data", config_root=root / "config")
            self.assertEqual(fake.calls, [])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = FakeBackend()
            setup_apps(root / "config")
            target = ten.autostart_file(root / "config")
            target.parent.mkdir(parents=True)
            target.write_text("[Desktop Entry]\nExec=other\n", encoding="utf-8")
            with self.assertRaisesRegex(RiceError, "not managed"):
                apply("ten-dark", backend=fake, data_root=root / "data", config_root=root / "config")
            self.assertEqual(fake.calls, [])

    def test_upgrade_keeps_user_customized_legacy_icon_theme(self):
        """RC1 can remain installed without blocking the new penguin artwork."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_theme = root / "data/icons/RiceHub-Ten"
            old_theme.mkdir(parents=True)
            (old_theme / "index.theme").write_text("user-edited legacy icons", encoding="utf-8")
            fake = FakeBackend()
            setup_apps(root / "config")
            backup = apply("ten-dark", backend=fake, data_root=root / "data", config_root=root / "config")
            self.assertEqual((old_theme / "index.theme").read_text(encoding="utf-8"),
                             "user-edited legacy icons")
            self.assertTrue((root / "data/icons" / ten.ICON_THEME / "index.theme").is_file())
            restore(backend=fake, data_root=root / "data", config_root=root / "config")
            self.assertTrue((backup / "restored").is_file())
    def test_pins_do_not_cross_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": tmp}):
                self.assertNotEqual(pin_file("aero"), pin_file("windows10"))

    def test_failed_apply_restores_previous_autostart_and_desktop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = FakeBackend()
            setup_apps(root / "config")
            original = fake.values.copy()
            apply("aero-meadow", backend=fake, data_root=root / "data", config_root=root / "config")
            aero_state = fake.values.copy()
            with mock.patch("macrice.rice.set_theme_values", side_effect=RuntimeError("injected failure")):
                with self.assertRaisesRegex(RiceError, "rolled back"):
                    apply("ten-light", backend=fake, data_root=root / "data", config_root=root / "config")
            self.assertEqual(fake.values, aero_state)
            self.assertIsNotNone(read_aero(root / "config"))
            self.assertIsNone(ten.read_autostart(root / "config"))
            restore(backend=fake, data_root=root / "data", config_root=root / "config")
            self.assertEqual(fake.values, original)

    def test_schema3_aero_snapshot_is_still_restorable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = FakeBackend()
            setup_apps(root / "config")
            original = fake.values.copy()
            backup = apply("aero-meadow", backend=fake, data_root=root / "data", config_root=root / "config")
            manifest_path = backup / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["schema"] = 3
            manifest["aero_autostart"] = manifest.pop("shell_autostarts")["aero"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            restore(backend=fake, data_root=root / "data", config_root=root / "config")
            self.assertEqual(fake.values, original)

    def test_manipulated_schema4_autostart_contents_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = FakeBackend()
            setup_apps(root / "config")
            backup = apply("ten-light", backend=fake, data_root=root / "data", config_root=root / "config")
            manifest_path = backup / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["shell_autostarts"]["ten"]["before"] = "[Desktop Entry]\nExec=bad\n"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            old = fake.values.copy()
            with self.assertRaisesRegex(RiceError, "Invalid Rice backup"):
                restore(backend=fake, data_root=root / "data", config_root=root / "config")
            self.assertEqual(fake.values, old)


if __name__ == "__main__":
    unittest.main()
