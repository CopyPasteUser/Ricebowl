"""Content-addressed Creator source copies must be reproducible and tamper-evident."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from macrice.cli import main as cli
from macrice.de import creator_snapshot as snapshots, creator_workspace as workspace
from macrice.de import drafts, recipes, review


class CreatorSnapshotTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        state = self.root / "state"
        state.mkdir(mode=0o700)
        configured = patch.dict(os.environ, {"XDG_STATE_HOME": str(state)})
        configured.start()
        self.addCleanup(configured.stop)

    def test_repeatable_read_only_snapshot_preserves_source_semantics(self):
        draft = workspace.create_draft("heritage")
        original = draft.path.read_bytes()
        first = snapshots.create(str(draft.path))
        self.assertTrue(first["created"])
        self.assertFalse(first["applied"])
        destination = Path(first["path"])
        self.assertEqual(destination.stat().st_mode & 0o777, 0o400)
        self.assertEqual(destination.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(hashlib.sha256(destination.read_bytes()).hexdigest(), first["content_sha256"])
        self.assertEqual(review.review(str(destination))["summary"]["semantic_sha256"],
                         draft.semantic_sha256)
        modified_ns = destination.stat().st_mtime_ns
        second = snapshots.create(str(draft.path))
        self.assertFalse(second["created"])
        self.assertEqual(second["path"], first["path"])
        self.assertEqual(destination.stat().st_mtime_ns, modified_ns)
        self.assertEqual(draft.path.read_bytes(), original)

    def test_edited_source_creates_new_snapshot_without_touching_old_one(self):
        original = workspace.create_draft("classic")
        first = snapshots.create(str(original.path))
        revised, _ = workspace.save_revision(original.path, {"/panel/height": 45},
                                             expected_sha256=original.semantic_sha256)
        second = snapshots.create(str(revised.path))
        self.assertNotEqual(first["content_sha256"], second["content_sha256"])
        self.assertEqual(recipes.load(first["path"]).height,
                         recipes.load(str(original.path)).height)
        self.assertEqual(recipes.load(second["path"]).height, 45)

    def test_byte_change_even_whitespace_fails_any_recipe_load_and_reuse(self):
        receipt = snapshots.create("classic")
        destination = Path(receipt["path"])
        destination.chmod(0o600)
        destination.write_bytes(destination.read_bytes() + b" ")
        destination.chmod(0o400)
        with self.assertRaises(recipes.RecipeFingerprintMismatch):
            recipes.load(str(destination))
        with self.assertRaises(snapshots.SnapshotError):
            snapshots.create("classic")
        edit = self.root / "edit.json"
        edit.write_text(json.dumps({"edit_version": 1, "operations": [
            {"op": "set", "path": "/panel/height", "value": 49}]}))
        output = self.root / "proposed.json"
        with self.assertRaises(drafts.DraftError):
            drafts.create_edit(recipe_token=str(destination), edit_source=edit,
                               destination=output)
        self.assertFalse(output.exists())

    def test_symlinks_permissions_and_invalid_sources_are_rejected(self):
        receipt = snapshots.create("classic")
        destination = Path(receipt["path"])
        destination.chmod(0o600)
        with self.assertRaisesRegex(snapshots.SnapshotError, "read-only"):
            snapshots.create("classic")
        destination.chmod(0o400)
        external = self.root / "outside.json"
        external.write_text(json.dumps({"bad": True}))
        destination.unlink()
        destination.symlink_to(external)
        with self.assertRaises(snapshots.SnapshotError):
            snapshots.create("classic")
        self.assertEqual(json.loads(external.read_text()), {"bad": True})
        with self.assertRaises(snapshots.SnapshotError):
            snapshots.create("missing-recipe-name")

    def test_draft_preflight_and_publish_can_use_pinned_snapshot_without_side_effects(self):
        original = workspace.create_draft("classic")
        frozen = snapshots.create(str(original.path))
        patch_file = self.root / "changes.json"
        patch_file.write_text(json.dumps({"edit_version": 1, "operations": [
            {"op": "set", "path": "/panel/height", "value": 48}]}))
        output = self.root / "proposed.json"
        checked = drafts.check_edit(recipe_token=frozen["path"], edit_source=patch_file,
                                    expected_sha256=frozen["source_semantic_sha256"])
        self.assertTrue(checked["validated"])
        self.assertFalse(output.exists())
        created = drafts.create_edit(recipe_token=frozen["path"], edit_source=patch_file,
                                     destination=output,
                                     expected_sha256=checked["source_semantic_sha256"],
                                     expected_draft_sha256=checked["draft_semantic_sha256"])
        self.assertTrue(created["created"])
        self.assertEqual(recipes.load(str(output)).height, 48)
        self.assertEqual(Path(frozen["path"]).stat().st_mode & 0o777, 0o400)

    def test_cli_snapshot_reports_private_copy_and_structured_failures(self):
        with patch("builtins.print") as output:
            self.assertEqual(cli(["de", "creator-snapshot", "--recipe", "classic", "--json"]), 0)
        created = json.loads(output.call_args.args[0])
        self.assertTrue(created["created"])
        self.assertFalse(created["applied"])
        self.assertEqual(recipes.load(created["path"]).recipe_id, "classic")
        with patch("builtins.print") as output:
            self.assertEqual(cli(["de", "creator-snapshot", "--recipe", "classic", "--json"]), 0)
        self.assertFalse(json.loads(output.call_args.args[0])["created"])
        with patch("sys.stderr"):
            self.assertEqual(cli(["de", "creator-snapshot", "--recipe", "classic",
                                  "--output", str(self.root / "nope.json")]), 1)
        with patch("builtins.print") as output:
            self.assertEqual(cli(["de", "creator-snapshot", "--recipe", "unknown", "--json"]), 2)
        self.assertEqual(json.loads(output.call_args.args[0])["error"]["code"],
                         "snapshot_unavailable")

    def test_reject_symlinked_snapshot_storage(self):
        folder = snapshots._private_directory()
        external = self.root / "external"
        external.mkdir(mode=0o700)
        folder.rmdir()
        folder.symlink_to(external, target_is_directory=True)
        with self.assertRaises(snapshots.SnapshotError):
            snapshots.create("classic")


if __name__ == "__main__":
    unittest.main()
