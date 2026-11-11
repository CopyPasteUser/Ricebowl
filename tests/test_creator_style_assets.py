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

from macrice.de import assets, creator_workspace, drafts, pack, recipes, style_assets
from tests.test_de_portable_wallpapers import png


ATTRIBUTION = {"author": "RiceBowl Creator", "license": "CC-BY-4.0",
               "origin": "original", "source_reference": "local art"}


def icon_png(color: bytes = b"\x4a\x8a\xca\xff") -> bytes:
    def chunk(name, data):
        return (struct.pack(">I", len(data)) + name + data
                + struct.pack(">I", zlib.crc32(name + data)))
    raster = (b"\x00" + color * 48) * 48
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

    def _two_icon_pack(self, *, wallpaper: bool = False):
        alternate = self.root / "other-icon.png"
        alternate.write_bytes(icon_png(b"\x2a\xc8\x83\xff"))
        first = style_assets.import_asset(self.icon, kind="icon", label="First original",
                                          provenance=ATTRIBUTION)
        second = style_assets.import_asset(alternate, kind="icon", label="Second original",
                                           provenance=ATTRIBUTION)
        changes = {"/artwork/icons/applications": first.identifier,
                   "/artwork/icons/terminal": second.identifier}
        wallpaper_id = None
        if wallpaper:
            wallpaper_id, _ = assets.store(png())
            changes["/desktop/wallpaper"] = wallpaper_id
        draft = creator_workspace.create_draft("heritage")
        edited, _ = creator_workspace.save_revision(
            draft.path, changes, expected_sha256=draft.semantic_sha256)
        archive = self.root / ("wallpaper-icons.ricepack" if wallpaper else "preflight-icons.ricepack")
        self.assertEqual(creator_workspace.export_draft(edited, archive)["pack_version"], 4)
        return archive, edited.recipe_id, (first.identifier, second.identifier), wallpaper_id

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

    def test_luna_builtin_icons_are_v12_only_and_export_without_private_assets(self):
        source = Path(__file__).resolve().parents[1] / "examples/wayland/xp-luna-columns.json"
        manifest = json.loads(source.read_text())
        recipe = recipes.parse(json.dumps(manifest).encode())
        self.assertEqual(recipe.artwork.icons, ("builtin-luna",) * 3)
        self.assertTrue(drafts._allowed_value("/artwork/icons/lock", "builtin-luna", 12))
        self.assertFalse(drafts._allowed_value("/artwork/icons/lock", "builtin-luna", 11))
        self.assertFalse(drafts._allowed_value("/artwork/icons/lock", "builtin-luna/../", 12))
        manifest["artwork"]["font"] = "builtin-luna"
        with self.assertRaises(recipes.RecipeError):
            recipes.parse(json.dumps(manifest).encode())

        target = self.root / "luna.ricepack"
        exported = pack.export_pack(str(source), target)
        self.assertEqual(exported["pack_version"], 2)
        with zipfile.ZipFile(target) as archive:
            self.assertFalse(any(name.startswith("assets/icons/") for name in archive.namelist()))
        self.assertEqual(pack.inspect_pack(target)["pack_version"], 2)

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

    def test_interrupted_icon_publication_retries_only_with_original_attribution(self):
        identifier = style_assets._identity(icon_png(), "icon")
        folder = self.root / "config/ricebowl/visual-assets"
        record = folder / f"{identifier}.json"
        image = folder / f"{identifier}.png"
        original_write = recipes._write_private_new

        def interrupt_image(destination, payload, **options):
            if destination == image:
                raise OSError("simulated crash before the asset becomes visible")
            return original_write(destination, payload, **options)

        with patch.object(recipes, "_write_private_new", side_effect=interrupt_image):
            with self.assertRaisesRegex(OSError, "simulated crash"):
                style_assets.import_asset(self.icon, kind="icon", label="Recovered icon",
                                          provenance=ATTRIBUTION)
        self.assertTrue(record.is_file(), "attribution must be committed first")
        self.assertFalse(image.exists(), "incomplete asset must stay undiscoverable")
        self.assertEqual(style_assets.list_assets("icon"), [])

        with self.assertRaises(style_assets.StyleAssetError):
            style_assets.import_asset(self.icon, kind="icon", label="Other author",
                                      provenance=ATTRIBUTION)
        self.assertFalse(image.exists())
        recovered = style_assets.import_asset(self.icon, kind="icon", label="Recovered icon",
                                              provenance=ATTRIBUTION)
        self.assertEqual(recovered.identifier, identifier)
        self.assertEqual(style_assets.list_assets("icon"), [recovered])
        self.assertEqual(style_assets.read(identifier), icon_png())

    def test_unattributed_asset_bytes_cannot_be_adopted_by_new_declaration(self):
        identifier = style_assets._identity(icon_png(), "icon")
        folder = self.root / "config/ricebowl/visual-assets"
        folder.mkdir(parents=True, mode=0o700)
        image = folder / f"{identifier}.png"
        image.write_bytes(icon_png())
        image.chmod(0o600)
        with self.assertRaises(style_assets.StyleAssetError):
            style_assets.import_asset(self.icon, kind="icon", label="Claimed art",
                                      provenance=ATTRIBUTION)
        self.assertFalse((folder / f"{identifier}.json").exists())
        self.assertEqual(image.read_bytes(), icon_png())

    def test_malformed_attribution_does_not_crash_library(self):
        added = style_assets.import_asset(self.icon, kind="icon", label="Check",
                                          provenance=ATTRIBUTION)
        record = self.root / "config/ricebowl/visual-assets" / (added.identifier + ".json")
        payload = json.loads(record.read_text())
        payload["provenance"]["license"] = "not-a-real-license"
        record.write_text(json.dumps(payload))
        self.assertEqual(style_assets.list_assets("icon"), [])

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

    def test_ricepack_v4_import_recovers_after_asset_publish_is_interrupted(self):
        icon = style_assets.import_asset(self.icon, kind="icon", label="Pack icon",
                                         provenance=ATTRIBUTION)
        draft = creator_workspace.create_draft("heritage")
        revised, _ = creator_workspace.save_revision(draft.path, {
            "/artwork/icons/applications": icon.identifier,
        }, expected_sha256=draft.semantic_sha256)
        archive = self.root / "safe-icons.ricepack"
        self.assertEqual(creator_workspace.export_draft(revised, archive)["pack_version"], 4)
        fresh = self.root / "another-config"
        fresh.mkdir(mode=0o700)
        assets_dir = fresh / "ricebowl/visual-assets"
        image = assets_dir / f"{icon.identifier}.png"
        original_write = recipes._write_private_new

        def interrupt_image(destination, payload, **options):
            if destination == image:
                raise OSError("simulated process exit during RicePack asset install")
            return original_write(destination, payload, **options)

        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(fresh)}):
            with patch.object(recipes, "_write_private_new", side_effect=interrupt_image):
                with self.assertRaises(pack.PackError):
                    pack.import_pack(archive)
            self.assertTrue((assets_dir / f"{icon.identifier}.json").is_file())
            self.assertFalse(image.exists())
            self.assertEqual(style_assets.list_assets("icon"), [])
            self.assertEqual(recipes.current_selection(), ("classic", None))
            self.assertFalse(list((fresh / "ricebowl/recipes").glob("*.json")))
            self.assertTrue(pack.import_pack(archive)["imported"])
            self.assertEqual(style_assets.read(icon.identifier), icon_png())
            self.assertEqual(style_assets.entry(icon.identifier), icon)
            self.assertEqual(recipes.current_selection(), ("classic", None))

    def test_ricepack_conflicting_second_icon_does_not_install_the_first(self):
        other = self.root / "different-icon.png"
        other.write_bytes(icon_png(b"\x2a\xc8\x83\xff"))
        first = style_assets.import_asset(self.icon, kind="icon", label="First original",
                                          provenance=ATTRIBUTION)
        second = style_assets.import_asset(other, kind="icon", label="Second original",
                                           provenance=ATTRIBUTION)
        draft = creator_workspace.create_draft("heritage")
        edited, _ = creator_workspace.save_revision(draft.path, {
            "/artwork/icons/applications": first.identifier,
            "/artwork/icons/terminal": second.identifier,
        }, expected_sha256=draft.semantic_sha256)
        archive = self.root / "multiple-icons.ricepack"
        self.assertEqual(creator_workspace.export_draft(edited, archive)["pack_version"], 4)

        other_config = self.root / "conflicting-config"
        other_config.mkdir(mode=0o700)
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(other_config)}):
            style_assets.store_pack_asset(second.identifier, other.read_bytes(),
                                          label="Different declaration", provenance=ATTRIBUTION)
            with self.assertRaises(pack.PackError) as failure:
                pack.import_pack(archive)
            self.assertEqual(failure.exception.code, "asset_unavailable")
            self.assertEqual(style_assets.list_assets("icon"), [
                style_assets.entry(second.identifier),
            ])
            self.assertFalse((other_config / "ricebowl/visual-assets" /
                              f"{first.identifier}.png").exists())
            self.assertFalse(list((other_config / "ricebowl/recipes").glob("*.json")))
            self.assertEqual(recipes.current_selection(), ("classic", None))

    def test_ricepack_receipt_collision_rejects_all_assets_before_publication(self):
        archive, token, icons, _ = self._two_icon_pack()
        for mode in ("other-receipt", "symlink"):
            with self.subTest(mode=mode):
                config = self.root / f"collision-{mode}"
                config.mkdir(mode=0o700)
                with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)}):
                    folder = recipes._private_recipe_dir(create=True)
                    receipt = folder / f"{token}{pack._RECEIPT_SUFFIX}"
                    outside = self.root / f"untouched-{mode}.txt"
                    outside.write_text("must not be altered")
                    if mode == "symlink":
                        receipt.symlink_to(outside)
                    else:
                        recipes._write_private_new(receipt, b"different private receipt\n",
                                                   suffix=pack._RECEIPT_SUFFIX)
                    with self.assertRaises(pack.PackError):
                        pack.import_pack(archive)
                    self.assertEqual(outside.read_text(), "must not be altered")
                    self.assertFalse((folder / f"{token}.json").exists())
                    self.assertFalse((config / "ricebowl/visual-assets").exists())
                    self.assertEqual(recipes.current_selection(), ("classic", None))

    def test_ricepack_broken_existing_wallpaper_rejects_all_icons(self):
        archive, token, icons, wallpaper_id = self._two_icon_pack(wallpaper=True)
        config = self.root / "bad-wallpaper-config"
        config.mkdir(mode=0o700)
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)}):
            folder = assets._collection(create=True)
            wallpaper_file = folder / f"{wallpaper_id}.png"
            recipes._write_private_new(wallpaper_file, png() + b"corrupt", suffix=".png")
            with self.assertRaises(pack.PackError) as failure:
                pack.import_pack(archive)
            self.assertEqual(failure.exception.code, "asset_unavailable")
            self.assertEqual(wallpaper_file.read_bytes(), png() + b"corrupt")
            self.assertFalse((config / "ricebowl/visual-assets").exists())
            self.assertFalse((config / "ricebowl/recipes" / f"{token}.json").exists())
            self.assertEqual(recipes.current_selection(), ("classic", None))

    def test_ricepack_retries_exact_prior_receipt_before_assets_are_installed(self):
        archive, token, icons, wallpaper_id = self._two_icon_pack(wallpaper=True)
        config = self.root / "retry-receipt-config"
        config.mkdir(mode=0o700)
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)}):
            folder = recipes._private_recipe_dir(create=True)
            receipt = folder / f"{token}{pack._RECEIPT_SUFFIX}"
            with zipfile.ZipFile(archive) as bundle:
                metadata = json.loads(bundle.read("ricepack.json"))
                original = recipes.parse(bundle.read("recipe.json"))
            provenance = pack._provenance_receipt(metadata, original)
            recipes._write_private_new(receipt, provenance, suffix=pack._RECEIPT_SUFFIX)
            self.assertTrue(pack.import_pack(archive)["imported"])
            self.assertEqual(receipt.read_bytes(), provenance)
            for icon in icons:
                self.assertEqual(style_assets.entry(icon).provenance, ATTRIBUTION)
            self.assertEqual(assets.read(wallpaper_id)[1], png())
            self.assertEqual(recipes.current_selection(), ("classic", None))

    def test_ricepack_rejects_two_attributions_for_one_icon_identity(self):
        original = style_assets.import_asset(self.icon, kind="icon", label="One icon",
                                              provenance=ATTRIBUTION)
        draft = creator_workspace.create_draft("heritage")
        edited, _ = creator_workspace.save_revision(draft.path, {
            "/artwork/icons/applications": original.identifier,
            "/artwork/icons/terminal": original.identifier,
        }, expected_sha256=draft.semantic_sha256)
        archive = self.root / "shared-icon.ricepack"
        creator_workspace.export_draft(edited, archive)
        with zipfile.ZipFile(archive) as source:
            contents = {name: source.read(name) for name in source.namelist()}
        manifest = json.loads(contents["ricepack.json"])
        manifest["asset_manifest"]["visual"]["icons"]["terminal"]["label"] = "Other owner"
        contents["ricepack.json"] = json.dumps(manifest).encode()
        malicious = self.root / "two-attributions.ricepack"
        with zipfile.ZipFile(malicious, "w") as result:
            for name, data in contents.items():
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                result.writestr(info, data)
        with self.assertRaises(pack.PackError) as caught:
            pack.inspect_pack(malicious)
        self.assertEqual(caught.exception.code, "asset_mismatch")

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

    def test_interrupted_font_publication_is_resumable_with_exact_provenance(self):
        fixture = Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")
        if not fixture.exists():
            self.skipTest("No system font fixture")
        payload = fixture.read_bytes()
        identifier = style_assets._identity(payload, "font")
        font_path = self.root / "config/ricebowl/visual-assets" / f"{identifier}.ttf"
        original_write = recipes._write_private_new

        def interrupt_font(destination, data, **options):
            if destination == font_path:
                raise OSError("interrupted private font write")
            return original_write(destination, data, **options)

        with patch.object(recipes, "_write_private_new", side_effect=interrupt_font):
            with self.assertRaisesRegex(OSError, "interrupted private font"):
                style_assets.store_pack_asset(identifier, payload, label="Installed typeface",
                                              provenance=ATTRIBUTION)
        self.assertFalse(font_path.exists())
        saved = style_assets.store_pack_asset(identifier, payload,
                                             label="Installed typeface", provenance=ATTRIBUTION)
        self.assertEqual(saved.kind, "font")
        self.assertEqual(style_assets.read(identifier), payload)
        self.assertEqual(style_assets.list_assets("font"), [saved])

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
