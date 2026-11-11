"""A verified installed RicePack becomes an editable copy, never an active rice."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from macrice import creator_gui
from macrice.de import creator_assets, creator_workspace as workspace, pack, recipes, review


class CreatorImportedTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        state, config, data = self.root / "state", self.root / "config", self.root / "data"
        state.mkdir(mode=0o700)
        config.mkdir(mode=0o700)
        data.mkdir(mode=0o700)
        environment = mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(state),
                                                   "XDG_CONFIG_HOME": str(config),
                                                   "XDG_DATA_HOME": str(data)})
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

    def test_imported_attribution_survives_private_edit_and_export(self):
        original = workspace.create_draft("heritage")
        declaration = {
            "author": "Original artist", "license": "CC-BY-4.0",
            "origin": "original", "source_reference": "offline artwork",
            "wallpaper_provenance": {
                "author": "Wallpaper artist", "license": "CC-BY-4.0",
                "origin": "adapted", "source_reference": "credited photograph",
            },
        }
        metadata = self.root / "attribution.json"
        metadata.write_text(json.dumps(declaration))
        archive = self.root / "attributed.ricepack"
        initial = pack.export_pack(str(original.path), archive, metadata=metadata)["manifest"]
        imported = pack.import_pack(archive)
        copy = workspace.create_draft_from_installed(imported["recipe_id"],
                            expected_sha256=imported["semantic_sha256"])
        edited, _ = workspace.save_revision(copy.path, {"/panel/height": 48},
                                            expected_sha256=copy.semantic_sha256)
        # A derivative must remain portable even if its installed source has
        # since been uninstalled: credit belongs to its verified root receipt.
        source = recipes._private_recipe_dir(create=False) / f"{imported['recipe_id']}.json"
        source.unlink()
        source.with_suffix(".ricepack-provenance").unlink()
        outgoing = self.root / "edited-with-credit.ricepack"
        delivered = workspace.export_draft(workspace.open_draft(edited.path), outgoing)["manifest"]
        self.assertEqual(delivered["provenance"], initial["provenance"])
        self.assertEqual(delivered["asset_manifest"]["wallpaper"]["provenance"],
                         initial["asset_manifest"]["wallpaper"]["provenance"])
        self.assertNotEqual(delivered["recipe"]["id"], initial["recipe"]["id"])
        self.assertEqual(recipes.current_selection(), ("classic", None))
        forked = workspace.fork_version(edited)
        inherited = workspace.export_draft(forked, self.root / "forked.ricepack")["manifest"]
        self.assertEqual(inherited["provenance"], initial["provenance"])
        self.assertEqual(inherited["asset_manifest"]["wallpaper"]["provenance"],
                         initial["asset_manifest"]["wallpaper"]["provenance"])

        # Replacing the wallpaper must not reattribute the new artist's image
        # to the original wallpaper author, while rice-level credit remains.
        image = (Path(__file__).resolve().parents[1] / "assets" / "themes" /
                 "RiceHub-Ten-Dark" / "xfwm4" / "maximize-active.png")
        new_credit = {"author": "Replacement artist", "license": "MIT",
                      "origin": "original", "source_reference": "local PNG"}
        replacement = creator_assets.import_wallpaper(
            image, label="Alternate image", provenance=new_credit)
        revised, _ = workspace.save_revision(forked.path,
                           {"/desktop/wallpaper": replacement.asset_id},
                           expected_sha256=forked.semantic_sha256)
        revised_manifest = workspace.export_draft(revised, self.root / "wallpaper-swapped.ricepack")[
            "manifest"]
        self.assertEqual(revised_manifest["provenance"], initial["provenance"])
        self.assertEqual(revised_manifest["asset_manifest"]["wallpaper"]["provenance"],
                         new_credit)

        # No unreviewed license may enter a trusted immutable history receipt.
        root_receipt = copy.path.with_suffix(".history")
        tampered = json.loads(root_receipt.read_text())
        tampered["attribution"]["rice"]["license"] = "exec:sh"
        root_receipt.write_text(json.dumps(tampered))
        with self.assertRaises(workspace.WorkspaceError):
            workspace.export_draft(revised, self.root / "untrusted.ricepack")
        self.assertFalse((self.root / "untrusted.ricepack").exists())


if __name__ == "__main__":
    unittest.main()
