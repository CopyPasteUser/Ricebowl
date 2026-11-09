"""Creator 0.5: strictly bounded visual assets, immutable drafts, portable v4."""

import io
import json
import os
from pathlib import Path
import stat
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib
import zipfile

from macrice.de import creator_workspace, drafts, pack, recipes, style_assets


ATTRIBUTION = {"author": "RiceBowl Creator", "license": "CC-BY-4.0",
               "origin": "original", "source_reference": "local art"}


def icon_png() -> bytes:
    def chunk(name, data):
        return (struct.pack(">I", len(data)) + name + data
                + struct.pack(">I", zlib.crc32(name + data)))
    raster = (b"\x00" + b"\x4a\x8a\xca\xff" * 48) * 48
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 48, 48, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raster)) + chunk(b"IEND", b""))


class CreatorStyleAssetsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for directory in ("config", "state"):
            (self.root / directory).mkdir(mode=0o700)
        env = patch.dict(os.environ, {
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_STATE_HOME": str(self.root / "state"),
        })
        env.start()
        self.addCleanup(env.stop)
        self.icon = self.root / "my-icon.png"
        self.icon.write_bytes(icon_png())

    def test_schema_v11_is_explicit_and_v10_remains_compatible(self):
        info = creator_workspace.create_draft("heritage")
        self.assertEqual(recipes.load(str(info.path)).schema_version, 11)
        self.assertEqual(recipes.load(str(info.path)).artwork.font, "builtin")
        manifest = json.loads(info.path.read_text())
        manifest["artwork"]["font"] = "../font.ttf"
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(manifest).encode())
        del manifest["artwork"]
        manifest["schema_version"] = 10
        self.assertIsNone(recipes.parse(json.dumps(manifest).encode()).artwork)

    def test_icon_validation_and_symlink_fail_closed(self):
        self.assertEqual(len(icon_png()) < style_assets.MAX_ICON_BYTES, True)
        self.assertTrue(style_assets.ICON_ID.fullmatch(style_assets._identity(icon_png(), "icon")))
        short = icon_png().replace(struct.pack(">I", 48), struct.pack(">I", 47), 1)
        with self.assertRaises(style_assets.StyleAssetError):
            style_assets.validate(short, "icon")
        alias = self.root / "alias.png"
        alias.symlink_to(self.icon)
        with self.assertRaises(style_assets.StyleAssetError):
            style_assets.import_asset(alias, kind="icon", label="Original",
                                      provenance=ATTRIBUTION)
        with self.assertRaises(style_assets.StyleAssetError):
            style_assets.validate(b"not a font", "font")

    def test_catalog_is_private_and_idempotent_with_declaration(self):
        added = style_assets.import_asset(self.icon, kind="icon", label="Glowing app",
                                          provenance=ATTRIBUTION)
        self.assertEqual(style_assets.read(added.identifier), icon_png())
        self.assertEqual(style_assets.list_assets("icon"), [added])
        self.assertEqual(style_assets.import_asset(self.icon, kind="icon", label="Glowing app",
                                                   provenance=ATTRIBUTION), added)
        with self.assertRaises(style_assets.StyleAssetError):
            style_assets.import_asset(self.icon, kind="icon", label="Other",
                                      provenance=ATTRIBUTION)
        record = self.root / "config/ricebowl/visual-assets" / (added.identifier + ".json")
        self.assertEqual(stat.S_IMODE(record.stat().st_mode), 0o600)
        self.assertFalse(drafts._allowed_value("/artwork/icons/applications", added.identifier, 10))
        self.assertTrue(drafts._allowed_value("/artwork/icons/applications", added.identifier, 11))

    def test_saved_icon_exports_and_imports_v4_without_apply(self):
        icon = style_assets.import_asset(self.icon, kind="icon", label="Custom app",
                                         provenance=ATTRIBUTION)
        info = creator_workspace.create_draft("heritage")
        revised, paths = creator_workspace.save_revision(info.path, {
            "/artwork/icons/applications": icon.identifier,
        }, expected_sha256=info.semantic_sha256)
        self.assertEqual(paths[0]["path"], "/artwork/icons/applications")
        self.assertEqual(recipes.load(str(info.path)).artwork.icons[0], "builtin")
        target = self.root / "new.ricepack"
        receipt = creator_workspace.export_draft(revised, target)
        self.assertEqual(receipt["pack_version"], 4)
        self.assertFalse(receipt["applied"])
        with zipfile.ZipFile(target) as archive:
            self.assertEqual(archive.read("assets/icons/applications.png"), icon_png())
            self.assertEqual(json.loads(archive.read("ricepack.json"))
                             ["asset_manifest"]["visual"]["icons"]["applications"]
                             ["provenance"], ATTRIBUTION)
        self.assertEqual(pack.inspect_pack(target)["pack_version"], 4)
        imported = pack.import_pack(target)
        self.assertTrue(imported["imported"])
        self.assertFalse(imported["applied"])
        self.assertEqual(style_assets.read(icon.identifier), icon_png())

    def test_untampered_font_can_be_packed_if_system_fixture_present(self):
        fixture = Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")
        if not fixture.exists():
            self.skipTest("No system font fixture")
        source = self.root / "original.ttf"
        source.write_bytes(fixture.read_bytes())
        face = style_assets.import_asset(source, kind="font", label="DejaVu Mono",
                                         provenance=ATTRIBUTION)
        info = creator_workspace.create_draft("chrome")
        revised, _ = creator_workspace.save_revision(info.path, {"/artwork/font": face.identifier},
                                                     expected_sha256=info.semantic_sha256)
        target = self.root / "font.ricepack"
        creator_workspace.export_draft(revised, target)
        with zipfile.ZipFile(target) as archive:
            self.assertEqual(archive.read("assets/font.ttf"), source.read_bytes())
        self.assertEqual(pack.inspect_pack(target)["pack_version"], 4)

    def test_archive_mismatch_fails_before_import(self):
        icon = style_assets.import_asset(self.icon, kind="icon", label="Custom app",
                                         provenance=ATTRIBUTION)
        info = creator_workspace.create_draft("heritage")
        revised, _ = creator_workspace.save_revision(info.path, {
            "/artwork/icons/applications": icon.identifier,
        }, expected_sha256=info.semantic_sha256)
        archive_path = self.root / "clean.ricepack"
        creator_workspace.export_draft(revised, archive_path)
        with zipfile.ZipFile(archive_path) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        entries["assets/icons/applications.png"] = b"fake executable"
        tampered = self.root / "tampered.ricepack"
        with zipfile.ZipFile(tampered, "w") as archive:
            for name, data in entries.items():
                record = zipfile.ZipInfo(name)
                record.create_system = 3
                record.external_attr = (stat.S_IFREG | 0o644) << 16
                archive.writestr(record, data)
        with self.assertRaises(pack.PackError):
            pack.inspect_pack(tampered)
        self.assertFalse((self.root / "config/ricebowl/recipes").exists())


if __name__ == "__main__":
    unittest.main()
