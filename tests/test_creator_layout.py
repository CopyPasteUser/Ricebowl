"""Creator canvas edits are genuine, bounded schema-v10 draft operations."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from macrice.de import creator_layout as layout, creator_workspace as workspace, recipes, review


class CreatorLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        state = Path(self.temp.name) / "state"
        state.mkdir(mode=0o700)
        environ = patch.dict(os.environ, {"XDG_STATE_HOME": str(state)})
        environ.start()
        self.addCleanup(environ.stop)
        self.info = workspace.create_draft("heritage")
        self.manifest = review.review(str(self.info.path))["recipe"]

    def test_viewport_preserves_geometry_and_pointer_mapping(self):
        view = layout.fit_viewport(510, 350, 1366, 768)
        self.assertAlmostEqual(view.width / view.height, 1366 / 768)
        self.assertEqual(view.to_screen(*view.to_canvas(241, 317)), (241, 317))
        tiny = layout.fit_viewport(20, 12, 1366, 768)
        self.assertLessEqual(tiny.width, 20)
        self.assertLessEqual(tiny.height, 12)
        for args in ((0, 10, 1366, 768), (50, 50, 0, 768)):
            with self.subTest(args=args), self.assertRaises(layout.LayoutError):
                layout.fit_viewport(*args)

    def test_hit_test_prefers_widgets_and_icons_over_reservation(self):
        self.assertEqual(layout.hit_test(self.manifest, 32, 340, 1366, 768), ("widget", 0))
        self.assertEqual(layout.hit_test(self.manifest, 40, 100, 1366, 768), ("icon", 0))
        self.assertEqual(layout.hit_test(self.manifest, 600, 400, 1366, 768), ("region", 0))
        self.assertIsNone(layout.hit_test(self.manifest, 10, 20, 1366, 768))

    def test_drag_coordinates_snap_and_export_valid_draft(self):
        moved = layout.move_layer(self.manifest, "widget", 0, 95, 395, 1366, 768, snap=8)
        self.assertEqual(moved["composition"]["widgets"][0]["x"], 96)
        self.assertEqual(moved["composition"]["widgets"][0]["y"], 392)
        self.assertEqual(self.manifest["composition"]["widgets"][0]["x"], 24)
        revised, changed = workspace.save_revision(self.info.path, {
            "/composition/widgets": moved["composition"]["widgets"],
        }, expected_sha256=self.info.semantic_sha256)
        self.assertEqual(changed[0]["path"], "/composition/widgets")
        self.assertEqual(recipes.load(str(revised.path)).composition.widgets[0].x, 96)
        self.assertEqual(self.info.path.stat().st_mode & 0o777, 0o600)

    def test_move_rejects_overlapping_shortcuts_without_changing_model(self):
        with self.assertRaises(layout.LayoutError):
            layout.move_layer(self.manifest, "icon", 1, 24, 92, 1366, 768)
        self.assertEqual(self.manifest["desktop"]["icons"][1]["x"], 144)
        clamped = layout.move_layer(self.manifest, "icon", 1, 9999, 9999, 1024, 768)
        self.assertLessEqual(clamped["desktop"]["icons"][1]["x"], 1024 - recipes.ICON_WIDTH)

    def test_create_widgets_and_actions_are_allowlisted_and_bounded(self):
        result = layout.add_layer(self.manifest, "text")
        self.assertEqual(result["composition"]["widgets"][-1]["kind"], "text")
        full = layout.add_layer(result, "clock")
        self.assertEqual(len(full["composition"]["widgets"]), recipes.MAX_DESKTOP_WIDGETS)
        with self.assertRaises(layout.LayoutError):
            layout.add_layer(full, "date")
        control = layout.add_layer(self.manifest, "component:wifi-switch")
        self.assertEqual(control["composition"]["widgets"][-1]["ref"], "wifi-switch")
        self.assertEqual(layout.layer_label(control, "widget", 2),
                         "◈  wifi-switch · action")
        self.assertEqual(recipes.parse(json.dumps(control).encode()).composition.widgets[2].kind,
                         "wifi-toggle")
        with self.assertRaises(layout.LayoutError):
            layout.add_layer(self.manifest, "command:rm")
        result = layout.add_layer(self.manifest, "icon:terminal")
        self.assertEqual(len(result["desktop"]["icons"]), 4)
        self.assertNotEqual(result["desktop"]["icons"][-1]["label"], "Console")

    def test_edit_text_region_and_compact_visibility(self):
        changed = layout.edit_layer(self.manifest, "widget", 0, {"text": "MODERN WORKSTATION"})
        hidden = layout.set_compact_hidden(changed, 0, True)
        self.assertEqual(hidden["composition"]["compact_hide_widgets"],
                         ["desk-network", "desk-heading"])
        resized = layout.edit_layer(hidden, "region", 0, {"width": 54, "height": 73})
        moved = layout.move_layer(resized, "region", 0, 1366, 768, 1366, 768)
        self.assertEqual(moved["composition"]["window_region"]["x"], 46)
        self.assertEqual(moved["composition"]["window_region"]["y"], 27)
        with self.assertRaises(layout.LayoutError):
            layout.edit_layer(self.manifest, "widget", 0, {"text": "🚫"})
        with self.assertRaises(layout.LayoutError):
            layout.edit_layer(self.manifest, "region", 0, {"width": 90})
        with self.assertRaises(layout.LayoutError):
            layout.edit_layer(self.manifest, "widget", -1, {"x": 12})
        with self.assertRaises(layout.LayoutError):
            layout.edit_layer(self.manifest, "region", 1, {"x": 12})

    def test_remove_widget_cleans_hide_list_and_retains_valid_icons(self):
        removed = layout.remove_layer(self.manifest, "widget", 1)
        self.assertEqual(removed["composition"]["compact_hide_widgets"], [])
        self.assertEqual(len(removed["composition"]["widgets"]), 1)
        with self.assertRaises(layout.LayoutError):
            layout.remove_layer(self.manifest, "region", 0)
        trimmed = self.manifest
        for _ in range(2):
            trimmed = layout.remove_layer(trimmed, "icon", 0)
        with self.assertRaises(layout.LayoutError):
            layout.remove_layer(trimmed, "icon", 0)


if __name__ == "__main__":
    unittest.main()
