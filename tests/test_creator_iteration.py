"""Rice Creator 0.9 source-pixel drag and comparable version receipts."""

import copy
import hashlib
import io
import unittest

from macrice.de import creator_iteration, creator_regions

try:
    from PIL import Image
except ImportError:
    Image = None


class CreatorPointerTests(unittest.TestCase):
    def select(self, a=(10, 15), b=(40, 35), **changes):
        kwargs = {"displayed": (100, 50), "source": (200, 100), "kind": "menu"}
        kwargs.update(changes)
        return creator_iteration.drag_rectangle(a, b, **kwargs)

    def test_forward_reverse_and_fractional_scale(self):
        rect = self.select()
        self.assertEqual(rect, {"kind": "menu", "x": 20, "y": 30,
                                "width": 60, "height": 40})
        self.assertEqual(self.select((40, 35), (10, 15)), rect)
        self.assertEqual(self.select((3.5, 4), (15.1, 19.25),
                                     displayed=(64, 60), source=(1000, 800)),
                         {"kind": "menu", "x": 54, "y": 53,
                          "width": 182, "height": 204})

    def test_release_outside_image_is_clamped(self):
        self.assertEqual(self.select((20, 10), (150, -200)),
                         {"kind": "menu", "x": 40, "y": 0,
                          "width": 160, "height": 20})

    def test_rejects_click_outside_start_nan_and_bad_scale(self):
        for args in (((0, 0), (1, 40), {}),
                     ((-1, 0), (20, 40), {}),
                     ((0, 0), (float("nan"), 20), {}),
                     ((1, 1), (20, 20), {"source": (0, 20)}),
                     ((1, 1), (20, 20), {"displayed": (100, True)}),
                     ((1, 1), (20, 20), {"kind": "untrusted"})):
            with self.subTest(args=args), self.assertRaises(creator_regions.RegionError):
                self.select(args[0], args[1], **args[2])


@unittest.skipIf(Image is None, "Optional Pillow missing")
class CreatorIterationTests(unittest.TestCase):
    @staticmethod
    def png(image):
        out = io.BytesIO()
        image.save(out, "PNG")
        return out.getvalue()

    def setUp(self):
        reference = Image.new("RGB", (30, 24), "#101010")
        flawed = reference.copy()
        improved = reference.copy()
        for x in range(4, 14):
            for y in range(3, 12):
                flawed.putpixel((x, y), (255, 255, 255))
        for x in range(4, 9):
            for y in range(3, 12):
                improved.putpixel((x, y), (255, 255, 255))
        self.original = self.png(reference)
        self.flawed = self.png(flawed)
        self.improved = self.png(improved)
        self.regions = [{"kind": "menu", "x": 3, "y": 2,
                         "width": 13, "height": 12}]

    def measure(self, image, recipe_sha="b" * 64, *, regions=None, threshold=24):
        return creator_regions.inspect(self.original, image,
                                       reference_sha256=hashlib.sha256(self.original).hexdigest(),
                                       recipe_sha256=recipe_sha,
                                       regions=self.regions if regions is None else regions,
                                       threshold=threshold, tolerance_radius=0)

    def test_successive_saved_revisions_have_real_pixel_deltas(self):
        a = self.measure(self.flawed)
        b = self.measure(self.improved, "c" * 64)
        original_a = copy.deepcopy(a)
        result = creator_iteration.journal([a, b])
        self.assertEqual(result["iteration_version"], 1)
        self.assertEqual(len(result["measurements"]), 2)
        self.assertEqual(result["comparisons"][0]["from_recipe_sha256"], "b" * 64)
        self.assertEqual(result["comparisons"][0]["regions"][0]["direction"], "lower")
        self.assertLess(result["comparisons"][0]["regions"][0]
                        ["tolerated_changed_percentage_point_delta"], 0)
        self.assertEqual(a, original_a)
        self.assertNotIn("screenshot", str(result))

    def test_worse_and_unchanged_deltas(self):
        a = self.measure(self.improved)
        b = self.measure(self.flawed, "c" * 64)
        c = self.measure(self.flawed, "d" * 64)
        result = creator_iteration.journal([a, b, c])
        self.assertEqual([c["regions"][0]["direction"]
                          for c in result["comparisons"]], ["higher", "unchanged"])

    def test_incompatible_reference_regions_and_policy_fail_closed(self):
        a = self.measure(self.flawed)
        for changed in (
            self.measure(self.improved, regions=[{**self.regions[0], "x": 4}]),
            self.measure(self.improved, threshold=12),
            {**self.measure(self.improved), "reference_sha256": "d" * 64},
            {**self.measure(self.improved), "regions": []},
        ):
            with self.subTest(changed=changed), self.assertRaises(creator_regions.RegionError):
                creator_iteration.journal([a, changed])

    def test_history_is_bounded_and_rejects_tampered_metrics(self):
        sample = self.measure(self.flawed)
        with self.assertRaises(creator_regions.RegionError):
            creator_iteration.journal([sample] * (creator_iteration.MAX_MEASUREMENTS + 1))
        with self.assertRaises(creator_regions.RegionError):
            creator_iteration.journal([])
        tampered = copy.deepcopy(sample)
        tampered["regions"][0]["tolerance"]["changed_pixel_ratio"] = float("nan")
        with self.assertRaises(creator_regions.RegionError):
            creator_iteration.journal([tampered])
