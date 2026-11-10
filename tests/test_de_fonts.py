"""Font selection is local, read-only until explicit private Creator import."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from macrice.cli import main
from macrice.de import fonts, pack, style_assets


class WaylandFontCatalogTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.face = self.root / "SomeFont.ttf"
        self.face.write_bytes(b"twelve-byte-face")

    def test_catalog_filters_non_ttf_symlinks_and_deduplicates(self):
        symlink = self.root / "link.ttf"
        symlink.symlink_to(self.face)
        output = (f"Sample Mono\tRegular\t{self.face}\n"
                  f"Sample Mono\tRegular\t{self.face}\n"
                  f"Sample Mono\tBold\t{symlink}\n"
                  f"Other\tBook\t{self.root / 'other.otf'}\n"
                  "malformed\n")
        with patch.object(fonts.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 0, output, "")):
            self.assertEqual(fonts.installed_fonts(), [
                fonts.FontFace("Sample Mono", "Regular", self.face)])

    def test_exact_family_and_style_no_silent_substitution(self):
        faces = [fonts.FontFace("Sample Mono", "Book", self.face),
                 fonts.FontFace("Sample Mono", "Bold Italic", self.face)]
        with patch.object(fonts, "installed_fonts", return_value=faces):
            self.assertEqual(fonts.choose_font("sample mono"), faces[0])
            self.assertEqual(fonts.choose_font("Sample Mono", "Bold Italic"), faces[1])
            with self.assertRaises(fonts.FontCatalogError):
                fonts.choose_font("Sample Mono", "Light")
            with self.assertRaises(fonts.FontCatalogError):
                fonts.choose_font("Wrong font")

    def test_unavailable_inventory_does_not_crash_into_a_fake_list(self):
        with patch.object(fonts.subprocess, "run", side_effect=FileNotFoundError):
            with self.assertRaises(fonts.FontCatalogError):
                fonts.installed_fonts()
        with patch.object(fonts.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 0, "x" * 2_000_001, "")):
            with self.assertRaises(fonts.FontCatalogError):
                fonts.installed_fonts()

    def test_root_owned_non_system_file_is_not_an_importable_font(self):
        with patch.object(style_assets.os, "geteuid", return_value=-1):
            self.assertFalse(style_assets.importable_font_source(self.face))
        self.assertFalse(style_assets.importable_font_source(self.root / "missing.ttf"))

    def test_open_font_license_and_apache_license_are_declared_portably(self):
        base = {"author": "Font author", "license": "OFL-1.1", "origin": "adapted",
                "source_reference": "https://example.org/font"}
        self.assertEqual(pack._provenance(base), base)
        apache = {**base, "license": "Apache-2.0"}
        self.assertEqual(pack._provenance(apache), apache)

    def test_installed_distribution_font_imports_as_private_digest(self):
        paths = (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf"),
            Path("/usr/share/fonts/truetype/liberation2/LiberationMono-Bold.ttf"),
        )
        fixture = next((path for path in paths
                        if style_assets.importable_font_source(path)), None)
        if fixture is None:
            self.skipTest("No safe non-symlink distro TrueType fixture installed")
        config = self.root / "config"
        config.mkdir(mode=0o700)
        provenance = {"author": "Distribution font author", "license": "custom",
                      "origin": "adapted", "source_reference": "locally installed package"}
        with patch.dict("os.environ", {"XDG_CONFIG_HOME": str(config)}):
            face = style_assets.import_asset(fixture, kind="font", label="Distribution font",
                                             provenance=provenance)
            self.assertEqual(style_assets.read(face.identifier), fixture.read_bytes())
            self.assertEqual(style_assets.entry(face.identifier).provenance, provenance)

    def test_cli_fonts_has_machine_readable_inventory(self):
        from contextlib import redirect_stdout
        from io import StringIO
        captured = StringIO()
        with patch.object(fonts, "installed_fonts", return_value=[
                fonts.FontFace("Sample Mono", "Regular", self.face)]), redirect_stdout(captured):
            self.assertEqual(main(["de", "fonts", "--json"]), 0)
        report = json.loads(captured.getvalue())
        self.assertEqual(report["format_version"], 1)
        self.assertEqual(report["fonts"][0]["family"], "Sample Mono")
        self.assertEqual(report["fonts"][0]["path"], str(self.face))


if __name__ == "__main__":
    unittest.main()
