"""Rice Creator 0.8 explicitly annotated, real-pixel reference diagnostics."""

import hashlib
import io
import unittest

from macrice.de import creator_regions as regions

try:
    from PIL import Image
except ImportError:
    Image = None


@unittest.skipIf(Image is None, "Optional Pillow missing")
class CreatorRegionTests(unittest.TestCase):
    @staticmethod
    def png(image):
        stream = io.BytesIO()
        image.save(stream, "PNG")
        return stream.getvalue()

    def setUp(self):
        self.before = Image.new("RGB", (80, 60), "#182b4a")
        self.after = self.before.copy()
        for y in range(10, 30):
            for x in range(20, 40):
                self.after.putpixel((x, y), (255, 255, 255))
        self.source = self.png(self.before)
        self.capture = self.png(self.after)
        self.sha = hashlib.sha256(self.source).hexdigest()
        self.recipe_sha = "f" * 64
        self.rois = [{"kind": "menu", "x": 20, "y": 10,
                      "width": 20, "height": 20},
                     {"kind": "panel", "x": 0, "y": 40,
                      "width": 80, "height": 20}]

    def inspect(self, *, rois=None, capture=None, radius=1):
        return regions.inspect(self.source, self.capture if capture is None else capture,
                               reference_sha256=self.sha, recipe_sha256=self.recipe_sha,
                               regions=self.rois if rois is None else rois,
                               tolerance_radius=radius)

    def test_region_errors_distinguish_changed_from_untouched_areas(self):
        result = self.inspect()
        self.assertEqual(result["region_report_version"], 1)
        self.assertEqual(result["capture_sha256"], hashlib.sha256(self.capture).hexdigest())
        self.assertEqual(result["regions"][0]["changed_pixel_ratio"], 1.0)
        self.assertEqual(result["regions"][1]["changed_pixel_ratio"], 0.0)
        self.assertEqual(result["regions"][0]["tolerance"]["changed_pixel_ratio"], 1.0)
        self.assertEqual(result["perceptual_or_functional_accuracy"], "not_measured")
        self.assertNotIn("reference_pixels", str(result))

    def test_subpixel_shift_uses_neighborhood_outside_region(self):
        original = Image.new("RGB", (80, 60), "#000000")
        shifted = original.copy()
        original.putpixel((19, 20), (255, 255, 255))
        shifted.putpixel((20, 20), (255, 255, 255))
        reference = self.png(original)
        roi = [{"kind": "unknown", "x": 20, "y": 19,
                "width": 2, "height": 3}]
        report = regions.inspect(reference, self.png(shifted),
                                 reference_sha256=hashlib.sha256(reference).hexdigest(),
                                 recipe_sha256=self.recipe_sha, regions=roi,
                                 tolerance_radius=1)
        self.assertGreater(report["regions"][0]["changed_pixels"], 0)
        self.assertEqual(report["regions"][0]["tolerance"]["changed_pixels"], 0)

    def test_overlay_is_a_copy_with_visible_annotations(self):
        output = regions.annotated_view(self.source, reference_sha256=self.sha,
                                        regions=self.rois)
        with Image.open(io.BytesIO(output)) as image:
            self.assertEqual(image.size, (80, 60))
            self.assertNotEqual(image.convert("RGB").getpixel((20, 10)),
                                self.before.getpixel((20, 10)))
        self.assertEqual(self.source, self.png(self.before))

    def test_malformed_bounds_duplicate_bool_and_volume_limits(self):
        for candidate in ([{**self.rois[0], "x": -1}],
                          [{**self.rois[0], "width": 61}],
                          [{**self.rois[0], "width": True}],
                          [{**self.rois[0], "kind": "custom"}],
                          [{**self.rois[0], "extra": "bad"}],
                          [self.rois[0], self.rois[0]],
                          [self.rois[1]] * 9,
                          [{"kind": "desktop", "x": 0, "y": 0,
                            "width": 80, "height": 60}] * 3):
            with self.subTest(candidate=candidate), self.assertRaises(regions.RegionError):
                regions.validate(candidate, size=(80, 60))

    def test_identity_resolution_and_policy_fail_closed(self):
        with self.assertRaisesRegex(regions.RegionError, "changed"):
            regions.inspect(self.source, self.capture, reference_sha256="0" * 64,
                            recipe_sha256=self.recipe_sha, regions=self.rois)
        with self.assertRaisesRegex(regions.RegionError, "resolutions"):
            self.inspect(capture=self.png(Image.new("RGB", (40, 60))))
        with self.assertRaises(regions.RegionError):
            self.inspect(rois=[])
        with self.assertRaises(regions.RegionError):
            regions.inspect(self.source, self.capture, reference_sha256=self.sha,
                            recipe_sha256="not-a-hash", regions=self.rois)
        for policy in ({"threshold": True}, {"threshold": 256},
                       {"tolerance_radius": 3}):
            with self.subTest(policy=policy), self.assertRaises(regions.RegionError):
                regions.inspect(self.source, self.capture,
                                reference_sha256=self.sha, recipe_sha256=self.recipe_sha,
                                regions=self.rois, **policy)
