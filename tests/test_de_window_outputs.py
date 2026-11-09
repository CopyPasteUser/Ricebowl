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


if __name__ == "__main__":
    unittest.main()
