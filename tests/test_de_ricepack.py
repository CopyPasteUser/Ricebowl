"""Portable, deterministic RicePack/Creator contract and untrusted archive tests."""

import io
import json
import os
import stat
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest import mock

from macrice.cli import main as cli
from macrice.de import catalog, creator_contract, pack, recipes, review


def _zip_files(items, *, compressed=False, symlink=False):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, payload in items:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED if compressed else zipfile.ZIP_STORED
            info.external_attr = ((stat.S_IFLNK if symlink else stat.S_IFREG) | 0o644) << 16
            # Duplicated central-directory names are intentionally fuzzed.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                archive.writestr(info, payload)
    return output.getvalue()


class PortableRicePackTests(unittest.TestCase):
    def test_v2_asset_receipts_tamper_detection_and_v1_read_compatibility(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "asset-pinned.ricepack"
            pack.export_pack("chrome", original)
            with zipfile.ZipFile(original) as archive:
                manifest = json.loads(archive.read("ricepack.json"))
                recipe_data = archive.read("recipe.json")
            asset = manifest["asset_manifest"]["wallpaper"]
            self.assertEqual(len(asset["sha256"]), 64)
            self.assertEqual(asset["provenance"]["license"], "unspecified")

            wrong = json.loads(json.dumps(manifest))
            wrong["asset_manifest"]["wallpaper"]["sha256"] = "0" * 64
            modified = root / "modified.ricepack"
            modified.write_bytes(_zip_files([("ricepack.json", json.dumps(wrong)),
                                              ("recipe.json", recipe_data)]))
            with self.assertRaises(pack.PackError) as failure:
                pack.inspect_pack(modified)
            self.assertEqual(failure.exception.code, "asset_mismatch")
            config = root / "config"
            config.mkdir(mode=0o700)
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)}):
                with self.assertRaises(pack.PackError) as failure:
                    pack.import_pack(modified)
                self.assertEqual(failure.exception.code, "asset_mismatch")
                self.assertFalse((config / "ricebowl").exists())

            legacy = json.loads(json.dumps(manifest))
            legacy["format_version"] = 1
            del legacy["asset_manifest"]
            old_pack = root / "old-v1.ricepack"
            old_pack.write_bytes(_zip_files([("ricepack.json", json.dumps(legacy)),
                                             ("recipe.json", recipe_data)]))
            self.assertEqual(pack.inspect_pack(old_pack)["pack_version"], 1)

    def test_v2_per_asset_provenance_is_declarative_and_non_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = root / "metadata.json"
            metadata.write_text(json.dumps({
                "author": "Rice Artist", "license": "CC0-1.0",
                "origin": "original", "source_reference": "offline work",
                "wallpaper_provenance": {
                    "author": "Wallpaper Artist", "license": "CC-BY-4.0",
                    "origin": "adapted", "source_reference": "local painting",
                },
            }))
            archive = root / "v2.ricepack"
            manifest = pack.export_pack("classic", archive, metadata=metadata)["manifest"]
            self.assertEqual(manifest["asset_manifest"]["wallpaper"]["provenance"]["author"],
                             "Wallpaper Artist")
            self.assertEqual(pack.inspect_pack(archive)["manifest"], manifest)
            metadata.write_text(json.dumps({
                "author": "Rice Artist", "license": "CC0-1.0",
                "origin": "original", "source_reference": "offline work",
                "wallpaper_provenance": {"author": "Bad", "license": "run:script",
                                          "origin": "original", "source_reference": ""},
            }))
            with self.assertRaises(pack.PackError):
                pack.export_pack("classic", root / "invalid.ricepack", metadata=metadata)

    def test_both_builtin_schemas_export_deterministically_with_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for base in ("classic", "chrome"):
                with self.subTest(base=base):
                    first, second = (root / f"{base}-{i}.ricepack" for i in (1, 2))
                    one = pack.export_pack(base, first)
                    two = pack.export_pack(base, second)
                    self.assertEqual(first.read_bytes(), second.read_bytes())
                    self.assertEqual(one["package_sha256"], two["package_sha256"])
                    self.assertEqual(first.stat().st_mode & 0o777, 0o600)
                    inspected = pack.inspect_pack(first)
                    self.assertEqual(inspected["manifest"], one["manifest"])
                    self.assertFalse(inspected["applied"])
                    with zipfile.ZipFile(first) as archive:
                        self.assertEqual(archive.namelist(), ["ricepack.json", "recipe.json"])
                        self.assertTrue(all(i.date_time[:3] == (1980, 1, 1)
                                            for i in archive.infolist()))
                        self.assertEqual(recipes.parse(archive.read("recipe.json")).recipe_id, base)

    def test_v5_provenance_and_import_preserve_recipe_without_applying(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "draft.json"
            metadata = root / "provenance.json"
            archive = root / "desktop.ricepack"
            created = recipes.create_from_template(
                source="classic", destination=source, recipe_id="original-y2k",
                name="Original Y2K", schema_version=5)
            metadata.write_text(json.dumps({
                "author": "Desktop Artist", "license": "CC-BY-4.0",
                "origin": "ai-assisted", "source_reference": "local concept sketch",
            }), encoding="utf-8")
            expected = review.review(str(source))["summary"]["semantic_sha256"]
            exported = pack.export_pack(str(source), archive, metadata=metadata)
            self.assertEqual(exported["manifest"]["recipe"]["semantic_sha256"], expected)
            self.assertEqual(exported["manifest"]["provenance"]["origin"], "ai-assisted")
            self.assertEqual(exported["manifest"]["recipe"]["schema_version"], 5)
            self.assertEqual(exported["manifest"]["format_version"], 2)
            self.assertEqual(exported["manifest"]["asset_manifest"]["wallpaper"]["id"],
                             created.wallpaper)
            config = root / "config"
            config.mkdir(mode=0o700)
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)}):
                installed = pack.import_pack(archive)
                self.assertTrue(installed["imported"])
                self.assertFalse(installed["applied"])
                self.assertEqual(installed["recipe_id"], created.recipe_id)
                self.assertTrue(installed["provenance_saved"])
                self.assertEqual(recipes.current_selection(), ("classic", None))
                target = config / "ricebowl" / "recipes" / "original-y2k.json"
                self.assertTrue(target.is_file())
                self.assertEqual(target.stat().st_mode & 0o777, 0o600)
                self.assertEqual(review.review(str(target))["summary"]["semantic_sha256"],
                                 expected)
                attribution = config / "ricebowl" / "recipes" / "original-y2k.ricepack-provenance"
                self.assertTrue(attribution.is_file())
                self.assertEqual(attribution.stat().st_mode & 0o777, 0o600)
                roundtrip = root / "roundtrip.ricepack"
                saved_manifest = pack.export_pack("original-y2k", roundtrip)["manifest"]
                self.assertEqual(saved_manifest["provenance"], exported["manifest"]["provenance"])
                self.assertEqual(saved_manifest["asset_manifest"], exported["manifest"]["asset_manifest"])
                # The import receipt is not a recipe and must never appear in
                # component discovery or consume the recipe collection quota.
                self.assertEqual(len(recipes.imported_recipes()), 1)
                for index in range(128):
                    (target.parent / f"other-{index}.ricepack-provenance").write_text("{}")
                self.assertEqual(len(recipes.imported_recipes()), 1)
                with self.assertRaises(pack.PackError) as caught:
                    pack.import_pack(archive)
                self.assertEqual(caught.exception.code, "import_unavailable")

    def test_imported_provenance_fails_closed_when_recipe_is_modified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            recipes.create_from_template(source="classic", destination=source,
                                         recipe_id="attributed-rice", name="Attributed Rice",
                                         schema_version=5)
            archive = root / "safe.ricepack"
            pack.export_pack(str(source), archive)
            config = root / "config"
            config.mkdir(mode=0o700)
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)}):
                pack.import_pack(archive)
                imported = config / "ricebowl" / "recipes" / "attributed-rice.json"
                changed = json.loads(imported.read_text())
                changed["name"] = "Edited without provenance review"
                imported.write_text(json.dumps(changed))
                with self.assertRaises(pack.PackError) as caught:
                    pack.export_pack("attributed-rice", root / "must-fail.ricepack")
                self.assertEqual(caught.exception.code, "provenance_stale")
                self.assertFalse((root / "must-fail.ricepack").exists())

    def test_imported_attribution_cannot_be_reused_for_changed_artwork_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "original.json"
            recipes.create_from_template(source="classic", destination=source,
                                         recipe_id="artwork-guard", name="Artwork Guard",
                                         schema_version=5)
            archive = root / "safe.ricepack"
            pack.export_pack(str(source), archive)
            config = root / "config"
            config.mkdir(mode=0o700)
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)}):
                pack.import_pack(archive)
                with mock.patch("macrice.de.pack._bundled_wallpaper",
                                return_value=("aero-seven-blue", "0" * 64)):
                    with self.assertRaises(pack.PackError) as caught:
                        pack.export_pack("artwork-guard", root / "wrong-artwork.ricepack")
                self.assertEqual(caught.exception.code, "provenance_stale")
                self.assertFalse((root / "wrong-artwork.ricepack").exists())

    def test_retries_interrupted_import_only_with_identical_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            recipes.create_from_template(source="classic", destination=source,
                                         recipe_id="recovery-test", name="Recovery",
                                         schema_version=5)
            archive = root / "safe.ricepack"
            pack.export_pack(str(source), archive)
            config = root / "config"
            config.mkdir(mode=0o700)
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)}):
                pack.import_pack(archive)
                folder = config / "ricebowl" / "recipes"
                imported = folder / "recovery-test.json"
                # Reproduce the crash window: safe receipt published, recipe
                # still absent. A repeat import of exactly the same pack works.
                imported.unlink()
                self.assertTrue(pack.import_pack(archive)["provenance_saved"])
                self.assertTrue(imported.is_file())

    def test_untrusted_provenance_receipts_are_never_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            recipes.create_from_template(source="classic", destination=source,
                                         recipe_id="protected-rice", name="Protected",
                                         schema_version=5)
            archive = root / "safe.ricepack"
            pack.export_pack(str(source), archive)
            config = root / "config"
            config.mkdir(mode=0o700)
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)}):
                pack.import_pack(archive)
                folder = config / "ricebowl" / "recipes"
                receipt = folder / "protected-rice.ricepack-provenance"
                receipt.chmod(0o644)
                with self.assertRaises(pack.PackError):
                    pack.export_pack("protected-rice", root / "bad.ricepack")
                receipt.chmod(0o600)
                receipt.unlink()
                outside = root / "unrelated.txt"
                outside.write_text("KEEP")
                receipt.symlink_to(outside)
                with self.assertRaises(pack.PackError):
                    pack.export_pack("protected-rice", root / "bad2.ricepack")
                self.assertEqual(outside.read_text(), "KEEP")

    def test_rejects_overwrite_symlinks_unowned_modes_and_reserved_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "keep.ricepack"
            original.write_bytes(b"do not overwrite")
            link = root / "link.ricepack"
            link.symlink_to(original)
            for target in (original, link, Path("relative.ricepack")):
                with self.subTest(target=target), self.assertRaises(pack.PackError):
                    pack.export_pack("classic", target)
            self.assertEqual(original.read_bytes(), b"do not overwrite")
            valid = root / "valid.ricepack"
            pack.export_pack("classic", valid)
            with self.assertRaises(pack.PackError):
                pack.inspect_pack(link)
            valid.chmod(0o666)
            with self.assertRaises(pack.PackError):
                pack.inspect_pack(valid)
            valid.chmod(0o600)
            config = root / "config"
            config.mkdir(mode=0o700)
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)}):
                with self.assertRaises(pack.PackError) as caught:
                    pack.import_pack(valid)
                self.assertEqual(caught.exception.code, "reserved_id")
                self.assertFalse((config / "ricebowl").exists())

    def test_invalid_manifest_and_archive_entries_are_always_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "base.ricepack"
            pack.export_pack("classic", original)
            with zipfile.ZipFile(original) as archive:
                manifest = json.loads(archive.read("ricepack.json"))
                recipe = archive.read("recipe.json")
            scenarios = []
            bad_checksum = json.loads(json.dumps(manifest))
            bad_checksum["recipe"]["sha256"] = "0" * 64
            scenarios.append(_zip_files([("ricepack.json", json.dumps(bad_checksum)),
                                         ("recipe.json", recipe)]))
            bad_schema = json.loads(json.dumps(manifest))
            bad_schema["format_version"] = 3
            scenarios.append(_zip_files([("ricepack.json", json.dumps(bad_schema)),
                                         ("recipe.json", recipe)]))
            bad_metadata = json.loads(json.dumps(manifest))
            bad_metadata["provenance"]["license"] = "exec:sh"
            scenarios.append(_zip_files([("ricepack.json", json.dumps(bad_metadata)),
                                         ("recipe.json", recipe)]))
            scenarios.extend((
                _zip_files([("ricepack.json", json.dumps(manifest)),
                            ("recipe.json", recipe), ("../../evil", b"script")]),
                _zip_files([("ricepack.json", json.dumps(manifest)),
                            ("recipe.json", recipe)], compressed=True),
                _zip_files([("ricepack.json", json.dumps(manifest)),
                            ("recipe.json", recipe)], symlink=True),
                _zip_files([("ricepack.json", json.dumps(manifest)),
                            ("ricepack.json", json.dumps(manifest)),
                            ("recipe.json", recipe)]),
                _zip_files([("ricepack.json", json.dumps(manifest)),
                            ("recipe.json", b'{"schema_version":5,"exec":"bad"}')]),
                b"not a zip file",
                b"0" * (pack.MAX_PACK_BYTES + 1),
            ))
            config = root / "config"
            config.mkdir(mode=0o700)
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)}):
                for index, content in enumerate(scenarios):
                    with self.subTest(index=index):
                        bad = root / f"invalid-{index}.ricepack"
                        bad.write_bytes(content)
                        with self.assertRaises(pack.PackError):
                            pack.inspect_pack(bad)
                        with self.assertRaises(pack.PackError):
                            pack.import_pack(bad)
                self.assertFalse((config / "ricebowl").exists())

    def test_metadata_rejects_ambiguous_licenses_and_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, source in enumerate((
                '{}',
                '{"author":"A","author":"B","license":"MIT","origin":"original","source_reference":""}',
                json.dumps({"author": "Bad\nName", "license": "MIT", "origin": "original",
                            "source_reference": ""}),
                json.dumps({"author": "artist", "license": "GPL-3.0", "origin": "original",
                            "source_reference": ""}),
            )):
                meta = root / f"meta-{index}.json"
                meta.write_text(source)
                output = root / f"not-created-{index}.ricepack"
                with self.subTest(index=index), self.assertRaises(pack.PackError):
                    pack.export_pack("classic", output, metadata=meta)
                self.assertFalse(output.exists())

    def test_versioned_api_and_cli_cover_safe_authoring_cycle(self):
        spec = creator_contract.describe_creator_api()
        self.assertEqual(spec["api_version"], 3)
        self.assertEqual(catalog.describe()["authoring"]["ricepack"],
                         creator_contract.describe_ricepack())
        self.assertTrue(spec["ricepack"]["provenance"]["roundtrip_preserves_attribution"])
        commands = {item["command"] for item in spec["commands"]}
        self.assertTrue({"catalog", "review", "draft-check", "draft-edit",
                         "render", "visual-compare",
                         "capture", "pack-export", "pack-inspect", "pack-import"} <= commands)
        with mock.patch("builtins.print") as printed:
            self.assertEqual(cli(["de", "creator-api", "--json"]), 0)
        self.assertEqual(json.loads(printed.call_args.args[0]), spec)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "verified.ricepack"
            with mock.patch("builtins.print") as printed:
                self.assertEqual(cli(["de", "pack-export", "--recipe", "chrome",
                                      "--output", str(target), "--json"]), 0)
            self.assertTrue(json.loads(printed.call_args.args[0])["created"])
            with mock.patch("builtins.print") as printed:
                self.assertEqual(cli(["de", "pack-inspect", "--package", str(target),
                                      "--json"]), 0)
            self.assertTrue(json.loads(printed.call_args.args[0])["valid"])
            with mock.patch("builtins.print") as printed:
                self.assertEqual(cli(["de", "pack-inspect", "--package", str(target),
                                      "--recipe", "classic", "--json"]), 1)
            with mock.patch("builtins.print") as printed:
                self.assertEqual(cli(["de", "pack-import", "--package",
                                      str(Path(directory) / "missing.ricepack"), "--json"]), 2)
            failed = json.loads(printed.call_args.args[0])
            self.assertFalse(failed["ok"])
            self.assertEqual(failed["error"]["code"], "invalid_input")
            self.assertNotIn(directory, json.dumps(failed))
        for flags in (("--package", "/tmp/anything.ricepack"),
                      ("--metadata", "/tmp/anything.json"),
                      ("--output", "/tmp/anything.ricepack")):
            with self.subTest(flags=flags), mock.patch("sys.stderr"):
                self.assertEqual(cli(["de", "catalog", *flags]), 1)


if __name__ == "__main__":
    unittest.main()
