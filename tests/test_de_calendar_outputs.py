"""Pure analyzer QA; the native workflow provides the genuine grim captures."""

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from scripts.check_wayland_calendar_outputs import calendar_matches, visible_calendar


class CalendarOutputCheckTests(unittest.TestCase):
    def test_exactly_one_output_owns_the_popup(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory, f"{index}.png") for index in range(2)]

            def capture(visible):
                for index, path in enumerate(paths):
                    image = Image.new("RGB", (1024, 768), (0x20, 0x3C, 0x59))
                    if index == visible:
                        image.putpixel((1024 - 336 - 8 + 20,
                                        768 - 36 - 352 + 10), (0x41, 0x79, 0xAA))
                    image.save(path)

            for visible in (0, 1):
                capture(visible)
                self.assertEqual(visible_calendar(paths), visible)
            capture(None)
            self.assertEqual(calendar_matches(paths), [])
            with self.assertRaisesRegex(ValueError, "exactly one"):
                visible_calendar(paths)
            capture(0)
            with Image.open(paths[1]) as image:
                duplicate = image.copy()
            duplicate.putpixel((1024 - 336 - 8 + 20,
                                768 - 36 - 352 + 10), (0x41, 0x79, 0xAA))
            duplicate.save(paths[1])
            with self.assertRaisesRegex(ValueError, "found 2"):
                visible_calendar(paths)


    def test_reject_truncated_calendar_framebuffer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "partial-calendar.png")
            image = Image.new("RGB", (1024, 768), (0x20, 0x3C, 0x59))
            image.putpixel((1024 - 336 - 8 + 20,
                            768 - 36 - 352 + 10), (0x41, 0x79, 0xAA))
            image.save(path)
            self.assertEqual(calendar_matches([path]), [0])

            # Preserve the valid PNG header and early scanlines, but discard
            # most compressed image data. The analyzer must not trust a
            # visible header pixel from an incomplete compositor capture.
            data = path.read_bytes()
            path.write_bytes(data[:max(64, len(data) // 3)])
            with self.assertRaises((OSError, ValueError)):
                calendar_matches([path])

if __name__ == "__main__":
    unittest.main()
