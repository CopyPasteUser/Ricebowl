"""Creator desktop authoring must remain offline, private and non-destructive."""

import json
import os
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from macrice.de import creator_workspace as workspace, drafts, recipes, review
from macrice import creator_gui


class CreatorWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / "state"
        self.state.mkdir(mode=0o700)
        environ = patch.dict(os.environ, {"XDG_STATE_HOME": str(self.state)})
        environ.start()
        self.addCleanup(environ.stop)

    def test_create_two_real_schema_ten_templates_and_list_private(self):
        self.assertEqual(workspace.list_drafts(), [])
        a = workspace.create_draft("heritage")
        b = workspace.create_draft("orbit")
        self.assertNotEqual(a.recipe_id, b.recipe_id)
        self.assertTrue(a.path.is_file())
        self.assertEqual(a.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(recipes.load(str(a.path)).schema_version, 11)
        self.assertEqual(recipes.load(str(b.path)).menu_presentation, "sidebar")
        self.assertEqual({x.path for x in workspace.list_drafts()}, {a.path, b.path})

    def test_classic_and_chrome_templates_use_same_validated_schema(self):
        for template in ("classic", "chrome"):
            with self.subTest(template=template):
                info = workspace.create_draft(template)
                self.assertEqual(recipes.load(str(info.path)).schema_version, 11)

    def test_versioned_change_preserves_original_and_supports_undo(self):
        original = workspace.create_draft("heritage")
        before = original.path.read_bytes()
        revised, changes = workspace.save_revision(original.path, {
            "/panel/position": "top", "/appearance/font_scale": 2,
            "/colors/active": "#112233", "/name": "New shell",
        }, expected_sha256=original.semantic_sha256)
        self.assertEqual(len(changes), 4)
        self.assertEqual(original.path.read_bytes(), before)
        self.assertEqual(original.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(review.review(str(revised.path), str(original.path))
                         ["comparison"]["changed"], True)
        self.assertEqual(revised.name, "New shell")
        self.assertEqual(recipes.load(str(revised.path)).position, "top")
        self.assertEqual(len(workspace.list_drafts()), 2)
        self.assertEqual(list(original.path.parent.glob(".creator-edit-*")), [])

    def test_preflight_review_matches_pinned_private_save(self):
        original = workspace.create_draft("heritage")
        original_bytes = original.path.read_bytes()
        proposed = {"/panel/height": 47, "/name": "Preflight desktop"}
        preflight = workspace.preview_revision(original.path, proposed,
                                               expected_sha256=original.semantic_sha256)
        self.assertTrue(preflight["validated"])
        self.assertFalse(preflight["created"])
        self.assertEqual(len(workspace.list_drafts()), 1)
        self.assertFalse(list(original.path.parent.glob(".creator-edit-*")))
        self.assertIn("/panel/height", creator_gui._revision_review_text(preflight))
        self.assertIn(preflight["draft_semantic_sha256"],
                      creator_gui._revision_review_text(preflight))
        saved, changes = workspace.save_revision(
            original.path, proposed, expected_sha256=preflight["source_semantic_sha256"],
            expected_draft_sha256=preflight["draft_semantic_sha256"])
        self.assertEqual(changes, preflight["changes"])
        self.assertEqual(saved.semantic_sha256, preflight["draft_semantic_sha256"])
        self.assertEqual(original.path.read_bytes(), original_bytes)
        self.assertEqual(len(workspace.list_drafts()), 2)
        self.assertFalse(list(original.path.parent.glob(".creator-edit-*")))

    def test_reviewed_proposal_change_or_stale_source_fails_without_output(self):
        original = workspace.create_draft("orbit")
        preflight = workspace.preview_revision(
            original.path, {"/panel/height": 47}, expected_sha256=original.semantic_sha256)
        with self.assertRaises(drafts.DraftError) as mismatch:
            workspace.save_revision(
                original.path, {"/panel/height": 48},
                expected_sha256=preflight["source_semantic_sha256"],
                expected_draft_sha256=preflight["draft_semantic_sha256"])
        self.assertEqual(mismatch.exception.code, "draft_changed")
        data = json.loads(original.path.read_text())
        data["panel"]["height"] += 1
        original.path.write_text(json.dumps(data) + "\n")
        # The underlying recipe remains owner-private and valid; its fingerprint changed.
        with self.assertRaisesRegex(workspace.WorkspaceError, "fingerprint"):
            workspace.open_draft(original.path)
        with self.assertRaisesRegex(workspace.WorkspaceError, "fingerprint"):
            workspace.save_revision(
                original.path, {"/panel/height": 47},
                expected_sha256=preflight["source_semantic_sha256"],
                expected_draft_sha256=preflight["draft_semantic_sha256"])
        self.assertEqual(workspace.list_drafts(), [])  # Invalid receipt hides the changed draft.
        self.assertTrue(original.path.is_file())
        self.assertFalse(list(original.path.parent.glob(".creator-edit-*")))

    def test_invalid_preflight_fails_without_creating_private_version(self):
        original = workspace.create_draft("heritage")
        for proposed in ({"/panel/height": -1}, {"/panel/position": "left"},
                         {"/unsafe/exec": "oops"}):
            with self.subTest(proposed=proposed), self.assertRaises(
                    (drafts.DraftError, workspace.WorkspaceError)):
                workspace.preview_revision(original.path, proposed,
                                           expected_sha256=original.semantic_sha256)
        self.assertEqual(len(workspace.list_drafts()), 1)
        self.assertFalse(list(original.path.parent.glob(".creator-edit-*")))

    def test_conflict_fails_closed_and_preserves_previous_versions(self):
        original = workspace.create_draft("orbit")
        revised, _ = workspace.save_revision(original.path, {"/panel/height": 52},
                                             expected_sha256=original.semantic_sha256)
        with self.assertRaisesRegex(workspace.WorkspaceError, "Reload"):
            workspace.save_revision(revised.path, {"/panel/height": 55},
                                    expected_sha256=original.semantic_sha256)
        self.assertEqual(len(workspace.list_drafts()), 2)

    def test_fork_saved_version_preserves_layout_but_uses_new_rice_id(self):
        original = workspace.create_draft("orbit")
        revised, _ = workspace.save_revision(original.path, {"/panel/height": 49},
                                              expected_sha256=original.semantic_sha256)
        source = revised.path.read_bytes()
        fork = workspace.fork_version(revised)
        self.assertNotEqual(fork.recipe_id, revised.recipe_id)
        self.assertEqual(recipes.load(str(fork.path)).height, 49)
        self.assertEqual(recipes.load(str(fork.path)).layout,
                         recipes.load(str(revised.path)).layout)
        self.assertEqual(revised.path.read_bytes(), source)
        self.assertEqual(fork.path.stat().st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(workspace.WorkspaceError, "Reopen"):
            workspace.fork_version(replace(original, semantic_sha256="0" * 64))

    def test_invalid_or_oversized_changes_publish_nothing(self):
        info = workspace.create_draft("heritage")
        for changes in ({"/unsafe/exec": "oops"}, {"/panel/height": 1},
                        {"/panel/position": "left"}, {}):
            with self.subTest(changes=changes), self.assertRaises((drafts.DraftError,
                                                                    workspace.WorkspaceError)):
                workspace.save_revision(info.path, changes, expected_sha256=info.semantic_sha256)
        self.assertEqual(len(workspace.list_drafts()), 1)

    def test_panel_lane_reorder_is_real_and_duplicates_fail(self):
        info = workspace.create_draft("heritage")
        original = review.review(str(info.path))["recipe"]["panel"]["layout"]["start"]
        revised, changes = workspace.save_revision(info.path, {
            "/panel/layout/start": [original[1], original[0], original[2]],
        }, expected_sha256=info.semantic_sha256)
        self.assertEqual(changes[0]["path"], "/panel/layout/start")
        self.assertNotEqual(recipes.load(str(revised.path)).layout,
                            recipes.load(str(info.path)).layout)
        with self.assertRaises(drafts.DraftError):
            workspace.save_revision(info.path, {
                "/panel/layout/start": original + [{"type": "widget", "id": "launcher"}],
            }, expected_sha256=info.semantic_sha256)
        self.assertEqual(len(workspace.list_drafts()), 2)

    def test_gui_uses_semantic_defaults_and_real_allowlisted_paths(self):
        info = workspace.create_draft("heritage")
        manifest = review.review(str(info.path))["recipe"]
        self.assertEqual(creator_gui._get_field(manifest, "/menu/presentation"), "tabs")
        paths = [field[0] for _group, fields in creator_gui.FIELDS for field in fields]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertTrue(set(paths) <= drafts.EDITABLE_PATHS)
        self.assertIn("launcher", creator_gui._node_label({"type": "widget", "id": "launcher"}))

    def test_export_ricepack_never_applies_or_overwrites(self):
        info = workspace.create_draft("heritage")
        destination = Path(self.temp.name) / "export.ricepack"
        result = workspace.export_draft(info, destination)
        self.assertTrue(result["ok"])
        self.assertFalse(result["applied"])
        with self.assertRaises(Exception):
            workspace.export_draft(info, destination)
        self.assertTrue(destination.is_file())

    def test_reject_symlinked_workspace_and_unsafe_permissions(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir(mode=0o700)
        link = self.state / "ricebowl"
        link.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(workspace.WorkspaceError, "unsafe"):
            workspace.create_draft("heritage")
        link.unlink()
        info = workspace.create_draft("heritage")
        info.path.chmod(0o644)
        self.assertNotIn(info.path, {row.path for row in workspace.list_drafts()})


if __name__ == "__main__":
    unittest.main()
