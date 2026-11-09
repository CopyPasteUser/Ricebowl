"""Creator 0.3 uses existing safe wallpaper assets and portable attribution."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from macrice.de import assets, creator_assets, creator_workspace, drafts, pack, recipes
from tests.test_de_portable_wallpapers import png


PROVENANCE = {"author": "RiceBowl Artist", "license": "CC-BY-4.0",
              "origin": "original", "source_reference": "https://example.invalid/original"}


class CreatorAssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("config", "state"):
            (self.root / name).mkdir(mode=0o700)
        env = patch.dict(os.environ, {
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_STATE_HOME": str(self.root / "state"),
        })
        env.start()
        self.addCleanup(env.stop)
        self.source = self.root / "original.png"
        self.source.write_bytes(png())

    def test_import_catalog_labels_permissions_idempotency(self):
        self.assertEqual(creator_assets.catalog(), [])
        first = creator_assets.import_wallpaper(self.source, label="Summer original",
                                               provenance=PROVENANCE)
        self.assertEqual((first.width, first.height), (1, 1))
        self.assertEqual(first.provenance, PROVENANCE)
        self.assertEqual(first.asset_id, assets.image_id(png()))
        self.assertEqual(creator_assets.catalog(), [first])
        sidecar = self.root / "config/ricebowl/wallpapers" / (first.asset_id + ".json")
        self.assertEqual(sidecar.stat().st_mode & 0o777, 0o600)
        self.assertEqual(creator_assets.import_wallpaper(self.source, label="Summer original",
                                                         provenance=PROVENANCE), first)
        with self.assertRaisesRegex(assets.AssetError, "different attribution"):
            creator_assets.import_wallpaper(self.source, label="Unrelated", provenance=PROVENANCE)
        self.assertEqual(creator_assets.entry(first.asset_id).label, "Summer original")

    def test_reject_invalid_local_images_attribution_and_tampering(self):
        symlink = self.root / "symlink.png"
        symlink.symlink_to(self.source)
        for source, label, declaration in (
            (symlink, "Okay", PROVENANCE),
            (self.source, "../unsafe", PROVENANCE),
            (self.source, "Okay", {**PROVENANCE, "license": "invented-license"}),
            (self.source, "Okay", {**PROVENANCE, "author": "Bad\nname"}),
        ):
            with self.subTest(source=source, label=label, declaration=declaration):
                with self.assertRaises(assets.AssetError):
                    creator_assets.import_wallpaper(source, label=label, provenance=declaration)
        self.assertEqual(creator_assets.catalog(), [])
        installed = creator_assets.import_wallpaper(self.source, label="Valid", provenance=PROVENANCE)
        sidecar = self.root / "config/ricebowl/wallpapers" / (installed.asset_id + ".json")
        sidecar.write_text('{"asset_id":"changed"}')
        self.assertEqual(creator_assets.catalog(), [])
        with self.assertRaises(assets.AssetError):
            creator_assets.entry(installed.asset_id)

    def test_malformed_metadata_labels_do_not_crash_catalog(self):
        imported = creator_assets.import_wallpaper(self.source, label="Good",
                                                    provenance=PROVENANCE)
        sidecar = self.root / "config/ricebowl/wallpapers" / (imported.asset_id + ".json")
        document = json.loads(sidecar.read_text())
        document["label"] = {"not": "plain text"}
        sidecar.write_text(json.dumps(document))
        self.assertEqual(creator_assets.catalog(), [])
        with self.assertRaises(assets.AssetError):
            creator_assets.entry(imported.asset_id)

    def test_wallpaper_draft_allowlist_respects_schema_version(self):
        imported = creator_assets.import_wallpaper(self.source, label="Versioned",
                                                    provenance=PROVENANCE)
        self.assertTrue(drafts._allowed_value("/desktop/wallpaper", imported.asset_id, 10))
        self.assertTrue(drafts._allowed_value("/desktop/wallpaper", imported.asset_id, 6))
        self.assertFalse(drafts._allowed_value("/desktop/wallpaper", imported.asset_id, 5))
        self.assertFalse(drafts._allowed_value("/desktop/wallpaper", "asset-../../bad", 10))

    def test_versioned_selection_exports_attribution_and_png_without_apply(self):
        imported = creator_assets.import_wallpaper(self.source, label="Studio backdrop",
                                                   provenance=PROVENANCE)
        original = creator_workspace.create_draft("heritage")
        revised, _ = creator_workspace.save_revision(original.path, {
            "/desktop/wallpaper": imported.asset_id,
        }, expected_sha256=original.semantic_sha256)
        self.assertNotEqual(revised.path, original.path)
        self.assertIn(recipes.load(str(original.path)).wallpaper, recipes.WALLPAPERS)
        destination = self.root / "studio.ricepack"
        receipt = creator_workspace.export_draft(revised, destination)
        self.assertEqual(receipt["pack_version"], 3)
        self.assertFalse(receipt["applied"])
        with zipfile.ZipFile(destination) as archive:
            self.assertEqual(archive.read("assets/wallpaper.png"), png())
            declared = json.loads(archive.read("ricepack.json"))
        self.assertEqual(declared["asset_manifest"]["wallpaper"]["provenance"], PROVENANCE)
        self.assertEqual(pack.inspect_pack(destination)["pack_version"], 3)
        self.assertEqual(recipes.current_selection(), ("classic", None))
        with self.assertRaises(pack.PackError):
            creator_workspace.export_draft(revised, destination)

    def test_existing_cli_import_has_honest_unknown_provenance(self):
        asset_id, _ = assets.import_png(self.source)
        visible = creator_assets.entry(asset_id)
        self.assertEqual(visible.provenance, creator_assets.UNKNOWN_PROVENANCE)
        self.assertIn("Imported PNG", visible.label)


if __name__ == "__main__":
    unittest.main()
