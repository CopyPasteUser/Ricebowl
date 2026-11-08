"""Cross-backend v8 shell composition: validated areas, widgets and breakpoints."""

import json
import tempfile
import unittest
from pathlib import Path

from macrice.de import creator_contract, drafts, recipes, review


FIXTURE = Path(__file__).parent / "fixtures/riceplate-layout-v8.json"


class LayoutEngineTests(unittest.TestCase):
    def test_versioned_multi_region_fixture_and_legacy_compatibility(self):
        recipe = recipes.parse(FIXTURE.read_bytes())
        self.assertEqual(recipe.schema_version, 8)
        self.assertEqual(recipe.composition.window_region,
                         recipes.WindowRegion(30, 8, 66, 84))
        self.assertEqual([widget.kind for widget in recipe.composition.widgets],
                         ["clock", "system", "date"])
        self.assertEqual(recipe.composition.compact_hide_widgets,
                         ("desk-system", "desk-date"))
        self.assertEqual(recipe.menu_presentation, "sidebar")
        for legacy in ("classic", "chrome"):
            self.assertIsNone(recipes.load(legacy).composition)

    def test_invalid_compositions_reject_unknown_actions_bounds_and_references(self):
        source = json.loads(FIXTURE.read_text())

        def invalid(change):
            candidate = json.loads(json.dumps(source))
            change(candidate)
            with self.assertRaises(recipes.RecipeError):
                recipes.parse(json.dumps(candidate).encode())

        invalid(lambda value: value["composition"]["widgets"][0].update(kind="shell-command"))
        invalid(lambda value: value["composition"]["widgets"][0].update(kind=["clock"]))
        invalid(lambda value: value["composition"]["widgets"][0].update(exec="terminal"))
        invalid(lambda value: value["composition"]["widgets"].append(
            {"id": "desk-clock", "kind": "date", "x": 1, "y": 1}))
        invalid(lambda value: value["composition"]["widgets"][0].update(x=True))
        invalid(lambda value: value["composition"]["widgets"][0].update(y=99999))
        invalid(lambda value: value["composition"]["window_region"].update(width=80))
        invalid(lambda value: value["composition"]["compact_hide_widgets"].append("missing"))
        invalid(lambda value: value["composition"]["compact_hide_widgets"].append("desk-system"))
        invalid(lambda value: value["composition"].update(executable="nope"))
        invalid(lambda value: value.update(schema_version=7))
        invalid(lambda value: value.pop("composition"))

    def test_template_exports_editable_v8_without_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "layout.json"
            recipe = recipes.create_from_template(
                source="classic", destination=path, recipe_id="layout-example",
                name="Layout Example", schema_version=8)
            self.assertEqual(recipe.schema_version, 8)
            self.assertEqual(len(recipe.composition.widgets), 2)
            self.assertEqual(recipes.parse(path.read_bytes()), recipe)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                recipes.create_from_template(
                    source="classic", destination=path, recipe_id="layout-example",
                    name="Layout Example", schema_version=8)

    def test_creator_review_and_draft_edits_preserve_full_desktop_composition(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.json"
            patch = Path(directory) / "edit.json"
            output = Path(directory) / "edited.json"
            source.write_bytes(FIXTURE.read_bytes())
            source.chmod(0o600)
            snapshot = review.review(str(source))
            self.assertEqual(snapshot["recipe"]["composition"]["widgets"][1]["id"],
                             "desk-system")
            self.assertIn("/composition/widgets", creator_contract.EDITABLE_PATHS)
            patch.write_text(json.dumps({"edit_version": 1, "operations": [
                {"op": "set", "path": "/composition/window_region",
                 "value": {"x": 35, "y": 8, "width": 61, "height": 84}},
                {"op": "set", "path": "/composition/compact_hide_widgets",
                 "value": ["desk-date"]},
            ]}))
            result = drafts.create_edit(recipe_token=str(source), edit_source=patch,
                                        destination=output)
            self.assertEqual(recipes.load(str(output)).composition.window_region.x, 35)
            self.assertEqual(recipes.load(str(output)).composition.compact_hide_widgets,
                             ("desk-date",))
            self.assertEqual(len(result["changes"]), 2)
            self.assertEqual(result["draft_semantic_sha256"],
                             review.review(str(output))["summary"]["semantic_sha256"])
            self.assertEqual(recipes.load(str(source)).composition.window_region.x, 30)


if __name__ == "__main__":
    unittest.main()
