"""Durable Wayland live-switch journal protects the next login after SIGKILL."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from macrice.cli import main as cli
from macrice.de import live_recovery, recipes, staging


class LiveRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        config = self.root / "config"
        config.mkdir(mode=0o700)
        configured = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)})
        configured.start()
        self.addCleanup(configured.stop)

    def pending(self):
        return recipes._private_recipe_dir(create=False) / live_recovery.FILE_NAME

    def test_no_journal_is_a_pure_read_only_noop(self):
        self.assertEqual(live_recovery.reconcile(),
                         {"status": "clean", "use_saved_selection": True})
        self.assertFalse((self.root / "config" / "ricebowl").exists())
        with mock.patch("builtins.print") as output:
            self.assertEqual(cli(["de", "creator-live-recovery", "--json"]), 0)
        self.assertFalse(json.loads(output.call_args.args[0])["pending"])

    def test_owner_is_live_and_second_session_cannot_recover_it(self):
        intent = live_recovery.begin("chrome", staging._hash("chrome"), None)
        self.assertEqual(self.pending().stat().st_mode & 0o777, 0o600)
        self.assertEqual(live_recovery.read(), intent)
        self.assertEqual(live_recovery.reconcile(),
                         {"status": "in_progress", "use_saved_selection": False})
        self.assertIsNone(recipes._selection_snapshot())
        self.assertTrue(self.pending().exists())
        with mock.patch("builtins.print") as output:
            self.assertEqual(cli(["de", "creator-live-recovery", "--json"]), 0)
        self.assertTrue(json.loads(output.call_args.args[0])["owner_running"])
        with self.assertRaisesRegex(live_recovery.LiveRecoveryError, "interrupted"):
            live_recovery.begin("chrome", staging._hash("chrome"), None)
        live_recovery.finish(intent)
        self.assertFalse(self.pending().exists())

    def test_crash_before_selection_write_only_clears_intent(self):
        live_recovery.begin("chrome", staging._hash("chrome"), None)
        with mock.patch.object(live_recovery, "_owner_running", return_value=False):
            report = live_recovery.reconcile()
        self.assertEqual(report["status"], "unchanged")
        self.assertTrue(report["use_saved_selection"])
        self.assertIsNone(recipes._selection_snapshot())
        self.assertFalse(self.pending().exists())

    def test_crash_after_completed_selection_write_restores_exact_old_state(self):
        # A previous pinned history must survive the interrupted live switch.
        staging.stage("chrome", staging._hash("chrome"))
        original = recipes._selection_snapshot()
        digest = staging._hash("classic")
        live_recovery.begin("classic", digest, original)
        recipes.change_selection("classic", expected_active="chrome",
                                 expected_semantic_sha256=digest)
        self.assertNotEqual(recipes._selection_snapshot(), original)
        with mock.patch.object(live_recovery, "_owner_running", return_value=False):
            report = live_recovery.reconcile()
        self.assertEqual(report, {"status": "restored", "use_saved_selection": True})
        self.assertEqual(recipes._selection_snapshot(), original)
        self.assertFalse(self.pending().exists())
        self.assertEqual(live_recovery.reconcile()["status"], "clean")

    def test_concurrent_reviewed_stage_wins_instead_of_forced_rollback(self):
        live_recovery.begin("chrome", staging._hash("chrome"), None)
        recipes.change_selection("chrome", expected_active="classic",
                                 expected_semantic_sha256=staging._hash("chrome"))
        # Another writer stages the prior look, changing the exact v2 state.
        staging.stage("classic", staging._hash("classic"), expected_active="chrome")
        intended = recipes._selection_snapshot()
        with mock.patch.object(live_recovery, "_owner_running", return_value=False):
            report = live_recovery.reconcile()
        self.assertEqual(report["status"], "superseded")
        self.assertEqual(recipes._selection_snapshot(), intended)
        self.assertFalse(self.pending().exists())

    def test_unsafe_selection_does_not_discard_the_recovery_record(self):
        live_recovery.begin("chrome", staging._hash("chrome"), None)
        recipes.change_selection("chrome", expected_active="classic",
                                 expected_semantic_sha256=staging._hash("chrome"))
        staging.stage("classic", staging._hash("classic"), expected_active="chrome")
        selected = recipes._private_recipe_dir(create=False) / ".active-recipe"
        payload = json.loads(selected.read_text())
        payload["active_sha256"] = "0" * 64
        selected.write_text(json.dumps(payload))
        with mock.patch.object(live_recovery, "_owner_running", return_value=False):
            report = live_recovery.reconcile()
        self.assertEqual(report, {"status": "unsafe", "use_saved_selection": False})
        self.assertTrue(self.pending().exists())

    def test_tampering_symlinks_and_oversize_fail_closed(self):
        live_recovery.begin("chrome", staging._hash("chrome"), None)
        path = self.pending()
        outside = self.root / "outside"
        outside.write_text("untouched")
        path.unlink()
        path.symlink_to(outside)
        self.assertEqual(live_recovery.reconcile()["status"], "unsafe")
        self.assertEqual(outside.read_text(), "untouched")
        self.assertTrue(path.is_symlink())
        path.unlink()
        path.write_text("{}")
        self.assertEqual(live_recovery.reconcile()["status"], "unsafe")
        path.write_bytes(b" " * (live_recovery.MAX_BYTES + 1))
        self.assertEqual(live_recovery.reconcile()["status"], "unsafe")
        path.chmod(0o644)
        self.assertEqual(live_recovery.reconcile()["status"], "unsafe")
        path.unlink()
        os.mkfifo(path, mode=0o600)
        self.assertEqual(live_recovery.reconcile()["status"], "unsafe")
        with mock.patch("builtins.print") as output:
            self.assertEqual(cli(["de", "creator-live-recovery", "--json"]), 2)
        self.assertEqual(json.loads(output.call_args.args[0])["error"]["code"],
                         "unsafe_journal")

    def test_stale_preflight_refuses_new_journal_and_cannot_clear_foreign_record(self):
        previous = recipes._selection_snapshot()
        staging.stage("chrome", staging._hash("chrome"))
        with self.assertRaisesRegex(live_recovery.LiveRecoveryError, "changed"):
            live_recovery.begin("classic", staging._hash("classic"), previous)
        self.assertFalse(self.pending().exists())
        correct_before = recipes._selection_snapshot()
        recorded = live_recovery.begin("classic", staging._hash("classic"), correct_before)
        with self.assertRaisesRegex(live_recovery.LiveRecoveryError, "changed"):
            live_recovery.finish({**recorded, "sha256": "0" * 64})
        self.assertTrue(self.pending().exists())


if __name__ == "__main__":
    unittest.main()
