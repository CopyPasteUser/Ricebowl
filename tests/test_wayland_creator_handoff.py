"""Contracts for the native Creator-to-installed-Wayland acceptance runner."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from macrice.de import recipes, review
from scripts import verify_wayland_creator_handoff as runner


class NativeCreatorHandoffRunnerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.output = Path(temp.name) / "captures"
        self.output.mkdir()

    def test_ineligible_output_and_missing_native_dependencies_fail_before_creation(self):
        self.output.joinpath("existing").write_text("keep")
        with self.assertRaisesRegex(ValueError, "empty"):
            runner.capture_installed(self.output)
        self.assertEqual(sorted(p.name for p in self.output.iterdir()), ["existing"])
        self.output.joinpath("existing").unlink()
        with mock.patch.object(runner.os, "geteuid", return_value=self.output.stat().st_uid), \
             mock.patch.object(runner.shutil, "which", return_value=None):
            with self.assertRaisesRegex(ValueError, "Missing native Wayland tools"):
                runner.capture_installed(self.output)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_private_drafts_are_installed_and_real_capture_receipts_verified(self):
        requested = []

        def fake_render(token, output, *, width, height, scale):
            recipe = recipes.load(token)
            requested.append((token, width, height, scale))
            color = (26, 117, 175) if recipe.name.startswith("Heritage") else (30, 70, 90)
            Image.new("RGB", (width, height), color).save(output)
            digest = hashlib.sha256(output.read_bytes()).hexdigest()
            return {"recipe": {"id": recipe.recipe_id,
                               "semantic_sha256": review._semantic_hash(review._manifest(recipe))},
                    "output": {"sha256": digest},
                    "source": "isolated-headless-labwc-native-riceplate",
                    "mutates_active_desktop": False, "interactive_session": False}

        with mock.patch.object(runner.os, "geteuid", return_value=self.output.stat().st_uid), \
             mock.patch.object(runner.shutil, "which", return_value="/usr/bin/fake"), \
             mock.patch.object(runner.subprocess, "check_output", return_value="abc123\n"), \
             mock.patch.object(runner.render, "render", side_effect=fake_render):
            manifest = runner.capture_installed(self.output)

        self.assertEqual(len(requested), 4)
        self.assertEqual(len({item[0] for item in requested}), 2)
        self.assertEqual({(item[1], item[2], item[3]) for item in requested},
                         set(runner.GEOMETRIES))
        self.assertEqual(manifest["source_commit"], "abc123")
        self.assertEqual(len(manifest["captures"]), 4)
        self.assertFalse(manifest["capture_is_interactive"])
        self.assertEqual(json.loads((self.output / "manifest.json").read_text()), manifest)
        self.assertEqual(len(list(self.output.glob("*.png"))), 4)


if __name__ == "__main__":
    unittest.main()
