"""Contracts for the native Creator-to-installed-Wayland acceptance runner."""

import hashlib
import json
import struct
import tempfile
import zlib
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

    def test_accepts_fully_decoded_native_capture(self):
        path = self.output / "valid.png"
        Image.new("RGB", (1024, 768), (20, 50, 80)).save(path)
        self.assertEqual(runner.checked_capture_png(path, width=1024, height=768),
                         path.read_bytes())

    def test_rejects_crc_valid_but_undecodable_idat(self):
        path = self.output / "corrupt-idat.png"
        Image.new("RGB", (1024, 768), (20, 50, 80)).save(path)
        payload = bytearray(path.read_bytes())
        offset = 8
        while offset < len(payload):
            length = struct.unpack_from(">I", payload, offset)[0]
            chunk_type = bytes(payload[offset + 4:offset + 8])
            if chunk_type == b"IDAT":
                self.assertGreaterEqual(length, 2)
                # A broken zlib header with a recomputed, valid PNG CRC.
                # Chunk-only verify() passes; full load() must reject it.
                payload[offset + 8:offset + 10] = bytes([0, 0])
                crc = zlib.crc32(payload[offset + 4:offset + 8 + length])
                struct.pack_into(">I", payload, offset + 8 + length, crc)
                break
            offset += 12 + length
        else:
            self.fail("Pillow PNG fixture did not contain an IDAT chunk")
        path.write_bytes(payload)
        with Image.open(path) as image:
            image.verify()  # CRC and IEND really are intact.
        with self.assertRaisesRegex(ValueError, "undecodable"):
            runner.checked_capture_png(path, width=1024, height=768)

    def test_rejects_truncated_or_wrong_geometry_native_capture(self):
        path = self.output / "incomplete.png"
        Image.new("RGB", (1024, 768), (20, 50, 80)).save(path)
        original = path.read_bytes()
        path.write_bytes(original[:-12])  # Entire raster remains, IEND absent.
        with self.assertRaisesRegex(ValueError, "undecodable"):
            runner.checked_capture_png(path, width=1024, height=768)
        path.write_bytes(original)
        with self.assertRaisesRegex(ValueError, "geometry"):
            runner.checked_capture_png(path, width=1366, height=768)
        path.write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "geometry"):
            runner.checked_capture_png(path, width=1024, height=768)

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

    def test_two_offline_creator_ricepacks_import_and_native_capture_receipts_verified(self):
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
        self.assertEqual(len(manifest["package_imports"]), 2)
        self.assertEqual({item["pack_version"] for item in manifest["package_imports"]},
                         {4})
        self.assertEqual(len({item["semantic_sha256"]
                              for item in manifest["package_imports"]}), 2)
        self.assertEqual({item["recipe"] for item in manifest["package_imports"]},
                         {item["recipe"] for item in manifest["captures"]})
        self.assertTrue(all(len(item["package_sha256"]) == 64
                            for item in manifest["package_imports"]))
        self.assertEqual(len(manifest["captures"]), 4)
        self.assertFalse(manifest["capture_is_interactive"])
        self.assertEqual(json.loads((self.output / "manifest.json").read_text()), manifest)
        self.assertEqual(len(list(self.output.glob("*.png"))), 4)


if __name__ == "__main__":
    unittest.main()
