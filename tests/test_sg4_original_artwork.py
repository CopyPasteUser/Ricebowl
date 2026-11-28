"""SG4 RF01-RF03/RF06: replaced artwork is original, generated in-repo and reproducible.

The generator (scripts/build_original_artwork.py) is deterministic and offline.  SVGs must
match it byte-for-byte; JPEGs are compared by decoded pixels because libjpeg/Pillow builds
can encode the same picture to different bytes.
"""
from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree

from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_original_artwork",
                                              ROOT / "scripts" / "build_original_artwork.py")
art = importlib.util.module_from_spec(spec)
sys.modules["build_original_artwork"] = art
spec.loader.exec_module(art)

GOOGLE_BRAND_HEXES = ("#4285f4", "#ea4335", "#fbbc04", "#34a853")


class OriginalArtworkTests(unittest.TestCase):
    def test_tracked_svgs_and_aliases_match_the_generator_exactly(self):
        for rel, text in art.expected_svgs().items():
            with self.subTest(path=rel):
                self.assertEqual((ROOT / rel).read_text(encoding="utf-8"), text)
                ElementTree.fromstring(text)

    def test_tracked_wallpapers_match_the_generator_pixels(self):
        for rel, builder in art.WALLPAPERS.items():
            with self.subTest(path=rel):
                with Image.open(ROOT / rel) as tracked:
                    self.assertEqual((tracked.format, tracked.size), ("JPEG", (1920, 1080)))
                    diff = ImageChops.difference(tracked.convert("RGB"), builder())
                    mean = sum(ImageStat.Stat(diff).mean) / 3
                self.assertLess(mean, 4.0, f"{rel} no longer matches scripts/build_original_artwork.py")

    def test_generator_is_deterministic(self):
        first, second = art.luna_hills(), art.luna_hills()
        self.assertEqual(first.tobytes(), second.tobytes())
        self.assertEqual(art.ten_wallpaper("blue").tobytes(), art.ten_wallpaper("blue").tobytes())

    def test_generator_needs_no_network_or_inference(self):
        source = (ROOT / "scripts" / "build_original_artwork.py").read_text(encoding="utf-8")
        for forbidden in ("urllib", "requests", "socket", "http.client", "openai", "anthropic", "subprocess"):
            self.assertNotIn("import " + forbidden, source)

    def test_chrome_start_mark_has_no_google_brand_colours_or_quadrants(self):
        text = (ROOT / "assets/ricebowl-chrome-start.svg").read_text(encoding="utf-8").lower()
        for brand in GOOGLE_BRAND_HEXES:
            self.assertNotIn(brand, text)
        self.assertNotIn("four", text)
        self.assertEqual(len(re.findall(r"<rect[^>]*rx=\"6\"", text)), 0)

    def test_ten_assets_carry_no_four_pane_logo_or_hero_beam_composition(self):
        bloom = (ROOT / "assets/windows10-bloom.svg").read_text(encoding="utf-8")
        self.assertIn("RiceBowl Ten Bloom", bloom)
        self.assertNotIn("Penguin", bloom)
        grid = (ROOT / "assets/icons/RiceHub-Ten-Penguin/scalable/apps/applications-other.svg").read_text()
        self.assertEqual(len(re.findall(r"<rect", grid)), 9)  # app grid, not four window panes

    def test_luna_hills_is_not_a_single_green_hill_under_a_blue_sky(self):
        with Image.open(ROOT / "assets/wallpapers/luna-hills.jpg") as image:
            self.assertEqual(image.size, (1920, 1080))
            rgb = image.convert("RGB")
            # Dusk horizon: the sky just above the ridges is warm (red >= blue), unlike a uniform blue sky.
            horizon = rgb.getpixel((1500, 600))
            self.assertGreaterEqual(horizon[0] + 20, horizon[2])
            # Several distinct receding ridges: count colour changes down one column through the land.
            column = [rgb.getpixel((960, y)) for y in range(600, 1080, 4)]
            jumps = sum(1 for a, b in zip(column, column[1:]) if sum(abs(x - y) for x, y in zip(a, b)) > 30)
            self.assertGreaterEqual(jumps, 3)


if __name__ == "__main__":
    unittest.main()
