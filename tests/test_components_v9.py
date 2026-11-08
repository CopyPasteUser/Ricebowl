"""Schema v9: one bounded capability binding reused in native/Waybar surfaces."""

import json
import tempfile
import unittest
from pathlib import Path

from macrice.de import catalog, creator_contract, drafts, pack, recipes, review


FIXTURE = Path(__file__).parent / "fixtures/riceplate-components-v9.json"


class SharedComponentTests(unittest.TestCase):
    def test_one_network_binding_drives_panel_compact_and_desktop(self):
        recipe = recipes.parse(FIXTURE.read_bytes())
        self.assertEqual(recipe.schema_version, 9)
        self.assertEqual(recipe.sections[2], ("network", "clock"))
        self.assertEqual(recipe.compact[1][2][0].value, "net-status")
        self.assertEqual(recipe.composition.widgets[1].kind, "network")
        self.assertEqual(recipe.composition.widgets[1].component_ref, "net-status")
        self.assertEqual(recipe.composition.widgets[2].kind, "audio")
        self.assertIn("/components", creator_contract.EDITABLE_PATHS)
        info = catalog.describe()
        self.assertEqual(info["catalog_version"], 10)
        self.assertEqual(info["recipe"]["component_library"]["status_bindings"],
                         sorted(recipes.COMPONENT_STATUS_BINDINGS))
        wide, _ = recipes.waybar_config(recipe, screen_width=1366)
        compact, _ = recipes.waybar_config(recipe, screen_width=640)
        self.assertIn("Wi-Fi (N/A)", wide)
        self.assertNotIn("Wi-Fi (N/A)", compact)
        self.assertIn('"network"', compact)

    def test_unknown_dangerous_and_cross_surface_roles_rejected(self):
        sample = json.loads(FIXTURE.read_text())

        def rejects(update):
            candidate = json.loads(json.dumps(sample))
            update(candidate)
            with self.assertRaises(recipes.RecipeError):
                recipes.parse(json.dumps(candidate).encode())

        rejects(lambda data: data["components"][0].update(binding="bash -c id"))
        rejects(lambda data: data["components"][0].update(binding=["network"]))
        rejects(lambda data: data["components"][0].update(exec="echo unsafe"))
        rejects(lambda data: data["components"][0].update(id="wifi-switch"))
        rejects(lambda data: data["components"][1].update(role="shell"))
        rejects(lambda data: data["panel"]["layout"]["start"][2].update(ref="missing"))
        rejects(lambda data: data["composition"]["widgets"][1].update(ref="wifi-switch"))
        rejects(lambda data: data["composition"]["widgets"][1].update(kind="exec"))
        rejects(lambda data: data.update(schema_version=8))
        rejects(lambda data: data.pop("components"))
        rejects(lambda data: data["components"].extend(data["components"] * 3))

    def test_creator_preserves_refs_and_edits_bindings_without_touching_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.json"
            patch = Path(folder) / "patch.json"
            output = Path(folder) / "draft.json"
            source.write_bytes(FIXTURE.read_bytes())
            source.chmod(0o600)
            baseline = review.review(str(source))
            self.assertEqual(baseline["recipe"]["panel"]["layout"]["end"][0],
                             {"type": "component", "ref": "net-status"})
            self.assertEqual(baseline["recipe"]["composition"]["widgets"][1]["kind"],
                             "component")
            declarations = baseline["recipe"]["components"]
            declarations[0] = {**declarations[0], "label": "Online"}
            patch.write_text(json.dumps({"edit_version": 1, "operations": [
                {"op": "set", "path": "/components", "value": declarations},
            ]}))
            result = drafts.create_edit(recipe_token=str(source), edit_source=patch,
                                        destination=output)
            self.assertEqual(len(result["changes"]), 1)
            self.assertEqual(result["changes"][0]["path"], "/components")
            self.assertEqual(review.review(str(output))["recipe"]["components"][0]["label"],
                             "Online")
            self.assertEqual(review.review(str(source))["recipe"]["components"][0]["label"],
                             "Network")

    def test_v9_private_template_preserves_v8_and_legacy_contracts(self):
        for base in ("classic", "chrome"):
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "private.json"
                recipe = recipes.create_from_template(source=base, destination=path,
                                                      recipe_id="my-components", name="Components",
                                                      schema_version=9)
                self.assertEqual(recipe.schema_version, 9)
                self.assertEqual(len(recipe.components), 2)
                self.assertEqual(recipes.parse(path.read_bytes()), recipe)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(recipes.parse(Path(__file__).parent.joinpath(
            "fixtures/riceplate-layout-v8.json").read_bytes()).schema_version, 8)

    def test_v9_ricepack_export_is_lossless_and_non_executable(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "v9.json"
            source.write_bytes(FIXTURE.read_bytes())
            source.chmod(0o600)
            exported = Path(folder) / "v9.ricepack"
            pack.export_pack(str(source), exported)
            inspected = pack.inspect_pack(exported)
            self.assertTrue(inspected["ok"])
            self.assertFalse(inspected["applied"])


if __name__ == "__main__":
    unittest.main()
