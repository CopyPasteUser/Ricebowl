"""Schema-v7 stateful controls share one validated native action vocabulary."""

import json
import tempfile
import unittest
from pathlib import Path

from macrice.de import catalog, drafts, recipes, review


FIXTURE = Path(__file__).parent / "fixtures/riceplate-controls-v7.json"


class PanelControlTests(unittest.TestCase):
    def test_v7_control_roundtrip_catalog_and_disabled_fallback(self):
        original = FIXTURE.read_bytes()
        parsed = recipes.parse(original)
        self.assertEqual(parsed.schema_version, 7)
        self.assertEqual(review._manifest(parsed), json.loads(original))
        metadata = catalog.describe()["recipe"]["nested_layout"]["node_types"]["control"]
        self.assertEqual(metadata["known_ids"], sorted(recipes.PANEL_CONTROLS))
        self.assertEqual(metadata["since_schema"], 7)
        self.assertEqual(metadata["waybar"], "disabled-status-only")
        standard, css = recipes.waybar_config(parsed, screen_width=1280)
        controls = [value for key, value in json.loads(standard).items()
                    if key.startswith("custom/rice-control-")]
        self.assertEqual(len(controls), 4)
        self.assertTrue(all("on-click" not in control for control in controls))
        self.assertTrue(all("(N/A)" in control["format"] for control in controls))
        self.assertIn("opacity: 0.55", css)
        compact, _ = recipes.waybar_config(parsed, screen_width=600)
        self.assertEqual(sum(key.startswith("custom/rice-control-")
                             for key in json.loads(compact)), 1)

    def test_legacy_and_malicious_controls_are_rejected(self):
        source = json.loads(FIXTURE.read_text())
        for node in [
            {"type": "control", "id": "terminal", "label": "Terminal"},
            {"type": "control", "id": "wifi-toggle", "label": "<bad>"},
            {"type": "control", "id": "audio-mute", "label": "Mute", "exec": "sh"},
            {"type": "control", "id": "bluetooth-toggle", "label": "BT"},
            {"type": "control", "id": "wifi-toggle", "label": True},
        ]:
            with self.subTest(node=node):
                data = json.loads(FIXTURE.read_text())
                data["panel"]["layout"]["end"][0] = node
                with self.assertRaises(recipes.RecipeError):
                    recipes.parse(json.dumps(data).encode())
        source["schema_version"] = 6
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(source).encode())
        data = json.loads(FIXTURE.read_text())
        data["responsive"]["compact_layout"]["end"][0]["label"] = "Other"
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(data).encode())

    def test_creator_revalidates_edit_without_changing_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "source.json"
            patch = root / "edit.json"
            destination = root / "draft.json"
            original.write_bytes(FIXTURE.read_bytes())
            original.chmod(0o600)
            patch.write_text(json.dumps({"edit_version": 1, "operations": [
                {"op": "set", "path": "/panel/layout/center", "value": [
                    {"type": "action", "id": "settings", "label": "Settings"},
                ]},
            ]}))
            receipt = drafts.create_edit(recipe_token=str(original), edit_source=patch,
                                         destination=destination)
            self.assertEqual(receipt["recipe_id"], "mockup-controls")
            parsed = recipes.load(str(destination))
            self.assertEqual(parsed.layout[1][0].value, "settings")
            self.assertEqual(original.read_bytes(), FIXTURE.read_bytes())
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
