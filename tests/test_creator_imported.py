"""A verified installed RicePack becomes an editable copy, never an active rice."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from macrice import creator_gui
from macrice.de import creator_workspace as workspace, pack, recipes, review


class CreatorImportedTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        state, config = self.root / "state", self.root / "config"
        state.mkdir(mode=0o700)
        config.mkdir(mode=0o700)
        environment = mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(state),
                                                   "XDG_CONFIG_HOME": str(config)})
        environment.start()
        self.addCleanup(environment.stop)

    def test_imported_ricepack_round_trip_preserves_installed_original(self):
        original = workspace.create_draft("orbit")
        archive = self.root / "original.ricepack"
        workspace.export_draft(original, archive)
        installed = pack.import_pack(archive)
        source = recipes._private_recipe_dir(create=False) / f"{installed['recipe_id']}.json"
        source_bytes = source.read_bytes()
        options = workspace.installed_editable()
        self.assertEqual(len(options), 1)
        self.assertEqual(options[0]["semantic_sha256"], installed["semantic_sha256"])

        copied = workspace.create_draft_from_installed(
            options[0]["id"], expected_sha256=options[0]["semantic_sha256"])
        self.assertNotEqual(copied.recipe_id, installed["recipe_id"])
        self.assertEqual(recipes.load(str(copied.path)).schema_version, 11)
        self.assertEqual(json.loads(copied.path.read_text())["panel"],
                         json.loads(source_bytes)["panel"])
        self.assertEqual(copied.path.stat().st_mode & 0o777, 0o600)
        updated, _ = workspace.save_revision(copied.path, {"/panel/height": 48},
                                              expected_sha256=copied.semantic_sha256)
        workspace.export_draft(updated, self.root / "edited.ricepack")
        self.assertTrue(pack.inspect_pack(self.root / "edited.ricepack")["valid"])
        self.assertEqual(source.read_bytes(), source_bytes)
        self.assertEqual(recipes.current_selection(), ("classic", None))

    def test_schema_twelve_luna_is_editable_without_dropping_distinct_layout(self):
        example = Path(__file__).resolve().parents[1] / "examples/wayland/xp-luna-columns.json"
        imported, source = recipes.import_recipe(example)
        original = source.read_bytes()
        option = workspace.installed_editable()[0]
        self.assertEqual(option["schema_version"], 12)
        copied = workspace.create_draft_from_installed(imported.recipe_id,
                            expected_sha256=option["semantic_sha256"])
        values = review.review(str(copied.path))["recipe"]
        self.assertEqual(values["menu"]["presentation"], "columns")
        self.assertIn("columns", creator_gui._choice_options(
            "/menu/presentation", ("tabs", "sidebar"), 12))
        self.assertNotIn("columns", creator_gui._choice_options(
            "/menu/presentation", ("tabs", "sidebar"), 11))
        self.assertEqual(source.read_bytes(), original)

    def test_stale_file_builtin_and_symlink_fail_before_any_draft_is_created(self):
        current = workspace.create_draft("heritage")
        recipes.import_recipe(current.path)
        option = workspace.installed_editable()[0]
        count = len(workspace.list_drafts())
        with self.assertRaisesRegex(workspace.WorkspaceError, "built-in"):
            workspace.create_draft_from_installed("classic", expected_sha256="0" * 64)
        with self.assertRaisesRegex(workspace.WorkspaceError, "changed"):
            workspace.create_draft_from_installed(option["id"],
                                                   expected_sha256="0" * 64)
        self.assertEqual(len(workspace.list_drafts()), count)
        source = recipes._private_recipe_dir(create=False) / f"{option['id']}.json"
        source.rename(source.with_suffix(".backup"))
        source.symlink_to(source.with_suffix(".backup"))
        with self.assertRaises(recipes.RecipeError):
            workspace.create_draft_from_installed(option["id"],
                                  expected_sha256=option["semantic_sha256"])
        self.assertEqual(len(workspace.list_drafts()), count)

    def test_confirmed_archive_change_fails_before_installing_anything(self):
        first = workspace.create_draft("orbit")
        changed = workspace.create_draft("heritage")
        archive = self.root / "selected.ricepack"
        workspace.export_draft(first, archive)
        reviewed = pack.inspect_pack(archive)
        replacement = self.root / "changed.ricepack"
        workspace.export_draft(changed, replacement)
        archive.write_bytes(replacement.read_bytes())
        with self.assertRaises(pack.PackError) as raised:
            pack.import_pack(archive, expected_manifest=reviewed["manifest"])
        self.assertEqual(raised.exception.code, "pack_changed")
        self.assertFalse(recipes._private_recipe_dir(create=False).exists())


if __name__ == "__main__":
    unittest.main()
