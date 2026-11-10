"""Crash-interrupted Creator authoring never destroys the last verified draft."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from macrice.cli import main as cli
from macrice.de import creator_history, creator_recovery, creator_workspace as workspace
from macrice.de import recipes


class CreatorRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        state = self.root / "state"
        state.mkdir(mode=0o700)
        configured = patch.dict(os.environ, {"XDG_STATE_HOME": str(state)})
        configured.start()
        self.addCleanup(configured.stop)

    def test_explicit_restore_from_healthy_child_is_new_verified_version(self):
        first = workspace.create_draft("classic")
        changed, _ = workspace.save_revision(first.path, {"/panel/height": 47},
                                             expected_sha256=first.semantic_sha256)
        previous_content = first.path.read_bytes()
        changed_content = changed.path.read_bytes()
        report = creator_recovery.inspect(changed.path)
        self.assertEqual(report["source_status"], "verified")
        self.assertEqual(report["parent_semantic_sha256"], first.semantic_sha256)
        restored = creator_recovery.recover(changed.path,
                                             expected_parent_sha256=first.semantic_sha256)
        self.assertTrue(restored["created"])
        self.assertFalse(restored["applied"])
        recovered = workspace.open_draft(Path(restored["path"]))
        self.assertEqual(recovered.semantic_sha256, first.semantic_sha256)
        self.assertEqual(workspace.previous_version(recovered).path, first.path)
        self.assertEqual(creator_history.read(recovered.path, recovered.semantic_sha256)
                         ["kind"], "recover")
        self.assertEqual(first.path.read_bytes(), previous_content)
        self.assertEqual(changed.path.read_bytes(), changed_content)
        self.assertEqual(len(workspace.list_drafts()), 3)

    def test_empty_scan_does_not_create_any_workspace_directories(self):
        self.assertEqual(creator_recovery.scan()["unresolved"], [])
        self.assertFalse((Path(os.environ["XDG_STATE_HOME"]) / "ricebowl").exists())

    def test_crash_between_intent_and_recipe_leaves_no_visible_unverified_draft(self):
        parent = workspace.create_draft("heritage")
        original_writer = recipes._write_private_new

        def interrupted(target, payload, **kwargs):
            if target.name.startswith("draft-") and target.suffix == ".json":
                raise OSError("simulated power failure before final recipe link")
            return original_writer(target, payload, **kwargs)

        with patch.object(recipes, "_write_private_new", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "simulated power failure"):
                workspace.save_revision(parent.path, {"/panel/height": 48},
                                        expected_sha256=parent.semantic_sha256)
        self.assertEqual([info.path for info in workspace.list_drafts()], [parent.path])
        unfinished = [entry.with_suffix(".json") for entry in parent.path.parent.glob(
            "draft-*.history") if not entry.with_suffix(".json").exists()]
        self.assertEqual(len(unfinished), 1)
        discovered = creator_recovery.scan()
        self.assertEqual(discovered["unresolved"][0]["source"], str(unfinished[0]))
        self.assertEqual(discovered["unresolved"][0]["source_status"], "missing")
        self.assertEqual(discovered["scanned_receipts"], 2)
        report = creator_recovery.inspect(unfinished[0])
        self.assertEqual(report["source_status"], "missing")
        restored = creator_recovery.recover(unfinished[0],
                                             expected_parent_sha256=parent.semantic_sha256)
        self.assertEqual(workspace.open_draft(Path(restored["path"])).semantic_sha256,
                         parent.semantic_sha256)
        self.assertFalse(unfinished[0].exists())
        self.assertTrue(unfinished[0].with_suffix(".history").exists())
        self.assertEqual(creator_recovery.scan()["unresolved"][0]["source"],
                         str(unfinished[0]))

    def test_damage_in_newer_recipe_can_be_skipped_but_not_overwritten(self):
        parent = workspace.create_draft("classic")
        child, _ = workspace.save_revision(parent.path, {"/panel/height": 46},
                                           expected_sha256=parent.semantic_sha256)
        data = json.loads(child.path.read_text())
        data["panel"]["height"] = 49
        child.path.write_text(json.dumps(data) + "\n")
        self.assertEqual(creator_recovery.inspect(child.path)["source_status"], "unverified")
        with self.assertRaises(workspace.WorkspaceError):
            workspace.open_draft(child.path)
        recovered = creator_recovery.recover(child.path,
                                              expected_parent_sha256=parent.semantic_sha256)
        self.assertEqual(recipes.load(recovered["path"]).height,
                         recipes.load(str(parent.path)).height)
        self.assertEqual(recipes.load(str(child.path)).height, 49)

    def test_multiple_damaged_versions_follow_receipts_to_last_verified_ancestor(self):
        root = workspace.create_draft("classic")
        middle, _ = workspace.save_revision(root.path, {"/panel/height": 46},
                                            expected_sha256=root.semantic_sha256)
        newest, _ = workspace.save_revision(middle.path, {"/panel/height": 48},
                                            expected_sha256=middle.semantic_sha256)
        for broken in (middle, newest):
            broken.path.write_text("{not a recipe}")
        report = creator_recovery.inspect(newest.path)
        self.assertEqual(report["source_status"], "unverified")
        self.assertEqual(report["parent"], str(root.path))
        self.assertEqual(report["skipped_unverified_versions"], 1)
        restored = creator_recovery.recover(newest.path,
                                             expected_parent_sha256=root.semantic_sha256)
        self.assertEqual(workspace.open_draft(Path(restored["path"])).semantic_sha256,
                         root.semantic_sha256)
        self.assertEqual(workspace.previous_version(workspace.open_draft(
            Path(restored["path"]))).path, root.path)

    def test_stale_hash_unverified_parent_and_invalid_receipt_fail_closed(self):
        parent = workspace.create_draft("classic")
        child, _ = workspace.save_revision(parent.path, {"/panel/height": 47},
                                           expected_sha256=parent.semantic_sha256)
        baseline = {info.path for info in workspace.list_drafts()}
        with self.assertRaisesRegex(creator_recovery.RecoveryError, "parent changed"):
            creator_recovery.recover(child.path, expected_parent_sha256="0" * 64)
        self.assertEqual({info.path for info in workspace.list_drafts()}, baseline)
        data = json.loads(parent.path.read_text())
        data["panel"]["height"] = 50
        parent.path.write_text(json.dumps(data) + "\n")
        with self.assertRaises(creator_recovery.RecoveryError):
            creator_recovery.inspect(child.path)
        with self.assertRaises(creator_recovery.RecoveryError):
            creator_recovery.recover(child.path,
                                      expected_parent_sha256=parent.semantic_sha256)
        # A modified history sidecar cannot redirect recovery into a random file.
        child.path.with_suffix(".history").write_text('{"bad":true}')
        with self.assertRaises(creator_recovery.RecoveryError):
            creator_recovery.inspect(child.path)

    def test_legacy_root_and_symlinked_or_external_paths_are_not_recovery_sources(self):
        parent = workspace.create_draft("orbit")
        with self.assertRaisesRegex(creator_recovery.RecoveryError, "no recorded parent"):
            creator_recovery.inspect(parent.path)
        parent.path.with_suffix(".history").unlink()
        with self.assertRaisesRegex(creator_recovery.RecoveryError, "legacy"):
            creator_recovery.inspect(parent.path)
        outside = self.root / "external.json"
        outside.write_text("{}")
        with self.assertRaises(creator_recovery.RecoveryError):
            creator_recovery.inspect(outside)
        with self.assertRaises(creator_recovery.RecoveryError):
            creator_recovery.inspect(parent.path.parent / ".." / parent.path.name)

    def test_scan_reports_unsafe_receipts_without_following_or_removing_them(self):
        parent = workspace.create_draft("classic")
        child, _ = workspace.save_revision(parent.path, {"/panel/height": 46},
                                           expected_sha256=parent.semantic_sha256)
        outside = self.root / "outside.txt"
        outside.write_text("untouched")
        receipt = child.path.with_suffix(".history")
        receipt.unlink()
        receipt.symlink_to(outside)
        unresolved = creator_recovery.scan()["unresolved"]
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]["source"], str(child.path))
        self.assertFalse(unresolved[0]["recoverable"])
        self.assertEqual(outside.read_text(), "untouched")
        self.assertTrue(receipt.is_symlink())

    def test_large_recovery_scan_has_a_strict_intent_limit(self):
        parent = workspace.create_draft("classic")
        for index in range(creator_recovery.MAX_RECOVERY_SCAN + 1):
            (parent.path.parent / f"draft-scantest-{index:04d}.history").write_text("{}")
        listing = creator_recovery.scan()
        self.assertTrue(listing["truncated"])
        self.assertEqual(listing["scanned_receipts"], creator_recovery.MAX_RECOVERY_SCAN)
        self.assertLessEqual(len(listing["unresolved"]), creator_recovery.MAX_RECOVERY_SCAN)

    def test_failed_intent_write_never_publishes_the_recipe(self):
        first = workspace.create_draft("classic")
        original = {item.name for item in first.path.parent.iterdir()}
        with patch.object(creator_history, "write", side_effect=creator_history.HistoryError(
                "intentionally blocked receipt")):
            with self.assertRaisesRegex(workspace.WorkspaceError, "blocked receipt"):
                workspace.save_revision(first.path, {"/panel/height": 46},
                                        expected_sha256=first.semantic_sha256)
        self.assertEqual({item.name for item in first.path.parent.iterdir()}, original)

    def test_cli_preflight_and_guarded_recovery_have_no_live_side_effect(self):
        first = workspace.create_draft("classic")
        later, _ = workspace.save_revision(first.path, {"/panel/height": 48},
                                           expected_sha256=first.semantic_sha256)
        with patch("builtins.print") as out:
            self.assertEqual(cli(["de", "creator-recovery", "--json"]), 0)
        self.assertEqual(json.loads(out.call_args.args[0])["unresolved"], [])
        with patch("builtins.print") as out:
            self.assertEqual(cli(["de", "creator-recovery", "--recipe", str(later.path),
                                  "--json"]), 0)
        status = json.loads(out.call_args.args[0])
        self.assertEqual(status["parent_semantic_sha256"], first.semantic_sha256)
        self.assertEqual(len(workspace.list_drafts()), 2)
        with patch("sys.stderr"):
            self.assertEqual(cli(["de", "creator-recovery", "--recipe", str(later.path),
                                  "--expect-sha256", first.semantic_sha256]), 1)
            self.assertEqual(cli(["de", "creator-recover", "--recipe", str(later.path)]), 1)
        with patch("builtins.print") as out:
            self.assertEqual(cli(["de", "creator-recover", "--recipe", str(later.path),
                                  "--expect-sha256", "0" * 64, "--json"]), 2)
        self.assertEqual(json.loads(out.call_args.args[0])["error"]["code"],
                         "recovery_unavailable")
        with patch("builtins.print") as out:
            self.assertEqual(cli(["de", "creator-recover", "--recipe", str(later.path),
                                  "--expect-sha256", first.semantic_sha256, "--json"]), 0)
        created = json.loads(out.call_args.args[0])
        self.assertTrue(created["created"])
        self.assertEqual(len(workspace.list_drafts()), 3)


if __name__ == "__main__":
    unittest.main()
