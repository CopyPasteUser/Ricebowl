"""Schema v9: one bounded capability binding reused in native/Waybar surfaces."""

import json
import tempfile
import unittest
from pathlib import Path

from macrice.de import catalog, creator_contract, drafts, pack, recipes, review


FIXTURE = Path(__file__).parent / "fixtures/riceplate-components-v9.json"
DESKTOP_ACTIONS = FIXTURE.parent / "riceplate-desktop-actions-v9.json"


class SharedComponentTests(unittest.TestCase):
    def test_one_network_binding_drives_panel_compact_and_desktop(self):
        recipe = recipes.parse(FIXTURE.read_bytes())
        self.assertEqual(recipe.schema_version, 9)
        self.assertEqual(recipe.sections[2], ("network", "clock"))
        self.assertEqual(recipe.compact[1][2][0].value, "net-status")
        self.assertEqual(recipe.composition.widgets[1].kind, "network")
        self.assertEqual(recipe.composition.widgets[1].component_ref, "net-status")
        self.assertEqual(recipe.composition.widgets[2].kind, "audio")
        self.assertEqual(recipe.composition.widgets[3].kind, "text")
        self.assertEqual(recipe.composition.widgets[3].text, "Welcome to RiceBowl")
        self.assertIn("/components", creator_contract.EDITABLE_PATHS)
        info = catalog.describe()
        self.assertEqual(info["catalog_version"], 14)
        widgets_catalog = info["recipe"]["shell_extensions"]["desktop"]["widgets"]
        self.assertEqual(widgets_catalog["text"]["max_characters"], 22)
        self.assertEqual(widgets_catalog["pointer_input"],
                         "transparent-for-status-action-hit-region-only")
        self.assertFalse(info["recipe"]["component_library"]["desktop_status_only"])
        self.assertIn("wifi-toggle", widgets_catalog["action_components"]["bindings"])
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
        rejects(lambda data: data["composition"]["widgets"][1].update(ref="does-not-exist"))
        rejects(lambda data: data["composition"]["widgets"][1].update(kind="exec"))
        rejects(lambda data: data["composition"]["widgets"][3].update(text="$(id)"))
        rejects(lambda data: data["composition"]["widgets"][3].update(text="A" * 23))
        rejects(lambda data: data["composition"]["widgets"][3].update(text="❤"))
        rejects(lambda data: data["composition"]["widgets"][3].update(exec="id"))
        rejects(lambda data: data["composition"]["widgets"][3].update(kind="system"))
        rejects(lambda data: data["composition"]["widgets"][3].pop("text"))
        rejects(lambda data: data.update(schema_version=8))
        rejects(lambda data: data.pop("components"))
        rejects(lambda data: data["components"].extend(data["components"] * 3))

    def test_desktop_reuses_allowlisted_action_with_creator_and_pack(self):
        data = json.loads(FIXTURE.read_text())
        data["composition"]["widgets"][2]["ref"] = "wifi-switch"
        parsed = recipes.parse(json.dumps(data).encode())
        self.assertEqual(parsed.composition.widgets[2].kind, "wifi-toggle")
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "shared.json"
            source.write_text(json.dumps(data))
            source.chmod(0o600)
            reviewed = review.review(str(source))
            self.assertEqual(reviewed["recipe"]["composition"]["widgets"][2]["ref"],
                             "wifi-switch")
            exported = Path(folder) / "shared.ricepack"
            pack.export_pack(str(source), exported)
            self.assertTrue(pack.inspect_pack(exported)["ok"])
        # An existing status component stays read-only; no untrusted command
        # can be smuggled through an action-bound desktop widget.
        data["components"][1]["binding"] = "sh -c id"
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(data).encode())

    def test_native_action_demonstrator_has_bounded_shared_controls(self):
        recipe = recipes.parse(DESKTOP_ACTIONS.read_bytes())
        self.assertEqual([widget.kind for widget in recipe.composition.widgets],
                         ["settings", "wifi-toggle", "network"])
        self.assertEqual(recipe.schema_version, 9)

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
            self.assertEqual(baseline["recipe"]["composition"]["widgets"][3],
                             {"id": "desk-title", "kind": "text", "text": "Welcome to RiceBowl",
                              "x": 32, "y": 656})
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
            self.assertEqual(review.review(str(output))["recipe"]["composition"]["widgets"][3]
                             ["text"], "Welcome to RiceBowl")
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

    def test_creator_edits_static_text_widget_with_shared_status_bindings(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.json"
            edit = Path(folder) / "edit.json"
            output = Path(folder) / "draft.json"
            source.write_bytes(FIXTURE.read_bytes())
            source.chmod(0o600)
            widgets = json.loads(source.read_text())["composition"]["widgets"]
            widgets[3]["text"] = "My Desktop"
            edit.write_text(json.dumps({"edit_version": 1, "operations": [
                {"op": "set", "path": "/composition/widgets", "value": widgets},
            ]}))
            drafts.create_edit(recipe_token=str(source), edit_source=edit,
                               destination=output)
            parsed = recipes.parse(output.read_bytes())
            self.assertEqual(parsed.composition.widgets[3].text, "My Desktop")
            self.assertEqual(parsed.composition.widgets[1].component_ref, "net-status")
            self.assertEqual(recipes.parse(source.read_bytes()).composition.widgets[3].text,
                             "Welcome to RiceBowl")

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
