"""Fixed real-shell Creator capture matrix: integrity, CLI and no partial writes."""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image

from macrice.cli import main as cli
from macrice.de import catalog, creator_contract, render_matrix
from macrice.de.render import RenderError


RECIPE = {"id": "classic", "schema_version": 11, "semantic_sha256": "1" * 64}


def png(width: int, height: int, color: tuple[int, int, int] = (20, 50, 90)) -> bytes:
    with io.BytesIO() as stream:
        Image.new("RGB", (width, height), color).save(stream, format="PNG")
        return stream.getvalue()


def fake_render(_recipe, output, *, width, height, scale):
    data = png(width, height)
    output.write_bytes(data)
    return {"recipe": dict(RECIPE),
            "geometry": {"width": width, "height": height, "scale": scale},
            "output": {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}}


class RenderMatrixTests(unittest.TestCase):
    def test_catalog_and_agent_contract_advertise_exact_matrix(self):
        self.assertEqual(catalog.describe()["authoring"]["render_matrix"]["cases"], 4)
        self.assertFalse(catalog.describe()["authoring"]["render_matrix"]["mutates_active_desktop"])
        api = creator_contract.describe_creator_api()
        by_name = {entry["command"]: entry for entry in api["commands"]}
        self.assertEqual(by_name["render-matrix"]["mutation_scope"], "private-file")
        self.assertEqual(by_name["render-matrix-inspect"]["mutation_scope"], "none")
        self.assertEqual(len(creator_contract.describe_render_matrix()["scenarios"]), 4)

    def test_four_real_render_receipts_publish_one_verified_private_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "matrix.zip"
            with mock.patch("macrice.de.render_matrix.render", side_effect=fake_render) as renderer:
                report = render_matrix.render_matrix("classic", output)
            self.assertEqual(renderer.call_count, 4)
            self.assertEqual([call.kwargs["scale"] for call in renderer.call_args_list],
                             [1.0, 1.0, 1.0, 1.25])
            self.assertTrue(report["verified"])
            self.assertEqual(report["recipe"], RECIPE)
            self.assertFalse(report["mutates_active_desktop"])
            self.assertEqual(report["functional_or_perceptual_accuracy"], "not_measured")
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(set(archive.namelist()), {"manifest.json", "captures/compact.png",
                        "captures/laptop.png", "captures/desktop.png", "captures/fractional.png"})
                self.assertNotIn(folder, archive.read("manifest.json").decode())
                self.assertEqual([item.compress_type for item in archive.infolist()], [0] * 5)
            self.assertEqual(render_matrix.inspect_matrix(output), report)
            self.assertFalse(list(Path(folder).glob(".ricebowl-matrix-*")))
            symbolic = Path(folder) / "alias.zip"
            symbolic.symlink_to(output)
            with self.assertRaises(render_matrix.MatrixError) as error:
                render_matrix.inspect_matrix(symbolic)
            self.assertEqual(error.exception.code, "invalid_matrix_archive")

    def test_existing_output_or_symlink_never_uses_renderer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            existing = root / "existing.zip"
            existing.write_bytes(b"user-data")
            link = root / "link.zip"
            link.symlink_to(existing)
            for path in (existing, link, Path("relative.zip"), root / "wrong.json",
                         root / "missing" / "matrix.zip"):
                with self.subTest(path=path), mock.patch("macrice.de.render_matrix.render") as render:
                    with self.assertRaises(render_matrix.MatrixError) as error:
                        render_matrix.render_matrix("classic", path)
                    self.assertEqual(error.exception.code, "invalid_matrix_request")
                    render.assert_not_called()
            self.assertEqual(existing.read_bytes(), b"user-data")

    def test_failed_second_capture_and_mismatched_receipt_leave_no_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            destination = root / "new.zip"
            count = 0

            def failed(*args, **kwargs):
                nonlocal count
                count += 1
                if count == 2:
                    raise RenderError("render_failed")
                return fake_render(*args, **kwargs)

            with mock.patch("macrice.de.render_matrix.render", side_effect=failed):
                with self.assertRaises(RenderError):
                    render_matrix.render_matrix("classic", destination)
            self.assertFalse(destination.exists())
            self.assertFalse(list(root.glob(".ricebowl-matrix-*")))

            def wrong_receipt(*args, **kwargs):
                result = fake_render(*args, **kwargs)
                result["output"]["sha256"] = "0" * 64
                return result

            with mock.patch("macrice.de.render_matrix.render", side_effect=wrong_receipt):
                with self.assertRaises(render_matrix.MatrixError):
                    render_matrix.render_matrix("classic", destination)
            self.assertFalse(destination.exists())
            self.assertFalse(list(root.glob(".ricebowl-matrix-*")))

    def test_racing_output_preserves_other_file(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "race.zip"

            def raced(*args, **kwargs):
                if not dest.exists():
                    dest.write_bytes(b"KEEP")
                return fake_render(*args, **kwargs)

            with mock.patch("macrice.de.render_matrix.render", side_effect=raced):
                with self.assertRaises(render_matrix.MatrixError) as error:
                    render_matrix.render_matrix("classic", dest)
            self.assertEqual(error.exception.code, "invalid_matrix_request")
            self.assertEqual(dest.read_bytes(), b"KEEP")

    def test_tampering_duplicate_and_unsupported_entries_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = root / "good.zip"
            with mock.patch("macrice.de.render_matrix.render", side_effect=fake_render):
                render_matrix.render_matrix("classic", original)
            with zipfile.ZipFile(original) as src:
                values = {key: src.read(key) for key in src.namelist()}

            variants = {}
            bad_capture = dict(values)
            bad_capture["captures/laptop.png"] = png(1366, 768, (255, 255, 255))
            variants["changed pixels"] = bad_capture
            bad_manifest = dict(values)
            data = json.loads(values["manifest.json"])
            data["cases"][0]["geometry"]["width"] = 999
            bad_manifest["manifest.json"] = json.dumps(data).encode()
            variants["changed geometry"] = bad_manifest
            variants["extra script"] = {**values, "setup.sh": b"#!/bin/sh\n"}
            bad_png_crc = dict(values)
            corrupt = bytearray(values["captures/laptop.png"])
            corrupt[45] ^= 1  # Interior chunk, leaving IHDR and IEND untouched.
            bad_png_crc["captures/laptop.png"] = bytes(corrupt)
            receipt = json.loads(values["manifest.json"])
            receipt["cases"][1]["sha256"] = hashlib.sha256(corrupt).hexdigest()
            bad_png_crc["manifest.json"] = json.dumps(receipt).encode()
            variants["corrupt PNG CRC with valid receipt"] = bad_png_crc

            for index, (label, entries) in enumerate(variants.items()):
                with self.subTest(label=label):
                    target = root / f"bad-{index}.zip"
                    with zipfile.ZipFile(target, "w") as out:
                        for key, content in entries.items():
                            out.writestr(*render_matrix._zip_entry(key, content))
                    with self.assertRaises(render_matrix.MatrixError) as error:
                        render_matrix.inspect_matrix(target)
                    self.assertEqual(error.exception.code, "invalid_matrix_archive")

            target = root / "duplicate.zip"
            with zipfile.ZipFile(target, "w") as out:
                for key, content in values.items():
                    out.writestr(*render_matrix._zip_entry(key, content))
                with mock.patch("warnings.warn"):
                    out.writestr(*render_matrix._zip_entry("manifest.json", values["manifest.json"]))
            with self.assertRaises(render_matrix.MatrixError):
                render_matrix.inspect_matrix(target)

    def test_cli_json_success_invalid_input_and_inspection(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "matrix.zip"
            with mock.patch("macrice.de.render_matrix.render", side_effect=fake_render), \
                 mock.patch("builtins.print") as printer:
                self.assertEqual(cli(["de", "render-matrix", "--recipe", "classic",
                                      "--output", str(target), "--json"]), 0)
            result = json.loads(printer.call_args.args[0])
            self.assertTrue(result["ok"])
            self.assertEqual(len(result["matrix"]["cases"]), 4)
            with mock.patch("builtins.print") as printer:
                self.assertEqual(cli(["de", "render-matrix-inspect", "--matrix",
                                      str(target), "--json"]), 0)
            self.assertEqual(json.loads(printer.call_args.args[0])["matrix"]["archive_sha256"],
                             result["matrix"]["archive_sha256"])
            with mock.patch("builtins.print") as printer:
                self.assertEqual(cli(["de", "render-matrix", "--recipe", "classic",
                                      "--output", str(target), "--json"]), 2)
            self.assertEqual(json.loads(printer.call_args.args[0])["error"]["code"],
                             "invalid_matrix_request")
            for argv in (["de", "render-matrix", "--width", "1024"],
                         ["de", "render-matrix-inspect", "--recipe", "classic"],
                         ["de", "catalog", "--matrix", str(target)]):
                with self.subTest(argv=argv), mock.patch("sys.stderr"):
                    self.assertEqual(cli(argv), 1)


if __name__ == "__main__":
    unittest.main()
