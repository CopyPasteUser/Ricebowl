"""Creator's guarded install/live handoff never silently mutates XFCE."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macrice.de import creator_activation as activation
from macrice.de import creator_workspace as workspace, recipes


class CreatorActivationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        state, config = root / "state", root / "config"
        state.mkdir(mode=0o700)
        config.mkdir(mode=0o700)
        patch = mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(state),
                                          "XDG_CONFIG_HOME": str(config)})
        patch.start()
        self.addCleanup(patch.stop)
        self.draft = workspace.create_draft("heritage")

    def test_install_is_explicit_private_idempotent_and_offline(self):
        with mock.patch.object(activation.live, "request") as request:
            plan = activation.inspect_install(self.draft)
            self.assertFalse(plan.already_installed)
            self.assertTrue(activation.install(plan))
            self.assertFalse(activation.install(plan))
            request.assert_not_called()
        self.assertEqual(recipes.load(self.draft.recipe_id).recipe_id, self.draft.recipe_id)
        self.assertEqual((recipes._private_recipe_dir(create=False) /
                          f"{self.draft.recipe_id}.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(recipes.current_selection(), ("classic", None))

    def test_reject_stale_draft_before_install(self):
        old = self.draft
        changed = old.path.read_text().replace("Heritage Modern draft", "Edited elsewhere")
        old.path.write_text(changed)
        with self.assertRaisesRegex(activation.ActivationError, "changed"):
            activation.install(activation.InstallPlan(old, False))
        self.assertFalse(recipes._private_recipe_dir(create=False).exists())

    def test_reject_mismatched_installed_id_without_overwriting(self):
        plan = activation.inspect_install(self.draft)
        self.assertTrue(activation.install(plan))
        installed = recipes._private_recipe_dir(create=False) / f"{self.draft.recipe_id}.json"
        original = installed.read_bytes()
        newer, _ = workspace.save_revision(self.draft.path, {"/panel/height": 40},
            expected_sha256=self.draft.semantic_sha256)
        with self.assertRaisesRegex(activation.ActivationError, "different version"):
            activation.inspect_install(newer)
        self.assertEqual(installed.read_bytes(), original)
        fork = workspace.fork_version(newer)
        self.assertTrue(activation.install(activation.inspect_install(fork)))
        self.assertEqual(recipes.load(fork.recipe_id).height, 40)
        self.assertEqual(installed.read_bytes(), original)

    def test_import_guards_exact_read_bytes_against_race(self):
        plan = activation.inspect_install(self.draft)
        original = recipes._read_import_source

        def changed(source):
            data = original(source)
            return data.replace(b"Heritage Modern draft", b"Changed during import")

        with mock.patch.object(recipes, "_read_import_source", side_effect=changed):
            with self.assertRaisesRegex(activation.ActivationError, "changed"):
                activation.install(plan)
        self.assertFalse((recipes._private_recipe_dir(create=False) /
                          f"{self.draft.recipe_id}.json").exists())

    def test_apply_requires_prior_install_and_live_supervisor(self):
        with mock.patch.object(activation.live, "request") as request:
            with self.assertRaisesRegex(activation.ActivationError, "Install"):
                activation.inspect_live(self.draft)
            request.assert_not_called()
        activation.install(activation.inspect_install(self.draft))
        with mock.patch.object(activation.live, "request",
                               side_effect=activation.live.LiveError("not Wayland")):
            with self.assertRaisesRegex(activation.ActivationError, "Wayland"):
                activation.inspect_live(self.draft)

    def test_apply_checks_expected_active_and_digest(self):
        activation.install(activation.inspect_install(self.draft))
        digest = self.draft.semantic_sha256
        status = {"version": 1, "ok": True, "active": "classic",
                  "next_login_persisted": True, "can_restore": False}
        applied = {"version": 1, "ok": True, "active": self.draft.recipe_id,
                   "semantic_sha256": digest, "changed": True}
        with mock.patch.object(activation.live, "request", side_effect=[status, applied]) as request:
            plan = activation.inspect_live(self.draft)
            self.assertEqual(plan.expected_active, "classic")
            self.assertEqual(activation.apply_live(plan)["active"], self.draft.recipe_id)
            request.assert_any_call("apply", recipe=self.draft.recipe_id,
                                    sha256=digest, expected="classic")

    def test_apply_rejects_concurrent_installed_edit(self):
        activation.install(activation.inspect_install(self.draft))
        with mock.patch.object(activation.live, "request", return_value={
            "version": 1, "ok": True, "active": "classic", "next_login_persisted": True,
        }) as request:
            plan = activation.inspect_live(self.draft)
            installed = recipes._private_recipe_dir(create=False) / f"{self.draft.recipe_id}.json"
            installed.write_text(installed.read_text().replace("Heritage Modern draft", "Changed"))
            with self.assertRaisesRegex(activation.ActivationError, "changed"):
                activation.apply_live(plan)
            request.assert_called_once_with("status")

    def test_live_conflict_and_uncertain_completion_are_not_reported_success(self):
        activation.install(activation.inspect_install(self.draft))
        plan = activation.LivePlan(self.draft, "classic", True)
        with mock.patch.object(activation.live, "request", return_value={
            "version": 1, "ok": False,
            "error": {"code": "selection_conflict", "message": "Active rice changed"},
        }):
            with self.assertRaisesRegex(activation.ActivationError, "changed"):
                activation.apply_live(plan)
        with mock.patch.object(activation.live, "request",
                               side_effect=activation.live.LiveError("timeout")):
            with self.assertRaisesRegex(activation.ActivationError, "uncertain"):
                activation.apply_live(plan)

    def test_restore_requires_explicit_previous_and_expected_active(self):
        with mock.patch.object(activation.live, "request", return_value={
            "version": 1, "ok": True, "active": "classic", "previous": None,
            "can_restore": False, "next_login_persisted": True,
        }):
            with self.assertRaisesRegex(activation.ActivationError, "no previous"):
                activation.inspect_restore()
        with mock.patch.object(activation.live, "request", side_effect=[
            {"version": 1, "ok": True, "active": "chrome", "previous": "classic",
             "can_restore": True, "next_login_persisted": True},
            {"version": 1, "ok": True, "active": "classic", "previous": "chrome"},
        ]) as request:
            plan = activation.inspect_restore()
            self.assertEqual(activation.restore_live(plan)["active"], "classic")
            request.assert_any_call("restore", recipe=None, sha256=None, expected="chrome")


if __name__ == "__main__":
    unittest.main()
