"""v9 desktop primitives share real shell state and preserve strict v8 input."""

import json
import tempfile
import unittest
from pathlib import Path

from macrice.de import catalog, creator_contract, drafts, recipes, review


FIXTURE = Path(__file__).parent / "fixtures/riceplate-components-v9.json"


class ComponentSystemV9Tests(unittest.TestCase):
    def test_valid_text_and_read_only_linux_status_bindings(self):
        recipe = recipes.parse(FIXTURE.read_bytes())
        self.assertEqual(recipe.schema_version, 9)
        self.assertEqual([(w.kind, w.text, w.source) for w in recipe.composition.widgets], [
            ("text", "Welcome to RiceBowl", ""),
            ("status", "", "network"),
            ("status", "", "battery"),
        ])
        self.assertEqual(review._manifest(recipe)["composition"]["widgets"],
                         json.loads(FIXTURE.read_text())["composition"]["widgets"])
        self.assertEqual(catalog.describe()["catalog_version"], 10)
        self.assertEqual(catalog.describe()["recipe"]["shell_extensions"]["desktop"]
                         ["widgets"]["v9_components"]["status"]["sources"],
                         sorted(recipes.DESKTOP_STATUS_SOURCES))
        self.assertIn(9, creator_contract.describe_ricepack()["recipe_schema_versions"])

    def test_v8_is_immutable_and_v9_rejects_executable_or_unrenderable_nodes(self):
        source = json.loads(FIXTURE.read_text())

        def reject(change):
            value = json.loads(json.dumps(source))
            change(value)
            with self.assertRaises(recipes.RecipeError):
                recipes.parse(json.dumps(value).encode())

        reject(lambda r: r.update(schema_version=8))
        reject(lambda r: r["composition"]["widgets"][0].update(exec="sh"))
        reject(lambda r: r["composition"]["widgets"][0].update(text="A" * 23))
        reject(lambda r: r["composition"]["widgets"][0].update(text="$(whoami)"))
        reject(lambda r: r["composition"]["widgets"][0].update(text=123))
        reject(lambda r: r["composition"]["widgets"][0].pop("text"))
        reject(lambda r: r["composition"]["widgets"][1].update(source="exec"))
        reject(lambda r: r["composition"]["widgets"][1].update(source="network", text="hi"))
        reject(lambda r: r["composition"]["widgets"][1].update(source=None))
        reject(lambda r: r["composition"]["widgets"][1].pop("source"))
        reject(lambda r: r["composition"]["widgets"][1].update(source=True))

    def test_creator_draft_and_v9_template_roundtrip(self):
        with tempfile.TemporaryDirectory() as location:
            folder = Path(location)
            source = folder / "source.json"
            source.write_bytes(FIXTURE.read_bytes())
            source.chmod(0o600)
            edit = folder / "edit.json"
            edit.write_text(json.dumps({"edit_version": 1, "operations": [{
                "op": "set", "path": "/composition/widgets", "value": [
                    {"id": "desk-title", "kind": "text", "text": "Hello RiceBowl", "x": 32, "y": 320},
                    {"id": "desk-audio", "kind": "status", "source": "audio", "x": 32, "y": 432},
                ],
            }, {"op": "set", "path": "/composition/compact_hide_widgets", "value": ["desk-audio"]}]}))
            destination = folder / "draft.json"
            result = drafts.create_edit(recipe_token=str(source), edit_source=edit,
                                        destination=destination)
            self.assertEqual(result["draft_semantic_sha256"],
                             review.review(str(destination))["summary"]["semantic_sha256"])
            self.assertEqual(recipes.load(str(destination)).composition.widgets[1].source, "audio")
            self.assertEqual(recipes.load(str(source)).composition.widgets[1].source, "network")
            template = recipes.create_from_template(
                source="classic", destination=folder / "v9.json",
                recipe_id="component-demo", name="Component demo", schema_version=9)
            self.assertEqual(template.composition.widgets[1].source, "network")


if __name__ == "__main__":
    unittest.main()
