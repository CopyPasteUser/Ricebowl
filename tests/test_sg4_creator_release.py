"""SG4 Creator GUI release: reviewed archive identity and negative publication cases.

All fixtures use disposable XDG homes; no live session or host configuration.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from macrice.de import (creator_release, creator_workspace, pack, recipes,
                        style_assets)
from tests.test_creator_style_assets import icon_png


CREDIT = {"author": "SG4 original artwork test", "license": "CC0-1.0",
          "origin": "original", "source_reference": "self-authored offline PNG"}
FONT_CREDIT = {"author": "Liberation Fonts contributors", "license": "OFL-1.1",
               "origin": "original", "source_reference": "bundled OFL font"}


class CreatorReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ricebowl-sg4-release-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "config").mkdir(mode=0o700)
        (self.root / "state").mkdir(mode=0o700)
        env = mock.patch.dict(os.environ, {
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_STATE_HOME": str(self.root / "state"),
        })
        env.start()
        self.addCleanup(env.stop)

    def _visual_drafts(self):
        fonts = Path(__file__).resolve().parents[1] / "assets/fonts/LiberationSans-Regular.ttf"
        font_copy = self.root / "review.ttf"
        font_copy.write_bytes(fonts.read_bytes())
        font = style_assets.import_asset(
            font_copy, kind="font", label="Liberation Sans", provenance=FONT_CREDIT)
        drafts = []
        for index, kind in enumerate(("heritage", "orbit")):
            source = self.root / f"original-{kind}.png"
            source.write_bytes(icon_png(
                bytes.fromhex("4a8acaff") if index == 0 else
                bytes.fromhex("2ac883ff")))
            icon = style_assets.import_asset(
                source, kind="icon", label=f"Original {kind}", provenance=CREDIT)
            first = creator_workspace.create_draft(kind)
            saved, _ = creator_workspace.save_revision(first.path, {
                "/artwork/font": font.identifier,
                "/artwork/icons/applications": icon.identifier,
            }, expected_sha256=first.semantic_sha256)
            drafts.append((saved, icon.identifier, font.identifier, source.read_bytes()))
        return drafts

    def test_two_structurally_distinct_packs_are_reviewed_and_portable(self):
        drafts = self._visual_drafts()
        self.assertNotEqual(
            recipes.load(str(drafts[0][0].path)).menu_presentation,
            recipes.load(str(drafts[1][0].path)).menu_presentation)
        self.assertNotEqual(
            recipes.load(str(drafts[0][0].path)).position,
            recipes.load(str(drafts[1][0].path)).position)
        self.assertEqual(recipes.current_selection(), ("classic", None))
        releases = []
        for draft, icon, font, artwork in drafts:
            review = creator_release.prepare_export(draft)
            self.assertEqual(review.manifest["format_version"], 4)
            self.assertEqual(review.manifest["recipe"]["semantic_sha256"],
                             draft.semantic_sha256)
            self.assertEqual(review.package_sha256,
                             hashlib.sha256(review.payload).hexdigest())
            self.assertIn(("font", font), {(row[0], row[1]) for row in review.entries})
            self.assertIn(("icon:applications", icon),
                          {(row[0], row[1]) for row in review.entries})
            description = creator_release.review_text(review)
            self.assertIn(icon, description)
            self.assertIn(font, description)
            self.assertIn("Independent legal/asset review", description)
            self.assertFalse(review.attribution_review["rights_independently_verified"])
            self.assertEqual(recipes.current_selection(), ("classic", None))
            releases.append((review, icon, font, artwork))
        for review, icon, font, artwork in releases:
            target = self.root / f"{review.draft.recipe_id}.ricepack"
            receipt = creator_release.publish_export(review, target)
            self.assertEqual(target.read_bytes(), review.payload)
            self.assertEqual(receipt["package_sha256"], review.package_sha256)
            self.assertFalse(receipt["applied"])
            self.assertFalse(receipt["rights_independently_verified"])
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root / "imported")}):
            (self.root / "imported").mkdir(mode=0o700)
            for review, icon, font, artwork in releases:
                archive = self.root / f"{review.draft.recipe_id}.ricepack"
                preflight = pack.preflight_import(
                    archive, expected_manifest=review.manifest)
                self.assertTrue(preflight["ready"])
                installed = pack.import_pack(
                    archive, expected_manifest=review.manifest)
                self.assertTrue(installed["imported"])
                self.assertFalse(installed["applied"])
                loaded = recipes.load(review.draft.recipe_id)
                self.assertEqual(loaded.artwork.font, font)
                self.assertEqual(loaded.artwork.icons[0], icon)
                self.assertEqual(style_assets.read(icon), artwork)
            self.assertEqual(recipes.current_selection(), ("classic", None))

    def test_unattributed_pack_is_not_mislabeled_as_approved_release(self):
        draft = creator_workspace.create_draft("heritage")
        review = creator_release.prepare_export(draft)
        self.assertFalse(review.attribution_review["declarations_complete"])
        self.assertIn("rice.license", review.attribution_review["missing_fields"])
        self.assertIn("INCOMPLETE", creator_release.review_text(review))
        self.assertIn("NOT ownership or redistribution rights",
                      creator_release.review_text(review))
        self.assertFalse((self.root / "unapproved.ricepack").exists())

    def test_cancelled_review_never_writes_destination(self):
        draft = creator_workspace.create_draft("orbit")
        creator_release.prepare_export(draft)
        self.assertFalse((self.root / "cancelled.ricepack").exists())
        self.assertEqual(recipes.current_selection(), ("classic", None))

    def test_stale_source_and_forged_receipt_fail_before_publication(self):
        draft = creator_workspace.create_draft("heritage")
        review = creator_release.prepare_export(draft)
        destination = self.root / "blocked.ricepack"
        with self.assertRaises(creator_release.ReleaseError):
            creator_release.publish_export(
                replace(review, package_sha256="0" * 64), destination)
        self.assertFalse(destination.exists())
        with self.assertRaises(pack.PackError):
            creator_release.publish_export(
                replace(review, payload=b"bad-zip",
                        package_sha256=hashlib.sha256(b"bad-zip").hexdigest()), destination)
        self.assertFalse(destination.exists())
        revised, _ = creator_workspace.save_revision(
            draft.path, {"/name": "Changed draft"},
            expected_sha256=draft.semantic_sha256)
        with self.assertRaises(creator_release.ReleaseError):
            creator_release.publish_export(replace(review, draft=revised), destination)
        self.assertFalse(destination.exists())

    def test_export_publishes_only_reviewed_bytes_without_reserializing_assets(self):
        review = creator_release.prepare_export(self._visual_drafts()[0][0])
        destination = self.root / "frozen.ricepack"
        with (mock.patch.object(creator_workspace, "export_draft",
                                side_effect=AssertionError("unexpected re-export")),
              mock.patch.object(pack, "_visual_assets",
                                side_effect=AssertionError("unexpected asset read"))):
            creator_release.publish_export(review, destination)
        self.assertEqual(destination.read_bytes(), review.payload)

    def test_no_overwrite_symlink_or_relative_output(self):
        review = creator_release.prepare_export(creator_workspace.create_draft("orbit"))
        protected = self.root / "keep.txt"
        protected.write_bytes(b"do not overwrite")
        collision = self.root / "collision.ricepack"
        collision.symlink_to(protected)
        with self.assertRaises(pack.PackError):
            creator_release.publish_export(review, collision)
        self.assertEqual(protected.read_bytes(), b"do not overwrite")
        with self.assertRaises(pack.PackError):
            creator_release.publish_export(review, Path("relative.ricepack"))
        self.assertFalse((self.root / "relative.ricepack").exists())
        target = self.root / "once.ricepack"
        creator_release.publish_export(review, target)
        with self.assertRaises(pack.PackError):
            creator_release.publish_export(review, target)
        self.assertEqual(target.read_bytes(), review.payload)


if __name__ == "__main__":
    unittest.main()
