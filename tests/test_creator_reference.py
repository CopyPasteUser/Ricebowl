"""Creator 0.6 references: private persistence, pixel QA and fail-closed IO."""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macrice.de import creator_reference as reference

try:
    from PIL import Image
except ImportError:
    Image = None


@unittest.skipIf(Image is None, "Optional Pillow not installed")
class CreatorReferenceTests(unittest.TestCase):
    draft = "creator-012345abcdef"

    def setUp(self):
        self.root = tempfile.TemporaryDirectory(prefix="ricebowl-ref-test-")
        self.addCleanup(self.root.cleanup)
        state = Path(self.root.name) / "state"
        state.mkdir(mode=0o700)
        self.environment = mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(state)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.source = Path(self.root.name) / "reference.png"
        Image.new("RGB", (24, 16), "#445566").save(self.source)

    def _png(self, color):
        output = io.BytesIO()
        Image.new("RGB", (24, 16), color).save(output, "PNG")
        return output.getvalue()

    def test_load_and_reopen_reference_across_draft_versions(self):
        selected = reference.select(self.draft, self.source)
        reopened = reference.selected(self.draft)
        self.assertEqual(selected, reopened)
        self.assertEqual(reference.image_bytes(self.draft), self.source.read_bytes())
        self.assertEqual((selected.width, selected.height), (24, 16))
        self.assertEqual(selected.sha256, __import__("hashlib").sha256(self.source.read_bytes()).hexdigest())
        folder = reference._folder()
        self.assertEqual((folder.stat().st_mode & 0o777), 0o700)
        for file in folder.iterdir():
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
        self.assertIsNone(reference.selected("creator-fedcba654321"))

    def test_real_comparison_generates_split_overlay_and_tolerant_heatmap(self):
        reference.select(self.draft, self.source)
        capture = self._png("#445566")
        metrics, images = reference.compare_capture(self.draft, capture)
        self.assertEqual(set(images), {"native", "reference", "wipe", "overlay", "heatmap"})
        self.assertEqual(metrics["changed_pixel_ratio"], 0)
        self.assertEqual(metrics["tolerance"]["radius_pixels"], 1)
        self.assertEqual(metrics["perceptual_or_functional_accuracy"], "not_measured")
        for contents in images.values():
            with Image.open(io.BytesIO(contents)) as output:
                self.assertEqual(output.size, (24, 16))

        altered = Image.new("RGB", (24, 16), "#445566")
        for y in range(16):
            for x in range(12, 24):
                altered.putpixel((x, y), (255, 255, 255))
        stream = io.BytesIO()
        altered.save(stream, "PNG")
        metrics, images = reference.compare_capture(self.draft, stream.getvalue(),
                                                    tolerance_radius=0)
        self.assertEqual(metrics["changed_pixel_ratio"], 0.5)
        with Image.open(io.BytesIO(images["wipe"])) as image:
            self.assertEqual(image.getpixel((2, 8)), (68, 85, 102))
            self.assertEqual(image.getpixel((20, 8)), (255, 255, 255))
        with Image.open(io.BytesIO(images["heatmap"])) as image:
            self.assertEqual(image.getpixel((2, 8)), (0, 0, 0))
            self.assertGreater(image.getpixel((20, 8))[0], 0)

    def test_resolution_mismatch_fails_without_outputs_or_resizing(self):
        reference.select(self.draft, self.source)
        stream = io.BytesIO()
        Image.new("RGB", (25, 16)).save(stream, "PNG")
        with self.assertRaisesRegex(reference.ReferenceError, "resolutions differ"):
            reference.compare_capture(self.draft, stream.getvalue())
        self.assertEqual(len(list(reference._folder().glob("*.png"))), 1)

    def test_symlinks_untrusted_inputs_and_invalid_png_are_rejected(self):
        link = Path(self.root.name) / "link.png"
        link.symlink_to(self.source)
        with self.assertRaises(reference.ReferenceError):
            reference.select(self.draft, link)
        self.source.write_bytes(b"not really a PNG")
        with self.assertRaises(reference.ReferenceError):
            reference.select(self.draft, self.source)
        with self.assertRaises(reference.ReferenceError):
            reference.select("../../unsafe", self.source)
        self.assertIsNone(reference.selected(self.draft))

    def test_corrupt_record_symlink_and_tampering_fail_closed(self):
        reference.select(self.draft, self.source)
        record = reference._folder() / f"{self.draft}.json"
        record.write_text('{"version": 2}')
        with self.assertRaisesRegex(reference.ReferenceError, "Malformed"):
            reference.selected(self.draft)
        record.unlink()
        record.symlink_to(self.source)
        with self.assertRaises(reference.ReferenceError):
            reference.selected(self.draft)
        record.unlink()
        reference.select(self.draft, self.source)
        image = next(reference._folder().glob("reference-*.png"))
        image.write_bytes(self._png("#000000"))
        with self.assertRaisesRegex(reference.ReferenceError, "integrity"):
            reference.selected(self.draft)

    def test_unlink_does_not_delete_source_or_versioned_artwork(self):
        reference.select(self.draft, self.source)
        reference.clear(self.draft)
        self.assertIsNone(reference.selected(self.draft))
        self.assertTrue(self.source.exists())
        self.assertEqual(len(list(reference._folder().glob("reference-*.png"))), 1)

    def test_private_record_must_not_accept_duplicate_or_unknown_fields(self):
        reference.select(self.draft, self.source)
        pointer = reference._folder() / f"{self.draft}.json"
        data = json.loads(pointer.read_text())
        data["location"] = "/etc/passwd"
        pointer.write_text(json.dumps(data))
        with self.assertRaisesRegex(reference.ReferenceError, "Malformed"):
            reference.selected(self.draft)
        data.pop("location")
        pointer.write_text(json.dumps(data).replace('"version": 1',
                                                 '"version": 1, "version": 2'))
        with self.assertRaisesRegex(reference.ReferenceError, "Malformed"):
            reference.selected(self.draft)

    def test_replacing_reference_keeps_original_immutable_and_links_new_digest(self):
        first = reference.select(self.draft, self.source)
        second_source = Path(self.root.name) / "second.png"
        Image.new("RGB", (24, 16), "#123456").save(second_source)
        second = reference.select(self.draft, second_source)
        self.assertNotEqual(first.sha256, second.sha256)
        with self.assertRaisesRegex(reference.ReferenceError, "changed during comparison"):
            reference.compare_capture(self.draft, self._png("#123456"),
                                      expected_sha256=first.sha256)
        self.assertEqual(reference.selected(self.draft), second)
        self.assertEqual(len(list(reference._folder().glob("reference-*.png"))), 2)
        self.assertEqual(reference.image_bytes(self.draft), second_source.read_bytes())


if __name__ == "__main__":
    unittest.main()
