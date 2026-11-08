"""Real data-only nested RicePlate panel composition, not a mock renderer."""

import json
import tempfile
import unittest
from pathlib import Path

from macrice.de import catalog, drafts, recipes, review

FIXTURE = Path(__file__).parent / "fixtures/riceplate-nested-v3.json"


def _v3():
    source = json.loads(recipes.BUILTINS["classic"].read_text())
    source["schema_version"] = 3
    sections = source["panel"].pop("sections")
    source["panel"]["metrics"] = dict(zip(recipes.METRIC_FIELDS, recipes.METRIC_DEFAULTS))
    source["panel"]["layout"] = {
        section: [{"type": "widget", "id": name} for name in sections[section]]
        for section in recipes.SECTIONS
    }
    return source


class NestedPanelTests(unittest.TestCase):
    def test_shared_native_headless_fixture_validates_in_python_and_waybar(self):
        parsed = recipes.parse(FIXTURE.read_bytes())
        self.assertEqual(parsed.recipe_id, "my-layout")
        self.assertEqual(parsed.sections, (("launcher", "tasks"), (), ("clock",)))
        config_raw, css = recipes.waybar_config(parsed)
        config = json.loads(config_raw)
        self.assertEqual(config["modules-left"][0], "custom/rice-launcher")
        self.assertEqual(config["modules-left"][-1], "wlr/taskbar")
        self.assertIn('min-width: 20px', css)

    def test_nested_group_gap_label_render_in_real_waybar_adapter(self):
        data = _v3()
        data["panel"]["layout"]["start"] = [
            {"type": "group", "gap": 12, "children": [
                {"type": "widget", "id": "launcher"},
                {"type": "group", "gap": 4, "children": [
                    {"type": "label", "text": "WORKSPACE 01"},
                    {"type": "gap", "width": 20},
                    {"type": "divider", "width": 12},
                ]},
                {"type": "widget", "id": "tasks"},
            ]},
        ]
        parsed = recipes.parse(json.dumps(data).encode())
        self.assertEqual(parsed.schema_version, 3)
        self.assertEqual(parsed.sections[0], ("launcher", "tasks"))
        manifest = review._manifest(parsed)
        self.assertEqual(manifest, data)
        config_raw, css = recipes.waybar_config(parsed)
        config = json.loads(config_raw)
        modules = config["modules-left"]
        self.assertEqual(modules[0], "custom/rice-launcher")
        self.assertEqual(modules[-1], "wlr/taskbar")
        self.assertIn("custom/rice-label-", " ".join(modules))
        self.assertIn("custom/rice-gap-", " ".join(modules))
        self.assertIn("custom/rice-divider-", " ".join(modules))
        label = next(key for key in modules if key.startswith("custom/rice-label-"))
        self.assertEqual(config[label]["format"], "WORKSPACE 01")
        self.assertNotIn("exec", config[label])
        self.assertIn("min-width: 20px", css)
        self.assertIn("border-left: 1px solid", css)
        self.assertEqual(config["spacing"], 0)

    def test_init_v3_and_creator_edit_preserve_identity_and_runtime_schema(self):
        from macrice.cli import main
        with tempfile.TemporaryDirectory() as folder:
            original = Path(folder) / "base.json"
            patch = Path(folder) / "patch.json"
            destination = Path(folder) / "draft.json"
            self.assertEqual(main(["de", "recipe-init", "--base", "chrome",
                                   "--schema-version", "3", "--id", "ai-desktop",
                                   "--name", "AI Desktop", "--output", str(original)]), 0)
            self.assertEqual(recipes.load(str(original)).schema_version, 3)
            changes = {"edit_version": 1, "operations": [
                {"op": "set", "path": "/panel/layout/start", "value": [
                    {"type": "group", "gap": 8, "children": [
                        {"type": "widget", "id": "launcher"},
                        {"type": "label", "text": "Y2K"},
                    ]},
                ]},
                {"op": "set", "path": "/panel/metrics/clock_width", "value": 112},
            ]}
            patch.write_text(json.dumps(changes))
            patch.chmod(0o600)
            result = drafts.create_edit(recipe_token=str(original), edit_source=patch,
                                        destination=destination)
            self.assertEqual(result["recipe_id"], "ai-desktop")
            self.assertEqual(recipes.load(str(destination)).schema_version, 3)
            self.assertEqual(recipes.load(str(destination)).metrics[-1], 112)
            self.assertEqual({entry["path"] for entry in review.review(
                str(destination), str(original))["comparison"]["changes"]},
                {"/panel/layout/start", "/panel/metrics/clock_width"})
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)

    def test_old_sections_and_v3_layout_are_mutually_exclusive(self):
        data = _v3()
        data["panel"]["sections"] = {section: [] for section in recipes.SECTIONS}
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(data).encode())
        data = _v3()
        data["panel"]["layout"].pop("start")
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(data).encode())
        data = _v3()
        data["schema_version"] = 2
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(data).encode())

    def test_rejects_executable_markup_unknown_nodes_and_unsafe_values(self):
        bad_nodes = [
            {"type": "label", "text": "<script>"},
            {"type": "label", "text": "{exec}"},
            {"type": "widget", "id": "run-command"},
            {"type": "widget", "id": "launcher", "on_click": "rm -rf"},
            {"type": "gap", "width": True},
            {"type": "gap", "width": 1000},
            {"type": "divider", "width": 5},
            {"type": "divider", "width": True},
            {"type": "divider", "width": 33},
            {"type": "divider", "width": 12, "exec": "unsafe"},
            {"type": "group", "gap": -1, "children": [{"type": "widget", "id": "launcher"}]},
            {"type": "group", "gap": 5, "children": []},
            {"type": "unknown", "payload": "ignore"},
        ]
        for node in bad_nodes:
            with self.subTest(node=node):
                data = _v3()
                data["panel"]["layout"]["start"] = [node]
                with self.assertRaises(recipes.RecipeError):
                    recipes.parse(json.dumps(data).encode())

    def test_global_limits_and_duplicate_widgets_fail_closed(self):
        data = _v3()
        data["panel"]["layout"]["start"].append({"type": "widget", "id": "clock"})
        with self.assertRaisesRegex(recipes.RecipeError, "only once"):
            recipes.parse(json.dumps(data).encode())
        data = _v3()
        data["panel"]["layout"]["start"] = [
            {"type": "label", "text": "x"} for _ in range(9)
        ]
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(data).encode())
        data = _v3()
        data["panel"]["layout"]["start"] = [{"type": "group", "gap": 0, "children": [
            {"type": "group", "gap": 0, "children": [
                {"type": "group", "gap": 0, "children": [
                    {"type": "widget", "id": "launcher"},
                ]},
            ]},
        ]}]
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(data).encode())

    def test_catalog_describes_actual_native_and_fallback_node_constraints(self):
        result = catalog.describe()
        self.assertEqual(result["catalog_version"], 10)
        nested = result["recipe"]["nested_layout"]
        self.assertEqual(nested["max_nodes"], recipes.MAX_LAYOUT_NODES)
        self.assertEqual(nested["max_depth"], recipes.MAX_LAYOUT_DEPTH)
        self.assertEqual({item["id"] for item in result["layout_primitives"]},
                         {"label", "group", "gap", "divider", "action"})
        self.assertTrue(set(("/panel/layout/start", "/panel/layout/center",
                             "/panel/layout/end")).issubset(
                                 set(result["authoring"]["draft_edit"]["editable_paths"])))


if __name__ == "__main__":
    unittest.main()
