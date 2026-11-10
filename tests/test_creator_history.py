"""Creator version lineage survives restarts and fails closed on damaged receipts."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from macrice.cli import main as cli
from macrice.de import creator_history, creator_workspace as workspace


class CreatorHistoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        state = Path(temp.name) / "state"
        state.mkdir(mode=0o700)
        configured = patch.dict(os.environ, {"XDG_STATE_HOME": str(state)})
        configured.start()
        self.addCleanup(configured.stop)

    def test_parent_chain_survives_reopen_and_has_private_no_overwrite_receipts(self):
        original = workspace.create_draft("heritage")
        middle, _ = workspace.save_revision(original.path, {"/panel/height": 47},
                                            expected_sha256=original.semantic_sha256)
        latest, _ = workspace.save_revision(middle.path, {"/panel/height": 48},
                                            expected_sha256=middle.semantic_sha256)
        for info in (original, middle, latest):
            receipt = info.path.with_suffix(".history")
            self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
            self.assertEqual(creator_history.read(info.path, info.semantic_sha256)
                             ["target_semantic_sha256"], info.semantic_sha256)
        reopened = workspace.open_draft(latest.path)  # New Creator process, no in-memory stack.
        self.assertEqual([item.path for item in workspace.version_history(reopened)],
                         [latest.path, middle.path, original.path])
        self.assertEqual(workspace.previous_version(reopened).path, middle.path)
        self.assertIsNone(workspace.previous_version(original))
        self.assertEqual({row.path for row in workspace.list_drafts()},
                         {original.path, middle.path, latest.path})
        with self.assertRaises(creator_history.HistoryError):
            creator_history.write(latest.path, latest.semantic_sha256, kind="create")

    def test_fork_has_traceable_parent_and_keeps_the_original_untouched(self):
        original = workspace.create_draft("orbit")
        earlier = original.path.read_bytes()
        fork = workspace.fork_version(original)
        self.assertNotEqual(fork.recipe_id, original.recipe_id)
        self.assertEqual(workspace.previous_version(fork).path, original.path)
        self.assertEqual(original.path.read_bytes(), earlier)
        self.assertEqual(creator_history.read(fork.path, fork.semantic_sha256)["kind"], "fork")

    def test_older_safe_draft_filename_can_be_a_verified_parent(self):
        original = workspace.create_draft("classic")
        older = original.path.with_name("draft-legacy-export.json")
        original.path.rename(older)
        original.path.with_suffix(".history").rename(older.with_suffix(".history"))
        reopened = workspace.open_draft(older)
        saved, _ = workspace.save_revision(older, {"/panel/height": 46},
                                            expected_sha256=reopened.semantic_sha256)
        self.assertEqual(workspace.previous_version(saved).path, older)

    def test_modified_recipe_fingerprint_is_detected_and_hidden_from_recent_list(self):
        original = workspace.create_draft("heritage")
        data = json.loads(original.path.read_text())
        data["panel"]["height"] += 1
        original.path.write_text(json.dumps(data) + "\n")
        with self.assertRaisesRegex(workspace.WorkspaceError, "fingerprint"):
            workspace.open_draft(original.path)
        self.assertEqual(workspace.list_drafts(), [])

    def test_damaged_parent_cannot_be_used_as_recovery_target(self):
        original = workspace.create_draft("heritage")
        child, _ = workspace.save_revision(original.path, {"/panel/height": 46},
                                           expected_sha256=original.semantic_sha256)
        data = json.loads(original.path.read_text())
        data["panel"]["height"] += 1
        original.path.write_text(json.dumps(data) + "\n")
        self.assertEqual(workspace.open_draft(child.path).path, child.path)
        with self.assertRaises(workspace.WorkspaceError):
            workspace.previous_version(child)

    def test_corrupt_unsafe_or_symlinked_receipts_are_rejected(self):
        for failure in ("malformed", "traversal", "duplicate", "bad-kind", "permissions", "symlink"):
            with self.subTest(failure=failure):
                info = workspace.create_draft("classic")
                receipt = info.path.with_suffix(".history")
                data = json.loads(receipt.read_text())
                if failure == "malformed":
                    receipt.write_text("{broken")
                elif failure == "traversal":
                    data["kind"] = "save"
                    data["parent"] = {"filename": "../../outside", "semantic_sha256": "a" * 64}
                    receipt.write_text(json.dumps(data))
                elif failure == "duplicate":
                    receipt.write_text('{"history_version":1,"history_version":1}')
                elif failure == "bad-kind":
                    data["kind"] = []
                    receipt.write_text(json.dumps(data))
                elif failure == "permissions":
                    receipt.chmod(0o644)
                else:
                    receipt.unlink()
                    receipt.symlink_to(info.path)
                with self.assertRaises(workspace.WorkspaceError):
                    workspace.open_draft(info.path)

    def test_legacy_receiptless_draft_remains_readable_without_claimed_history(self):
        info = workspace.create_draft("classic")
        info.path.with_suffix(".history").unlink()
        reopened = workspace.open_draft(info.path)
        self.assertEqual(workspace.version_history(reopened), [reopened])
        self.assertIsNone(workspace.previous_version(reopened))

    def test_long_version_chain_is_bounded_without_losing_current_draft(self):
        original = workspace.create_draft("classic")
        current = original
        for number in range(creator_history.MAX_HISTORY_DEPTH + 2):
            current, _ = workspace.save_revision(
                current.path, {"/panel/height": 44 + number % 2},
                expected_sha256=current.semantic_sha256)
        chain = workspace.version_history(workspace.open_draft(current.path))
        self.assertEqual(len(chain), creator_history.MAX_HISTORY_DEPTH)
        self.assertEqual(chain[0].path, current.path)
        self.assertNotEqual(chain[-1].path, original.path)

    def test_receipt_parent_hash_cannot_be_forged_without_detection(self):
        original = workspace.create_draft("orbit")
        newer, _ = workspace.save_revision(original.path, {"/panel/height": 49},
                                           expected_sha256=original.semantic_sha256)
        record = newer.path.with_suffix(".history")
        payload = json.loads(record.read_text())
        payload["parent"]["semantic_sha256"] = "0" * 64
        record.write_text(json.dumps(payload) + "\n")
        self.assertEqual(workspace.open_draft(newer.path).path, newer.path)
        with self.assertRaisesRegex(workspace.WorkspaceError, "modified"):
            workspace.version_history(newer)

    def test_cli_reports_exact_read_only_history_and_structured_damage(self):
        original = workspace.create_draft("classic")
        newer, _ = workspace.save_revision(original.path, {"/panel/height": 46},
                                           expected_sha256=original.semantic_sha256)
        with patch("builtins.print") as output:
            result = cli(["de", "creator-history", "--recipe", str(newer.path), "--json"])
        self.assertEqual(result, 0)
        payload = json.loads(output.call_args.args[0])
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["applied"])
        self.assertEqual([item["semantic_sha256"] for item in payload["versions"]],
                         [newer.semantic_sha256, original.semantic_sha256])
        with patch("sys.stderr"):
            self.assertEqual(cli(["de", "creator-history", "--recipe", "classic"]), 1)
        original.path.with_suffix(".history").chmod(0o644)
        with patch("builtins.print") as output:
            result = cli(["de", "creator-history", "--recipe", str(newer.path), "--json"])
        self.assertEqual(result, 2)
        payload = json.loads(output.call_args.args[0])
        self.assertEqual(payload["error"]["code"], "unverified_history")


if __name__ == "__main__":
    unittest.main()
