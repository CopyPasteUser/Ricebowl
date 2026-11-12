"""Regression tests for native panel screenshot integrity and pixel matching.

Fixtures are synthetic and only test the analyzer; native CI supplies real
labwc/grim captures for compositor verification.
"""

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from scripts.check_wayland_panel_outputs import validate


class PanelOutputCheckTests(unittest.TestCase):
    def test_accepts_complete_classic_png_and_two_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory, f"output-{i}.png") for i in range(2)]
            for path in paths:
                Image.new("RGB", (1024, 768), (0x20, 0x3C, 0x59)).save(path)
            validate(paths)

    def test_rejects_truncated_png_even_with_valid_panel_pixel(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "truncated.png")
            # Use incompressible pixels so a truncated IDAT cannot contain a
            # complete framebuffer; preserve a valid classic panel sample.
            image = Image.effect_noise((1024, 768), 80).convert("RGB")
            image.putpixel((512, 763), (0x20, 0x3C, 0x59))
            image.save(path)
            validate([path])
            original = path.read_bytes()
            path.write_bytes(original[:len(original) // 2])
            with self.assertRaises((OSError, ValueError)):
                validate([path])

    def test_rejects_wrong_panel_and_invalid_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "wrong.png")
            Image.new("RGB", (1024, 768), "black").save(path)
            with self.assertRaisesRegex(ValueError, "No classic RiceBowl panel"):
                validate([path])
            Image.new("RGB", (320, 240), (0x20, 0x3C, 0x59)).save(path)
            with self.assertRaisesRegex(ValueError, "invalid PNG geometry"):
                validate([path])


if __name__ == "__main__":
    unittest.main()
