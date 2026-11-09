"""Creator 0.7 offline reference inference and strictly gated AI data contracts."""

import copy
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from macrice.de import creator_mapping as mapping, creator_workspace as workspace, review

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None


@unittest.skipIf(Image is None, "Optional Pillow missing")
class CreatorMappingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ricebowl-mapping-")
        self.addCleanup(self.temporary.cleanup)
        state = Path(self.temporary.name) / "state"
        state.mkdir(mode=0o700)
        environ = patch.dict(os.environ, {"XDG_STATE_HOME": str(state)})
        environ.start()
        self.addCleanup(environ.stop)
        self.draft = workspace.create_draft("heritage")
        self.manifest = review.review(str(self.draft.path))["recipe"]

    @staticmethod
    def screenshot(edge="bottom", thickness=42, *, both=False):
        image = Image.new("RGB", (320, 200), "#aabbcc")
        drawer = ImageDraw.Draw(image)
        if edge == "bottom" or both:
            drawer.rectangle((0, 200 - thickness, 319, 199), fill="#233447")
            drawer.rectangle((80, 180, 94, 184), fill="#ffffff")
            drawer.rectangle((200, 179, 220, 183), fill="#ff6600")
        if edge == "top" or both:
            drawer.rectangle((0, 0, 319, thickness - 1), fill="#233447")
            drawer.rectangle((80, 10, 94, 14), fill="#ffffff")
            drawer.rectangle((200, 10, 220, 14), fill="#ff6600")
        stream = io.BytesIO()
        image.save(stream, "PNG")
        return stream.getvalue()

    def analyze(self, data):
        return mapping.analyze(
            data, reference_sha256=hashlib.sha256(data).hexdigest(),
            recipe_sha256=self.draft.semantic_sha256)

    def validate(self, obj, data):
        return mapping.validate(
            obj, reference_sha256=hashlib.sha256(data).hexdigest(),
            recipe_sha256=self.draft.semantic_sha256, size=(320, 200),
            manifest=self.manifest)

    def test_bottom_panel_position_height_and_dominant_palette(self):
        image = self.screenshot()
        result = self.validate(self.analyze(image), image)
        changes = {item["path"]: item["value"] for item in result["suggestions"]}
        self.assertEqual(changes["/panel/position"], "bottom")
        self.assertEqual(changes["/panel/height"], 42)
        self.assertEqual(changes["/colors/background"], "#233447")
        self.assertEqual(result["regions"][0]["y"], 158)
        self.assertTrue(all(0 <= item["confidence"] <= 1
                            for item in result["suggestions"]))
        self.assertTrue(any("not inferred" in note for note in result["notes"]))

    def test_top_panel_and_ambiguous_both_edge_conservatism(self):
        top = self.screenshot("top", thickness=36)
        result = self.validate(self.analyze(top), top)
        fields = {item["path"]: item["value"] for item in result["suggestions"]}
        self.assertEqual(fields["/panel/position"], "top")
        self.assertEqual(fields["/panel/height"], 36)
        both = self.screenshot(both=True)
        result = self.validate(self.analyze(both), both)
        self.assertFalse(result["suggestions"])
        self.assertFalse(result["regions"])
        self.assertTrue(any("ambiguous" in note for note in result["notes"]))

    def test_uniform_wallpaper_does_not_invent_panel_or_semantics(self):
        image = Image.new("RGB", (320, 200), "#556677")
        stream = io.BytesIO()
        image.save(stream, "PNG")
        result = self.validate(self.analyze(stream.getvalue()), stream.getvalue())
        self.assertEqual(result["suggestions"], [])
        self.assertEqual(result["regions"], [])
        self.assertFalse(mapping.contract()["automatic_menu_or_component_recognition"])

    def test_external_mapping_can_propose_bounded_existing_panel_structure(self):
        image = self.screenshot()
        proposal = self.analyze(image)
        proposal["source"] = "external"
        proposal["suggestions"] = [
            {"path": "/menu/presentation", "value": "sidebar", "confidence": 0.4,
             "evidence": "Human or AI interpretation; no pixel-level guarantee"},
            {"path": "/panel/layout/start",
             "value": copy.deepcopy(self.manifest["panel"]["layout"]["start"]),
             "confidence": 0.2, "evidence": "Existing native node vocabulary"},
        ]
        checked = self.validate(json.dumps(proposal).encode(), image)
        changes = mapping.selected_changes(
            checked, {"/menu/presentation"}, reference_sha256=proposal["reference_sha256"],
            recipe_sha256=self.draft.semantic_sha256, size=(320, 200),
            manifest=self.manifest)
        self.assertEqual(changes, {"/menu/presentation": "sidebar"})
        previous = self.draft.path.read_bytes()
        revised, _ = workspace.save_revision(self.draft.path, changes,
                                             expected_sha256=self.draft.semantic_sha256)
        self.assertEqual(self.draft.path.read_bytes(), previous)
        self.assertEqual(review.review(str(revised.path))["recipe"]["menu"]["presentation"],
                         "sidebar")

    def test_image_identity_and_draft_fingerprints_are_mandatory(self):
        image = self.screenshot()
        result = self.analyze(image)
        with self.assertRaisesRegex(mapping.MappingError, "identity"):
            mapping.analyze(image + b"junk", reference_sha256=result["reference_sha256"],
                            recipe_sha256=self.draft.semantic_sha256)
        for key, value in (("reference_sha256", "a" * 64),
                           ("recipe_sha256", "b" * 64),
                           ("reference_size", {"width": 1, "height": 1})):
            changed = copy.deepcopy(result)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(mapping.MappingError):
                self.validate(changed, image)

    def test_untrusted_json_rejects_unknown_paths_duplicates_commands_and_bad_values(self):
        image = self.screenshot()
        original = self.analyze(image)
        for path, value in (("/system/exec", "curl example.org"),
                            ("/panel/height", 999),
                            ("/panel/layout/start", [{"type": "action", "id": "arbitrary"}]),
                            ("/colors/background", "url(evil)")):
            proposal = copy.deepcopy(original)
            proposal["suggestions"] = [{"path": path, "value": value,
                                        "confidence": 0.7, "evidence": "untrusted proposal"}]
            with self.subTest(path=path, value=value), self.assertRaises(mapping.MappingError):
                self.validate(proposal, image)
        proposal = copy.deepcopy(original)
        proposal["suggestions"].append(copy.deepcopy(proposal["suggestions"][0]))
        with self.assertRaises(mapping.MappingError):
            self.validate(proposal, image)
        proposal = copy.deepcopy(original)
        proposal["extra_field"] = "unused"
        with self.assertRaises(mapping.MappingError):
            self.validate(proposal, image)
        self.assertEqual(len(workspace.list_drafts()), 1)

    def test_strict_json_bounds_and_printable_evidence(self):
        image = self.screenshot()
        proposal = self.analyze(image)
        encoded = json.dumps(proposal)
        with self.assertRaises(mapping.MappingError):
            self.validate(encoded.encode() + b" " * mapping.MAX_MAPPING_BYTES, image)
        tampered = encoded.replace('"mapping_version": 1',
                                    '"mapping_version": 1, "mapping_version": 1')
        with self.assertRaises(mapping.MappingError):
            self.validate(tampered.encode(), image)
        proposal["suggestions"][0]["confidence"] = float("nan")
        with self.assertRaises(mapping.MappingError):
            self.validate(proposal, image)
        proposal = self.analyze(image)
        proposal["suggestions"][0]["evidence"] = "newline\ncommand"
        with self.assertRaises(mapping.MappingError):
            self.validate(proposal, image)
        proposal = self.analyze(image)
        proposal["regions"][0]["width"] = 321
        with self.assertRaises(mapping.MappingError):
            self.validate(proposal, image)

    def test_partial_selection_rechecks_integrity_and_has_no_side_effects(self):
        image = self.screenshot()
        proposal = self.validate(self.analyze(image), image)
        before = self.draft.path.read_bytes()
        self.assertEqual(len(workspace.list_drafts()), 1)
        for selected in (set(), {"/outside"}):
            with self.assertRaises(mapping.MappingError):
                mapping.selected_changes(
                    proposal, selected, reference_sha256=proposal["reference_sha256"],
                    recipe_sha256=self.draft.semantic_sha256, size=(320, 200),
                    manifest=self.manifest)
        changes = mapping.selected_changes(
            proposal, {"/panel/height"}, reference_sha256=proposal["reference_sha256"],
            recipe_sha256=self.draft.semantic_sha256, size=(320, 200),
            manifest=self.manifest)
        self.assertEqual(changes, {"/panel/height": 42})
        self.assertEqual(self.draft.path.read_bytes(), before)
        self.assertEqual(len(workspace.list_drafts()), 1)


if __name__ == "__main__":
    unittest.main()
