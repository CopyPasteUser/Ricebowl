"""Schema v10: bounded visual tokens shared by native RicePlate and Waybar."""

import json
import tempfile
import unittest
from pathlib import Path

from macrice.de import catalog, creator_contract, drafts, pack, recipes, review


FIXTURE = Path(__file__).parent / "fixtures/riceplate-design-v10.json"


class DesignTokensTests(unittest.TestCase):
    def test_v10_design_is_preserved_by_review_and_waybar(self):
        source = FIXTURE.read_bytes()
        recipe = recipes.parse(source)
        self.assertEqual(recipe.schema_version, 10)
        self.assertEqual(recipe.design, (88, 14, 18, 16))
        self.assertEqual(recipe.tokens, (8, 5))
        self.assertEqual(recipe.composition.widgets[0].kind, "text")
        self.assertEqual(recipe.composition.widgets[1].component_ref, "net-status")
        self.assertEqual(review._manifest(recipe)["tokens"], json.loads(source)["tokens"])
        wide, css = recipes.waybar_config(recipe, screen_width=1366)
        compact, compact_css = recipes.waybar_config(recipe, screen_width=640)
        self.assertIn("rgba(32, 60, 89, 0.88)", css)
        self.assertIn("rgba(32, 60, 89, 0.88)", compact_css)
        self.assertIn('"custom/rice-control-', wide)
        self.assertNotIn('"custom/rice-control-', compact)
        info = catalog.describe()
        self.assertEqual(info["catalog_version"], 12)
        self.assertEqual(info["recipe"]["shell_extensions"]["tokens"]["panel_opacity"],
                         {"since_schema": 10, "range": [80, 100]})

    def test_v10_rejects_non_declarative_and_backward_incompatible_tokens(self):
        base = json.loads(FIXTURE.read_text())

        def rejects(update):
            candidate = json.loads(json.dumps(base))
            update(candidate)
            with self.assertRaises(recipes.RecipeError):
                recipes.parse(json.dumps(candidate).encode())

        rejects(lambda data: data.update(schema_version=9))
        rejects(lambda data: data["tokens"].pop("menu_radius"))
        rejects(lambda data: data["tokens"].update(menu_radius=-1))
        rejects(lambda data: data["tokens"].update(widget_radius=19))
        rejects(lambda data: data["tokens"].update(widget_padding=17))
        rejects(lambda data: data["tokens"].update(panel_opacity=0))
        rejects(lambda data: data["tokens"].update(panel_opacity=True))
        rejects(lambda data: data["tokens"].update(exec="true"))
        self.assertEqual(recipes.parse(Path(__file__).with_name("fixtures")
                         .joinpath("riceplate-components-v9.json").read_bytes()).design, None)

    def test_creator_edits_design_tokens_without_modifying_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.json"
            edit = Path(folder) / "edit.json"
            output = Path(folder) / "draft.json"
            source.write_bytes(FIXTURE.read_bytes())
            source.chmod(0o600)
            self.assertIn("/tokens/widget_radius", creator_contract.EDITABLE_PATHS)
            edit.write_text(json.dumps({"edit_version": 1, "operations": [
                {"op": "set", "path": "/tokens/widget_radius", "value": 0},
                {"op": "set", "path": "/tokens/panel_opacity", "value": 100},
            ]}))
            drafts.create_edit(recipe_token=str(source), edit_source=edit,
                               destination=output)
            self.assertEqual(recipes.parse(output.read_bytes()).design, (100, 14, 0, 16))
            self.assertEqual(recipes.parse(source.read_bytes()).design, (88, 14, 18, 16))
            exported = Path(folder) / "design.ricepack"
            pack.export_pack(str(output), exported)
            self.assertTrue(pack.inspect_pack(exported)["ok"])

    def test_private_v10_template_is_safe(self):
        for base in ("classic", "chrome"):
            with tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / "private.json"
                recipe = recipes.create_from_template(source=base, destination=target,
                                                      recipe_id="design-template", name="Design",
                                                      schema_version=10)
                self.assertEqual(recipe.design, (100, 4, 10, 12))
                self.assertEqual(recipes.parse(target.read_bytes()), recipe)
                self.assertEqual(target.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
