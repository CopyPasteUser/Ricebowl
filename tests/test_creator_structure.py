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

    def test_transfer_between_lanes_is_atomic_and_preserves_order(self):
        before = copy.deepcopy(self.original)
        result = structure.transfer_layout(self.original, "start", (2,), "center", target_index=0)
        self.assertEqual(result["center"], [{"type": "widget", "id": "tasks"}])
        self.assertEqual(result["start"], before["panel"]["layout"]["start"][:2])
        self.assertEqual(self.original, before)
        proposal = copy.deepcopy(before)
        proposal["panel"]["layout"].update(result)
        self.assertEqual(recipes.parse(json.dumps(proposal).encode()).schema_version,
                         self.original["schema_version"])

    def test_transfer_nested_group_and_compact_are_independent(self):
        proposal = copy.deepcopy(self.original)
        proposal["panel"]["layout"]["start"] = structure.edit_layout(
            proposal, "start", (2,), "wrap")
        moved = structure.transfer_layout(proposal, "start", (2,), "center")
        self.assertEqual(moved["center"][0]["type"], "group")
        self.assertEqual(moved["center"][0]["children"],
                         [{"type": "widget", "id": "tasks"}])
        self.assertEqual(proposal["panel"]["layout"]["center"], [])
        proposal["panel"]["layout"].update(moved)
        compact = structure.transfer_layout(proposal, "center", (0,), "end", compact=True)
        self.assertEqual(compact["center"], [])
        self.assertEqual(compact["end"][0]["id"], "clock")
        self.assertEqual(compact["end"][1]["id"], "tasks")
        self.assertEqual(proposal["responsive"]["compact_layout"]["center"],
                         [{"type": "widget", "id": "tasks"}])
        proposal["responsive"]["compact_layout"].update(compact)
        recipes.parse(json.dumps(proposal).encode())

    def test_transfer_rejects_stale_and_ambiguous_paths_without_mutation(self):
        before = copy.deepcopy(self.original)
        cases = (
            ("start", (2,), "start", None),
            ("other", (2,), "center", None),
            ("start", (2,), "other", None),
            ("start", (), "center", None),
            ("start", (False,), "center", None),
            ("start", (100,), "center", None),
            ("start", (2,), "center", -1),
            ("start", (2,), "center", True),
            ("start", (2,), "center", 100),
        )
        for source, path, destination, index in cases:
            with self.subTest(source=source, path=path, destination=destination, index=index):
                with self.assertRaises(structure.StructureError):
                    structure.transfer_layout(
                        self.original, source, path, destination, target_index=index)
        self.assertEqual(self.original, before)

    def test_clone_wide_to_compact_preserves_full_tree_and_original(self):
        original = copy.deepcopy(self.original)
        clone = structure.clone_layout_mode(self.original)
        self.assertEqual(clone, original["panel"]["layout"])
        self.assertEqual(self.original, original)
        proposal = copy.deepcopy(original)
        proposal["responsive"]["compact_layout"] = clone
        recipes.parse(json.dumps(proposal).encode())
        clone["start"][0]["id"] = "modified-after-copy"
        self.assertEqual(self.original, original)

    def test_clone_compact_to_wide_preserves_responsive_independence(self):
        clone = structure.clone_layout_mode(self.original, from_compact=True)
        self.assertEqual(clone, self.original["responsive"]["compact_layout"])
        self.assertNotEqual(clone, self.original["panel"]["layout"])
        proposal = copy.deepcopy(self.original)
        proposal["panel"]["layout"] = clone
        recipes.parse(json.dumps(proposal).encode())
        self.assertEqual(self.original["panel"]["layout"]["end"][0]["type"], "group")

    def test_clone_layout_rejects_unsupported_modes_and_broken_source(self):
        original = copy.deepcopy(self.original)
        for invalid in (None, 0, "compact"):
            with self.subTest(invalid=invalid), self.assertRaises(structure.StructureError):
                structure.clone_layout_mode(self.original, from_compact=invalid)
        old = copy.deepcopy(self.original)
        old["schema_version"] = 9
        with self.assertRaises(structure.StructureError):
            structure.clone_layout_mode(old)
        broken = copy.deepcopy(self.original)
        broken["panel"]["layout"]["start"][0]["id"] = "unknown-widget"
        with self.assertRaises(structure.StructureError):
            structure.clone_layout_mode(broken)
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

    def test_cross_lane_move_saves_both_lanes_in_one_private_revision(self):
        info = creator_workspace.create_draft("heritage")
        original = info.path.read_bytes()
        manifest = review.review(str(info.path))["recipe"]
        moved = structure.transfer_layout(manifest, "start", (2,), "center")
        saved, changes = creator_workspace.save_revision(info.path, {
            "/panel/layout/start": moved["start"],
            "/panel/layout/center": moved["center"],
        }, expected_sha256=info.semantic_sha256)
        self.assertEqual(len(changes), 2)
        self.assertEqual(info.path.read_bytes(), original)
        persisted = review.review(str(saved.path))["recipe"]
        self.assertEqual(persisted["panel"]["layout"]["start"], moved["start"])
        self.assertEqual(persisted["panel"]["layout"]["center"], moved["center"])

    def test_responsive_mode_clone_is_one_private_revision(self):
        info = creator_workspace.create_draft("heritage")
        original = info.path.read_bytes()
        manifest = review.review(str(info.path))["recipe"]
        mirrored = structure.clone_layout_mode(manifest)
        saved, changes = creator_workspace.save_revision(info.path, {
            "/responsive/compact_layout": mirrored,
        }, expected_sha256=info.semantic_sha256)
        self.assertEqual(len(changes), 1)
        self.assertEqual(info.path.read_bytes(), original)
        result = review.review(str(saved.path))["recipe"]
        self.assertEqual(result["responsive"]["compact_layout"], mirrored)
        self.assertEqual(result["panel"]["layout"], manifest["panel"]["layout"])
        # Editing the cloned variant remains an ordinary, validated lane edit.
        newer_lane = structure.edit_layout(result, "center", (), "add",
                                           node={"type": "label", "text": "Compact"},
                                           compact=True)
        next_info, next_changes = creator_workspace.save_revision(saved.path, {
            "/responsive/compact_layout/center": newer_lane,
        }, expected_sha256=saved.semantic_sha256)
        self.assertEqual(len(next_changes), 1)
        self.assertEqual(review.review(str(next_info.path))["recipe"]
                         ["responsive"]["compact_layout"]["center"], newer_lane)

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
