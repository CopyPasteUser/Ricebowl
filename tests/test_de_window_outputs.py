"""Pixel acceptance guard for live foreign-toplevel window smoke."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from scripts.check_wayland_window_outputs import changed_panel_pixels, validate


class WindowOutputsTest(unittest.TestCase):
    def test_task_region_changes_and_returns_to_empty(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            paths = [folder / f"{name}.png" for name in ("before", "opened", "closed")]
            for path in paths:
                Image.new("RGB", (1024, 768), "#202f46").save(path)
            with Image.open(paths[1]) as image:
                opened = image.copy()
            ImageDraw.Draw(opened).rectangle((112, 745, 180, 759), fill="#ffffff")
            opened.save(paths[1])
            on, off = validate(*paths)
            self.assertGreater(on, 30)
            self.assertEqual(off, 0)

    def test_ignores_clock_area_and_rejects_missing_task(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            first, second = folder / "one.png", folder / "two.png"
            Image.new("RGB", (1024, 768), "#202f46").save(first)
            with Image.open(first) as image:
                changed = image.copy()
            ImageDraw.Draw(changed).rectangle((950, 745, 1000, 760), fill="#ffffff")
            changed.save(second)
            self.assertEqual(changed_panel_pixels(first, second), 0)
            with self.assertRaisesRegex(ValueError, "did not visibly appear"):
                validate(first, second, first)


    def test_rejects_truncated_png_even_with_valid_taskbar_region(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            first, second = folder / "before.png", folder / "opened.png"
            Image.new("RGB", (1024, 768), "#202f46").save(first)
            with Image.open(first) as image:
                opened = image.copy()
            ImageDraw.Draw(opened).rectangle((112, 745, 180, 759), fill="#ffffff")
            opened.save(second)
            self.assertGreater(changed_panel_pixels(first, second), 30)

            # A valid header and partial IDAT must not be accepted as a
            # screenshot of the real application lifecycle.
            payload = second.read_bytes()
            second.write_bytes(payload[:max(64, len(payload) // 3)])
            with self.assertRaises((OSError, ValueError)):
                changed_panel_pixels(first, second)

    def test_rejects_missing_corrupt_or_followed_iend(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            first, second = folder / "before.png", folder / "opened.png"
            Image.new("RGB", (1024, 768), "#202f46").save(first)
            with Image.open(first) as image:
                opened = image.copy()
            ImageDraw.Draw(opened).rectangle((112, 745, 180, 759), fill="#ffffff")
            opened.save(second)
            self.assertGreater(changed_panel_pixels(first, second), 30)

            intact = second.read_bytes()
            self.assertEqual(intact[-8:-4], b"IEND")
            for kind, payload in (
                ("missing IEND", intact[:-12]),
                ("bad IEND CRC", intact[:-1] + bytes([intact[-1] ^ 0xFF])),
                ("trailing junk", intact + b"junk"),
            ):
                with self.subTest(corruption=kind):
                    second.write_bytes(payload)
                    with self.assertRaises((OSError, ValueError)):
                        changed_panel_pixels(first, second)

    def test_rejects_non_png_capture_even_when_pixels_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            first, second = folder / "before.png", folder / "opened.jpg"
            Image.new("RGB", (1024, 768), "#202f46").save(first)
            Image.new("RGB", (1024, 768), "#ffffff").save(second, format="JPEG")
            with self.assertRaisesRegex(ValueError, "must be PNG"):
                changed_panel_pixels(first, second)


if __name__ == "__main__":
    unittest.main()
