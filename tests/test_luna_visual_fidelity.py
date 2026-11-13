"""Luna Fidelity 2.0 uses a private labwc theme without affecting other rices."""

from pathlib import Path
import unittest

from macrice.de import recipes
from macrice.de.window_chrome import labwc_chrome


ROOT = Path(__file__).resolve().parents[1] / "examples" / "wayland"


class LunaWindowFidelityTests(unittest.TestCase):
    def test_luna_titles_have_distinct_active_inactive_gradients(self):
        luna = recipes.parse((ROOT / "xp-luna-columns.json").read_bytes())
        chrome = labwc_chrome(luna)
        self.assertIsNotNone(chrome)
        self.assertIn("window.active.title.bg.color: #4b9bed", chrome)
        self.assertIn("window.active.title.bg.colorTo: #17438f", chrome)
        self.assertIn("window.inactive.title.bg.color: #b5c8e6", chrome)
        self.assertIn("window.inactive.title.bg.colorTo: #7d98c3", chrome)
        self.assertIn("window.button.width: 26", chrome)
        self.assertIn("window.button.height: 26", chrome)
        self.assertIn("window.button.spacing: 2", chrome)
        self.assertIn("border.width: 2", chrome)
        self.assertEqual(chrome.count("window.active.title.bg:"), 1)

    def test_non_columns_and_legacy_rices_unchanged(self):
        regular = recipes.parse((ROOT / "xp-luna.json").read_bytes())
        self.assertIsNone(labwc_chrome(regular))
        # Other recipe-derived column themes must not inherit XP-specific hardcoded colors.
        another = recipes.parse((ROOT / "xp-luna-columns.json").read_bytes())
        from dataclasses import replace
        variant = replace(another, recipe_id="not-xp-luna")
        theme = labwc_chrome(variant)
        self.assertIn(f"window.active.title.bg.color: {another.menu_palette.header}", theme)
        self.assertNotIn("window.active.title.bg.color: #4b9bed", theme)


if __name__ == "__main__":
    unittest.main()
