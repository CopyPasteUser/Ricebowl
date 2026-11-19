"""SG4: reviewed, offline RicePack export/import and fail-closed preflight.

All mutations are confined to temporary XDG homes; never touch the session.
"""
from __future__ import annotations

import io
import json
import os
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from macrice.cli import main as cli
from macrice.de import (assets, creator_assets, creator_workspace, pack,
                        recipes, review, style_assets)
from tests.test_de_portable_wallpapers import png
from tests.test_creator_style_assets import icon_png


DECLARATION = {"author": "SG4 test artist", "license": "CC0-1.0",
               "origin": "original", "source_reference": "original drawing"}


def rewritten_zip(path: Path, changes: dict[str, bytes] | None = None,
                  *, extra: tuple[str, bytes] | None = None,
                  compressed: bool = False,
                  omit: frozenset[str] = frozenset()) -> bytes:
    with zipfile.ZipFile(path) as source:
        entries = [(name, source.read(name)) for name in source.namelist()
                   if name not in omit]
    replaced = changes or {}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as target:
        for name, body in entries + ([extra] if extra else []):
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED if compressed else zipfile.ZIP_STORED
            target.writestr(info, replaced.get(name, body))
    return output.getvalue()


class RicePackPreflightTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ("state", "config"):
            (self.root / name).mkdir(mode=0o700)
        context = mock.patch.dict(os.environ, {
            "XDG_STATE_HOME": str(self.root / "state"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
        })
        context.start()
        self.addCleanup(context.stop)

    def export(self, token="classic") -> Path:
        output = self.root / (token + ".ricepack")
        pack.export_pack(token, output)
        return output

    def test_offline_preflight_is_pure_before_and_after_command(self):
        archive = self.export()
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*"))
        with mock.patch("builtins.print") as output:
            self.assertEqual(cli(["de", "pack-preflight", "--package", str(archive),
                                  "--json"]), 2)  # reserved built-in cannot be installed
        self.assertEqual(json.loads(output.call_args.args[0])["error"]["code"], "reserved_id")
        self.assertEqual(before, sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*")))

    def test_two_distinct_creator_rices_roundtrip_without_activation(self):
        heritage = creator_workspace.create_draft("heritage")
        orbit = creator_workspace.create_draft("orbit")
        self.assertNotEqual(recipes.load(str(heritage.path)).position,
                            recipes.load(str(orbit.path)).position)
        self.assertNotEqual(recipes.load(str(heritage.path)).menu_presentation,
                            recipes.load(str(orbit.path)).menu_presentation)
        self.assertEqual(recipes.current_selection(), ("classic", None))
        for index, draft in enumerate((heritage, orbit)):
            with self.subTest(rice=draft.name):
                archive = self.root / ("roundtrip-%d.ricepack" % index)
                original = creator_workspace.export_draft(draft, archive)
                self.assertTrue(pack.inspect_pack(archive)["valid"])
                ready = pack.preflight_import(archive,
                                              expected_manifest=original["manifest"])
                self.assertEqual(ready["package_sha256"], original["package_sha256"])
                self.assertFalse(ready["applied"])
                with mock.patch("builtins.print") as output:
                    self.assertEqual(cli(["de", "pack-preflight", "--package",
                                          str(archive), "--json"]), 0)
                self.assertTrue(json.loads(output.call_args.args[0])["ready"])
                installed = pack.import_pack(archive, expected_manifest=original["manifest"])
                self.assertTrue(installed["imported"])
                self.assertFalse(installed["applied"])
                self.assertEqual(recipes.load(draft.recipe_id).recipe_id, draft.recipe_id)
                self.assertEqual(recipes.current_selection(), ("classic", None))
                with self.assertRaises(pack.PackError) as conflict:
                    pack.preflight_import(archive)
                self.assertEqual(conflict.exception.code, "import_unavailable")
        self.assertNotEqual(heritage.semantic_sha256, orbit.semantic_sha256)

    def test_pending_recovery_and_stale_manifest_block_read_only_preflight(self):
        draft = creator_workspace.create_draft("heritage")
        archive = self.root / "safe.ricepack"
        emitted = creator_workspace.export_draft(draft, archive)
        stale = json.loads(json.dumps(emitted["manifest"]))
        stale["recipe"]["sha256"] = "0" * 64
        with self.assertRaises(pack.PackError) as caught:
            pack.preflight_import(archive, expected_manifest=stale)
        self.assertEqual(caught.exception.code, "pack_changed")
        folder = recipes._private_recipe_dir(create=True)
        pending = folder / pack._IMPORT_PENDING
        pending.write_bytes(b"intentionally corrupt journal")
        pending.chmod(0o600)
        with self.assertRaises(pack.PackError) as caught:
            pack.preflight_import(archive)
        self.assertEqual(caught.exception.code, "recovery_required")
        self.assertEqual(pending.read_bytes(), b"intentionally corrupt journal")
        self.assertFalse((folder / (draft.recipe_id + ".json")).exists())

    def test_reviewed_export_rejects_source_change_after_initial_check(self):
        draft = creator_workspace.create_draft("heritage")
        original = review._manifest(recipes.load(str(draft.path)))
        changed = json.loads(json.dumps(original))
        changed["name"] = "Changed after review"
        replacement = recipes.parse(json.dumps(changed).encode("utf-8"))
        target = self.root / "never-published.ricepack"
        with mock.patch.object(pack, "_read_recipe", return_value=replacement):
            with self.assertRaises(pack.PackError) as caught:
                creator_workspace.export_draft(draft, target)
        self.assertEqual(caught.exception.code, "recipe_changed")
        self.assertFalse(target.exists())
        with self.assertRaises(pack.PackError) as caught:
            pack.export_pack("classic", target, expected_semantic_sha256="not-a-sha")
        self.assertEqual(caught.exception.code, "invalid_fingerprint")
        self.assertFalse(target.exists())

    def test_untrusted_archives_produce_stable_error_codes_and_no_writes(self):
        archive = self.export("chrome")
        with zipfile.ZipFile(archive) as source:
            original = json.loads(source.read("ricepack.json"))
        future = json.loads(json.dumps(original))
        future["format_version"] = 99
        invalid = json.loads(json.dumps(original))
        invalid["unexpected"] = True
        mismatch = json.loads(json.dumps(original))
        mismatch["recipe"]["sha256"] = "0" * 64
        scenarios = [
            (b"not a zip", "invalid_archive"),
            (rewritten_zip(archive, {"ricepack.json": json.dumps(future).encode()}),
             "unsupported_version"),
            (rewritten_zip(archive, {"ricepack.json": json.dumps(invalid).encode()}),
             "invalid_manifest"),
            (rewritten_zip(archive, {"ricepack.json": json.dumps(mismatch).encode()}),
             "recipe_mismatch"),
            (rewritten_zip(archive, extra=("../escape.txt", b"bad")), "unsafe_entries"),
            (rewritten_zip(archive, compressed=True), "unsafe_entries"),
        ]
        for index, (data, code) in enumerate(scenarios):
            with self.subTest(index=index, code=code):
                bad = self.root / ("invalid-%d.ricepack" % index)
                bad.write_bytes(data)
                bad.chmod(0o600)
                with self.assertRaises(pack.PackError) as failure:
                    pack.preflight_import(bad)
                self.assertEqual(failure.exception.code, code)
                error = pack.invalid_pack(failure.exception)
                self.assertEqual(error["error"]["code"], code)
                self.assertFalse(error["applied"])
        self.assertFalse((self.root / "config/ricebowl").exists())

    def test_missing_referenced_visual_asset_is_rejected_before_import(self):
        source = self.root / "custom.png"
        source.write_bytes(icon_png())
        icon = style_assets.import_asset(source, kind="icon", label="Original icon",
                                         provenance=DECLARATION)
        draft = creator_workspace.create_draft("heritage")
        revised, _ = creator_workspace.save_revision(
            draft.path, {"/artwork/icons/applications": icon.identifier},
            expected_sha256=draft.semantic_sha256)
        original = self.root / "valid-icon.ricepack"
        creator_workspace.export_draft(revised, original)
        self.assertEqual(pack.inspect_pack(original)["pack_version"], 4)
        damaged = self.root / "missing-icon.ricepack"
        damaged.write_bytes(rewritten_zip(
            original, omit=frozenset({"assets/icons/applications.png"})))
        damaged.chmod(0o600)
        with self.assertRaises(pack.PackError) as caught:
            pack.preflight_import(damaged)
        self.assertEqual(caught.exception.code, "asset_mismatch")
        self.assertFalse((self.root / "config/ricebowl/recipes" /
                          (revised.recipe_id + ".json")).exists())
        self.assertEqual(recipes.current_selection(), ("classic", None))

    def test_direction_spoofed_wallpaper_label_rejected_before_asset_install(self):
        source = self.root / "image.png"
        source.write_bytes(png())
        for label in ("Safe\u202eexe", "Safe\u2066hidden\u2069", "a\u200fb"):
            with self.subTest(label=label):
                with self.assertRaises(assets.AssetError):
                    creator_assets.import_wallpaper(source, label=label, provenance=DECLARATION)
        self.assertFalse((self.root / "config/ricebowl").exists())
        # Real RTL lettering (without control characters) is not prohibited.
        added = creator_assets.import_wallpaper(
            source, label="ציור מקורי", provenance=DECLARATION)
        self.assertEqual(added.label, "ציור מקורי")


if __name__ == "__main__":
    unittest.main()
