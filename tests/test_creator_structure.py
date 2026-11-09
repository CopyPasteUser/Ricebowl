"""Creator 0.4 structural edits are bounded, versioned and not live-applied."""

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from macrice.de import creator_structure as structure, creator_workspace, drafts, recipes, review


def template():
    source = creator_workspace.TEMPLATES["heritage"][1]
    return review._manifest(recipes.parse(recipes._read_import_source(source)))


class CreatorStructureTests(unittest.TestCase):
    def setUp(self):
        self.original = template()

    def test_nested_groups_add_move_edit_and_ungroup(self):
        original = copy.deepcopy(self.original)
        lane = structure.edit_layout(original, "start", (2,), "wrap")
        self.assertEqual(lane[2]["type"], "group")
        edited = copy.deepcopy(original)
        edited["panel"]["layout"]["start"] = lane
        lane = structure.edit_layout(edited, "start", (2,), "add",
                                     node={"type": "label", "text": "Tasks"})
        self.assertEqual(len(lane[2]["children"]), 2)
        edited["panel"]["layout"]["start"] = lane
        lane = structure.edit_layout(edited, "start", (2, 1), "up")
        self.assertEqual(lane[2]["children"][0]["text"], "Tasks")
        edited["panel"]["layout"]["start"] = lane
        group = copy.deepcopy(lane[2])
        group["gap"] = 12
        lane = structure.edit_layout(edited, "start", (2,), "replace", node=group)
        self.assertEqual(lane[2]["gap"], 12)
        edited["panel"]["layout"]["start"] = lane
        lane = structure.edit_layout(edited, "start", (2,), "ungroup")
        self.assertEqual([item["type"] for item in lane],
                         ["widget", "gap", "label", "widget"])
        self.assertEqual(self.original, original)

    def test_compact_layout_edits_do_not_touch_wide(self):
        lane = structure.edit_layout(self.original, "center", (), "add",
                                     node={"type": "label", "text": "Compact"}, compact=True)
        self.assertEqual(lane[-1], {"type": "label", "text": "Compact"})
        self.assertEqual(self.original["panel"]["layout"]["center"], [])
        self.assertEqual(self.original["responsive"]["compact_layout"]["center"],
                         [{"type": "widget", "id": "tasks"}])

    def test_invalid_paths_overflows_and_duplicate_actions_rejected(self):
        for path, action, item in (
            ((50,), "remove", None),
            ((False,), "up", None),
            ((0, 1), "remove", None),
            ((0,), "ungroup", None),
            ((), "add", {"type": "widget", "id": "launcher"}),
            ((), "add", {"type": "action", "id": "terminal", "label": "\n"}),
            ((), "add", {"type": "group", "gap": 999, "children": []}),
        ):
            with self.subTest(path=path, action=action, item=item):
                with self.assertRaises(structure.StructureError):
                    structure.edit_layout(self.original, "start", path, action, node=item)
        original = copy.deepcopy(self.original)
        original["panel"]["layout"]["center"] = [
            {"type": "group", "gap": 0, "children": [
                {"type": "group", "gap": 0, "children": [
                    {"type": "gap", "width": 4},
                ]},
            ]},
        ]
        with self.assertRaises(structure.StructureError):
            structure.edit_layout(original, "center", (0, 0, 0), "wrap")

    def test_component_create_edit_and_referenced_removal(self):
        original = copy.deepcopy(self.original)
        addition = {"id": "quiet-time", "role": "status", "binding": "clock",
                    "label": "Quiet time"}
        components = structure.edit_component(original, "add", addition)
        self.assertIn(addition, components)
        edited = copy.deepcopy(original)
        edited["components"] = components
        rename = {**addition, "label": "Calendar"}
        components = structure.edit_component(edited, "update", rename,
                                              identifier="quiet-time")
        self.assertIn(rename, components)
        edited["components"] = components
        self.assertNotIn("quiet-time", structure.component_uses(edited, "quiet-time"))
        components = structure.edit_component(edited, "remove", identifier="quiet-time")
        self.assertNotIn(rename, components)
        with self.assertRaisesRegex(structure.StructureError, "used by"):
            structure.edit_component(original, "remove", identifier="wifi-switch")

    def test_duplicate_components_and_invalid_updates_fail_closed(self):
        original = copy.deepcopy(self.original)
        existing = original["components"][0]
        for action, value, identifier in (
            ("add", existing, None),
            ("add", {"id": "unsafe-id", "role": "action", "binding": "curl https://x",
                     "label": "Untrusted"}, None),
            ("update", {**existing, "id": "changed-id"}, existing["id"]),
            ("remove", None, "missing-id"),
        ):
            with self.subTest(action=action, value=value):
                with self.assertRaises(structure.StructureError):
                    structure.edit_component(original, action, value, identifier=identifier)

    def test_in_use_component_binding_change_respects_runtime_contract(self):
        old = next(row for row in self.original["components"] if row["id"] == "net-status")
        with self.assertRaises(structure.StructureError):
            structure.edit_component(self.original, "update",
                                     {**old, "role": "action", "binding": "terminal"},
                                     identifier="net-status")

    def test_atomic_edit_uses_new_definitions_independent_of_operation_order(self):
        added = {"id": "fresh-battery", "role": "status", "binding": "battery",
                 "label": "Battery"}
        layout = [{"type": "component", "ref": "fresh-battery"}]
        for operations in (
            [("/panel/layout/center", layout),
             ("/components", self.original["components"] + [added])],
            [("/components", self.original["components"] + [added]),
             ("/panel/layout/center", layout)],
        ):
            payload = json.dumps({"edit_version": 1, "operations": [
                {"op": "set", "path": path, "value": value}
                for path, value in operations
            ]}).encode()
            parsed = drafts._parse_edit(payload, schema_version=10, components={
                key.component_id: key for key in
                recipes.parse(json.dumps(self.original).encode()).components
            })
            self.assertEqual(len(parsed), 2)


class CreatorStructureDraftIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / "state"
        self.state.mkdir(mode=0o700)
        environment = patch.dict(os.environ, {"XDG_STATE_HOME": str(self.state)})
        environment.start()
        self.addCleanup(environment.stop)

    def test_structural_changes_produce_a_portable_private_version(self):
        info = creator_workspace.create_draft("heritage")
        original_bytes = info.path.read_bytes()
        manifest = review.review(str(info.path))["recipe"]
        component = {"id": "new-battery", "role": "status", "binding": "battery",
                     "label": "Battery"}
        updated = structure.edit_component(manifest, "add", component)
        with_component = copy.deepcopy(manifest)
        with_component["components"] = updated
        lane = structure.edit_layout(with_component, "center", (), "add",
                                     node={"type": "component", "ref": "new-battery"})
        saved, changes = creator_workspace.save_revision(info.path, {
            "/components": updated, "/panel/layout/center": lane,
        }, expected_sha256=info.semantic_sha256)
        self.assertEqual(len(changes), 2)
        self.assertEqual(info.path.read_bytes(), original_bytes)
        self.assertEqual(recipes.load(str(saved.path)).schema_version, 11)
        destination = Path(self.temp.name) / "studio.ricepack"
        receipt = creator_workspace.export_draft(saved, destination)
        # Without a custom PNG, the portable exporter intentionally uses v2.
        self.assertEqual(receipt["pack_version"], 2)
        self.assertFalse(receipt["applied"])
        self.assertTrue(destination.exists())


if __name__ == "__main__":
    unittest.main()
